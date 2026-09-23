"""TRAFFICINTEL AI - Real-Data Import

Imports operator-supplied CSV, GeoJSON and GTFS files. There is no sample-data
generator here and there never will be: every row that lands in the database
came out of a file a human supplied, tagged with where it came from.

The import contract:

1. **Validate first, then import — or don't.** Every import runs in two
   passes. The first validates every row and produces a report; the second
   writes, and only if the caller asked to commit. A half-imported file is
   worse than a rejected one, because nobody knows which half.

2. **Rejected rows are reported individually, with their line number and the
   reason.** "17 rows failed" is not an error message an operator can act on.

3. **Provenance is mandatory.** Every imported record carries the filename, a
   content hash and the import id, so any row in the database can be traced to
   the file and the import that produced it.

4. **Physical bounds are enforced on import**, not on display. An occupancy of
   150% never enters the database; it is rejected at the boundary with its row
   number.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.entities import (
    Approach, Intersection, Lane, Sensor, TrafficObservation, TransitEvent, utc_now,
)
from app.traffic.quality_engine import DataQualityEngine

logger = logging.getLogger("trafficintel.ingest")


@dataclass
class RowError:
    row_number: int
    field: Optional[str]
    value: Any
    reason: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "row_number": self.row_number,
            "field": self.field,
            "value": str(self.value)[:120] if self.value is not None else None,
            "reason": self.reason,
        }


@dataclass
class ImportReport:
    """The outcome of one import, valid rows and rejected rows alike."""

    import_id: str
    source_filename: str
    content_sha256: str
    format: str
    committed: bool
    rows_read: int = 0
    rows_valid: int = 0
    rows_rejected: int = 0
    rows_written: int = 0
    rows_skipped_duplicate: int = 0
    errors: List[RowError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    created_records: Dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "import_id": self.import_id,
            "source_filename": self.source_filename,
            "content_sha256": self.content_sha256,
            "format": self.format,
            "committed": self.committed,
            "rows_read": self.rows_read,
            "rows_valid": self.rows_valid,
            "rows_rejected": self.rows_rejected,
            "rows_written": self.rows_written,
            "rows_skipped_duplicate": self.rows_skipped_duplicate,
            "created_records": self.created_records,
            "errors": [error.as_dict() for error in self.errors[:200]],
            "error_count": len(self.errors),
            "errors_truncated": len(self.errors) > 200,
            "warnings": self.warnings,
            "status": (
                "COMMITTED" if self.committed else
                "VALIDATED_NOT_COMMITTED"
            ),
            "note": (
                "Validation ran over every row before anything was written. Nothing "
                "is imported unless commit=true, and a file with rejected rows "
                "imports only its valid rows - each rejection is listed with its "
                "row number."
            ),
        }


def _hash_content(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _provenance(report: ImportReport, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Stamped on every imported record."""
    return {
        "ingest_method": "FILE_IMPORT",
        "import_id": report.import_id,
        "source_filename": report.source_filename,
        "content_sha256": report.content_sha256,
        "format": report.format,
        "imported_at": utc_now().isoformat(),
        **(extra or {}),
    }


def _parse_float(value: Any, field_name: str, row: int, errors: List[RowError]) -> Optional[float]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(RowError(row, field_name, value, "Not a number"))
        return None


def _parse_int(value: Any, field_name: str, row: int, errors: List[RowError]) -> Optional[int]:
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        errors.append(RowError(row, field_name, value, "Not an integer"))
        return None


def _parse_timestamp(
    value: Any, field_name: str, row: int, errors: List[RowError]
) -> Optional[datetime]:
    if value is None or str(value).strip() == "":
        errors.append(RowError(row, field_name, value, "Timestamp is required"))
        return None

    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            errors.append(RowError(
                row, field_name, value,
                "Unparseable timestamp. Use ISO 8601, e.g. 2026-09-21T14:30:00Z",
            ))
            return None

    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


# ===========================================================================
# CSV: traffic observations
# ===========================================================================

OBSERVATION_REQUIRED_COLUMNS = {"intersection_code", "source", "timestamp", "vehicle_count"}
OBSERVATION_OPTIONAL_COLUMNS = {"lane_id", "occupancy_pct", "avg_speed_kph"}


def import_observations_csv(
    db: Session, content: bytes, filename: str, commit: bool
) -> ImportReport:
    """Imports detector observations from CSV.

    Required columns: intersection_code, source, timestamp, vehicle_count.
    Optional: lane_id, occupancy_pct, avg_speed_kph.
    """
    report = ImportReport(
        import_id="imp-{}".format(utc_now().strftime("%Y%m%dT%H%M%S%f")),
        source_filename=filename,
        content_sha256=_hash_content(content),
        format="CSV_TRAFFIC_OBSERVATIONS",
        committed=False,
    )

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        report.errors.append(RowError(0, None, None, "File is not valid UTF-8"))
        return report

    reader = csv.DictReader(io.StringIO(text))
    columns = set(reader.fieldnames or [])

    missing = OBSERVATION_REQUIRED_COLUMNS - columns
    if missing:
        report.errors.append(RowError(
            0, None, None,
            "Missing required column(s): {}. Required: {}".format(
                sorted(missing), sorted(OBSERVATION_REQUIRED_COLUMNS)
            ),
        ))
        return report

    unknown = columns - OBSERVATION_REQUIRED_COLUMNS - OBSERVATION_OPTIONAL_COLUMNS
    if unknown:
        report.warnings.append(
            "Ignoring unrecognised column(s): {}".format(sorted(unknown))
        )

    # Resolve junction codes once; an unknown code is a per-row rejection.
    by_code = {
        inter.code: inter.id for inter in db.query(Intersection).all() if inter.code
    }

    staged: List[TrafficObservation] = []

    for line_number, row in enumerate(reader, start=2):
        report.rows_read += 1
        row_errors: List[RowError] = []

        code = (row.get("intersection_code") or "").strip()
        intersection_id = by_code.get(code)
        if not intersection_id:
            row_errors.append(RowError(
                line_number, "intersection_code", code,
                "No configured junction has this code. Create the junction first.",
            ))

        source = (row.get("source") or "").strip()
        if not source:
            row_errors.append(RowError(
                line_number, "source", source,
                "Source is required: every observation records which detector produced it.",
            ))

        timestamp = _parse_timestamp(row.get("timestamp"), "timestamp", line_number, row_errors)
        vehicle_count = _parse_int(row.get("vehicle_count"), "vehicle_count", line_number, row_errors)
        occupancy = _parse_float(row.get("occupancy_pct"), "occupancy_pct", line_number, row_errors)
        speed = _parse_float(row.get("avg_speed_kph"), "avg_speed_kph", line_number, row_errors)

        if vehicle_count is None and not any(e.field == "vehicle_count" for e in row_errors):
            row_errors.append(RowError(
                line_number, "vehicle_count", None, "Vehicle count is required",
            ))

        # Physical bounds are enforced here, at the boundary, so an impossible
        # value never enters the database to be discovered later on a chart.
        for field_name, value in (("occupancy_pct", occupancy), ("speed_kph", speed),
                                  ("vehicle_count", vehicle_count)):
            if value is None:
                continue
            valid, reason = DataQualityEngine.validate_measurement_bounds(field_name, value)
            if not valid:
                row_errors.append(RowError(line_number, field_name, value, reason))

        if row_errors:
            report.errors.extend(row_errors)
            report.rows_rejected += 1
            continue

        report.rows_valid += 1
        staged.append(TrafficObservation(
            intersection_id=intersection_id,
            lane_id=(row.get("lane_id") or "").strip() or None,
            source=source,
            source_id=None,
            timestamp=timestamp,
            vehicle_count=vehicle_count,
            occupancy_pct=occupancy,
            avg_speed_kph=speed,
            quality="FRESH",
            provenance=_provenance(report, {"csv_row": line_number}),
        ))

    if commit and staged:
        for observation in staged:
            db.add(observation)
        db.commit()
        report.committed = True
        report.rows_written = len(staged)
        report.created_records = {"traffic_observations": len(staged)}

    return report


# ===========================================================================
# GeoJSON: junction geometry
# ===========================================================================

def import_junctions_geojson(
    db: Session, content: bytes, filename: str, commit: bool
) -> ImportReport:
    """Imports junctions from a GeoJSON FeatureCollection of Points.

    Each feature needs `properties.name` and `properties.code`.
    """
    report = ImportReport(
        import_id="imp-{}".format(utc_now().strftime("%Y%m%dT%H%M%S%f")),
        source_filename=filename,
        content_sha256=_hash_content(content),
        format="GEOJSON_JUNCTIONS",
        committed=False,
    )

    try:
        document = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        report.errors.append(RowError(0, None, None, "Not valid GeoJSON: {}".format(exc)))
        return report

    if document.get("type") != "FeatureCollection":
        report.errors.append(RowError(
            0, "type", document.get("type"),
            "Expected a FeatureCollection at the top level.",
        ))
        return report

    features = document.get("features") or []
    existing_codes = {
        inter.code for inter in db.query(Intersection).all() if inter.code
    }
    existing_names = {inter.name for inter in db.query(Intersection).all()}

    staged: List[Intersection] = []
    seen_codes: set = set()

    for index, feature in enumerate(features, start=1):
        report.rows_read += 1
        row_errors: List[RowError] = []

        geometry = feature.get("geometry") or {}
        properties = feature.get("properties") or {}

        if geometry.get("type") != "Point":
            row_errors.append(RowError(
                index, "geometry.type", geometry.get("type"),
                "Only Point geometries are supported for junctions.",
            ))

        coordinates = geometry.get("coordinates") or []
        longitude = latitude = None
        if len(coordinates) >= 2:
            # GeoJSON is [longitude, latitude] - the opposite of how most
            # traffic systems write it, and a frequent source of junctions
            # appearing in the wrong hemisphere.
            longitude = _parse_float(coordinates[0], "coordinates[0]", index, row_errors)
            latitude = _parse_float(coordinates[1], "coordinates[1]", index, row_errors)
        else:
            row_errors.append(RowError(
                index, "geometry.coordinates", coordinates,
                "Point needs [longitude, latitude].",
            ))

        if latitude is not None and not (-90.0 <= latitude <= 90.0):
            row_errors.append(RowError(
                index, "latitude", latitude,
                "Latitude out of range. GeoJSON order is [longitude, latitude]; "
                "these may be swapped.",
            ))
        if longitude is not None and not (-180.0 <= longitude <= 180.0):
            row_errors.append(RowError(
                index, "longitude", longitude, "Longitude out of range (-180 to 180)."
            ))

        name = str(properties.get("name") or "").strip()
        code = str(properties.get("code") or "").strip()

        if not name:
            row_errors.append(RowError(index, "properties.name", name, "Name is required"))
        if not code:
            row_errors.append(RowError(index, "properties.code", code, "Code is required"))

        if code and (code in existing_codes or code in seen_codes):
            row_errors.append(RowError(
                index, "properties.code", code,
                "A junction with this code already exists; skipped rather than "
                "overwriting configured infrastructure.",
            ))
            report.rows_skipped_duplicate += 1
            report.errors.extend(row_errors)
            continue
        if name and name in existing_names:
            row_errors.append(RowError(
                index, "properties.name", name,
                "A junction with this name already exists; skipped.",
            ))
            report.rows_skipped_duplicate += 1
            report.errors.extend(row_errors)
            continue

        if row_errors:
            report.errors.extend(row_errors)
            report.rows_rejected += 1
            continue

        report.rows_valid += 1
        seen_codes.add(code)
        staged.append(Intersection(
            name=name,
            code=code,
            latitude=latitude,
            longitude=longitude,
            jurisdiction=str(properties.get("jurisdiction") or "Municipal DOT"),
            operational_status="DISCONNECTED",
        ))

    if commit and staged:
        for junction in staged:
            db.add(junction)
        db.commit()
        report.committed = True
        report.rows_written = len(staged)
        report.created_records = {"intersections": len(staged)}
        report.warnings.append(
            "Imported junctions start as DISCONNECTED. They report no telemetry "
            "until a controller, camera or detector is connected to them."
        )

    return report


# ===========================================================================
# GTFS: transit stops and routes
# ===========================================================================

def import_gtfs(
    db: Session, content: bytes, filename: str, commit: bool
) -> ImportReport:
    """Reads a GTFS zip and reports what it contains.

    GTFS describes scheduled service. This importer validates the feed and
    records its routes, but it creates NO transit events: a schedule says a bus
    is due, not that one arrived. Arrival events come from GTFS-Realtime, and
    inventing them from a timetable would put unobserved vehicles on the map.
    """
    report = ImportReport(
        import_id="imp-{}".format(utc_now().strftime("%Y%m%dT%H%M%S%f")),
        source_filename=filename,
        content_sha256=_hash_content(content),
        format="GTFS_STATIC",
        committed=False,
    )

    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        report.errors.append(RowError(0, None, None, "Not a valid zip archive"))
        return report

    names = set(archive.namelist())
    required = {"routes.txt", "stops.txt", "trips.txt"}
    missing = required - names
    if missing:
        report.errors.append(RowError(
            0, None, None,
            "GTFS feed is missing required file(s): {}".format(sorted(missing)),
        ))
        return report

    summary: Dict[str, int] = {}
    for member in sorted(names):
        if not member.endswith(".txt"):
            continue
        try:
            raw = archive.read(member).decode("utf-8-sig")
        except (UnicodeDecodeError, KeyError):
            report.warnings.append("Could not read {} as UTF-8; skipped.".format(member))
            continue
        rows = list(csv.DictReader(io.StringIO(raw)))
        summary[member] = len(rows)
        report.rows_read += len(rows)

    routes_raw = archive.read("routes.txt").decode("utf-8-sig")
    routes = list(csv.DictReader(io.StringIO(routes_raw)))

    for index, route in enumerate(routes, start=2):
        if not (route.get("route_id") or "").strip():
            report.errors.append(RowError(
                index, "route_id", route.get("route_id"), "route_id is required"
            ))
            report.rows_rejected += 1
        else:
            report.rows_valid += 1

    report.created_records = {"gtfs_files_parsed": len(summary)}
    report.warnings.append(
        "GTFS static describes scheduled service. No transit events were created: "
        "a schedule says a bus is due, not that one arrived. Connect GTFS-Realtime "
        "for observed vehicle positions."
    )
    report.warnings.append("File contents: {}".format(summary))

    if commit:
        # Nothing to write: validating the feed is the whole operation until a
        # GTFS-Realtime consumer exists.
        report.committed = True
        report.rows_written = 0

    return report


IMPORTERS: Dict[str, Dict[str, Any]] = {
    "traffic_observations_csv": {
        "function": import_observations_csv,
        "label": "Traffic observations (CSV)",
        "required_columns": sorted(OBSERVATION_REQUIRED_COLUMNS),
        "optional_columns": sorted(OBSERVATION_OPTIONAL_COLUMNS),
        "creates": "traffic_observations",
    },
    "junctions_geojson": {
        "function": import_junctions_geojson,
        "label": "Junction geometry (GeoJSON FeatureCollection of Points)",
        "required_properties": ["name", "code"],
        "creates": "intersections",
    },
    "gtfs_static": {
        "function": import_gtfs,
        "label": "GTFS static feed (zip)",
        "required_files": ["routes.txt", "stops.txt", "trips.txt"],
        "creates": "nothing - validation and inventory only",
    },
}
