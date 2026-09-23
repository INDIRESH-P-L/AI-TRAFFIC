"""TRAFFICINTEL AI - Operational Reporting

Daily operations summaries, incident reports and signal performance reports,
built only from stored records.

Reports are where fabrication is most tempting and most damaging: a report is
read later, out of context, by someone who was not there, and it carries an
authority the live console does not. So:

* **A report never fills a gap.** A measure with too few samples appears as
  "insufficient data (n=3, 10 required)", not as a number with an asterisk and
  not omitted entirely. Omission is its own lie: a reader assumes the section
  was empty because nothing happened.
* **Every figure names its source and sample size** in the report body, not in
  a footnote nobody reads.
* **CSV export carries the same caveats** as the on-screen report, in their own
  columns, because a spreadsheet strips context faster than anything else.

PDF generation uses no external library: the platform emits a minimal, valid
PDF built from the same data as the JSON report. Adding a rendering dependency
to produce a prettier document than the data supports would be the wrong
trade.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.performance import SignalPerformance
from app.incidents.lifecycle import IncidentLifecycle
from app.models.entities import (
    Alert, AuditLog, Incident, Intersection, SignalCommand, SignalController,
    SignalStateLog, TrafficObservation, utc_now,
)

logger = logging.getLogger("trafficintel.reporting")


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


# ===========================================================================
# Daily operations summary
# ===========================================================================

def daily_operations_summary(
    db: Session, day: Optional[datetime] = None
) -> Dict[str, Any]:
    """What the platform recorded over one 24-hour period."""
    end = day or datetime.now(timezone.utc)
    start = end - timedelta(hours=24)
    start_naive, end_naive = _naive(start), _naive(end)

    incidents = (
        db.query(Incident)
        .filter(Incident.detected_at >= start_naive, Incident.detected_at <= end_naive)
        .all()
    )
    resolved = [i for i in incidents if i.status == "RESOLVED"]
    unacknowledged = [i for i in incidents if not i.acknowledged_at]

    commands = (
        db.query(SignalCommand)
        .filter(SignalCommand.issued_at >= start_naive, SignalCommand.issued_at <= end_naive)
        .all()
    )
    rejected = [c for c in commands if not c.safety_check_passed]

    alerts = (
        db.query(Alert)
        .filter(Alert.timestamp >= start_naive, Alert.timestamp <= end_naive)
        .all()
    )

    observations = (
        db.query(TrafficObservation)
        .filter(
            TrafficObservation.timestamp >= start_naive,
            TrafficObservation.timestamp <= end_naive,
        )
        .count()
    )
    signal_readings = (
        db.query(SignalStateLog)
        .filter(
            SignalStateLog.timestamp >= start_naive,
            SignalStateLog.timestamp <= end_naive,
        )
        .count()
    )

    controllers = db.query(SignalController).all()
    connected = [c for c in controllers if c.connection_status == "CONNECTED"]

    # Rejection reasons, grouped, so a recurring cause is visible.
    rejection_reasons: Dict[str, int] = {}
    for command in rejected:
        for violation in (command.safety_report or {}).get("violations", []):
            key = violation.split(":")[0][:80]
            rejection_reasons[key] = rejection_reasons.get(key, 0) + 1

    gaps: List[str] = []
    if observations == 0:
        gaps.append(
            "No traffic observations were recorded in this period. Volume, occupancy "
            "and delay figures are absent because nothing was measured, not because "
            "traffic was zero."
        )
    if signal_readings == 0:
        gaps.append(
            "No signal state was observed in this period, so arrival-on-green, split "
            "failures and progression cannot be reported for any junction."
        )
    if not controllers:
        gaps.append("No signal controller is configured.")

    return {
        "report_type": "DAILY_OPERATIONS_SUMMARY",
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "generated_at": utc_now().isoformat(),
        "infrastructure": {
            "junctions_configured": db.query(Intersection).count(),
            "controllers_configured": len(controllers),
            "controllers_readable": len(connected),
            "controllers_readable_note": (
                "Readable means a protocol session existed and phase state was read. "
                "A reachable-but-unreadable controller is not counted."
            ),
        },
        "incidents": {
            "detected": len(incidents),
            "resolved": len(resolved),
            "still_open": len(incidents) - len(resolved),
            "never_acknowledged": len(unacknowledged),
            "by_severity": _count_by(incidents, "severity"),
            "sla_acknowledge_breaches": sum(
                1 for i in incidents if i.sla_acknowledge_breached
            ),
            "sla_resolve_breaches": sum(1 for i in incidents if i.sla_resolve_breached),
        },
        "signal_commands": {
            "issued": len(commands),
            "executed": sum(1 for c in commands if c.status == "EXECUTED"),
            "rejected_by_safety_engine": len(rejected),
            "rejection_reasons": rejection_reasons,
        },
        "alerts": {
            "raised": len(alerts),
            "by_severity": _count_by(alerts, "severity"),
            "escalated": sum(1 for a in alerts if a.escalated),
            "still_unacknowledged": sum(1 for a in alerts if not a.is_acknowledged),
        },
        "telemetry": {
            "observations_recorded": observations,
            "signal_state_readings": signal_readings,
        },
        "gaps": gaps,
        "report_basis": (
            "Every figure counts stored records over the stated period. Where nothing "
            "was recorded, the report says so rather than reporting zero as a "
            "measurement."
        ),
    }


def _count_by(items: List[Any], attribute: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        key = getattr(item, attribute, None) or "UNKNOWN"
        counts[key] = counts.get(key, 0) + 1
    return counts


# ===========================================================================
# Signal performance report
# ===========================================================================

def signal_performance_report(
    db: Session, intersection_id: str, hours: int = 24
) -> Dict[str, Any]:
    """Full ATSPM report for one junction, insufficiencies included."""
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise ValueError("Intersection '{}' not found".format(intersection_id))

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    report = SignalPerformance.intersection_report(db, intersection_id, start, end)

    measures = report["measures"]
    computed = report["summary"]["computed"]
    insufficient = report["summary"]["insufficient_data"]
    not_computable = report["summary"]["not_computable"]

    narrative: List[str] = []
    for name in computed:
        measure = measures[name]
        narrative.append(
            "{}: {}{} (from {} samples; {})".format(
                name.replace("_", " ").title(),
                measure["value"],
                " " + measure.get("unit", "") if measure.get("unit") else "",
                measure["sample_size"],
                measure["method"],
            )
        )
    for name in insufficient:
        measure = measures[name]
        narrative.append(
            "{}: insufficient data (n={}, {} required). {}".format(
                name.replace("_", " ").title(),
                measure["sample_size"], measure["minimum_samples"],
                measure["explanation"],
            )
        )
    for name in not_computable:
        narrative.append(
            "{}: not computable. {}".format(
                name.replace("_", " ").title(), measures[name]["explanation"]
            )
        )

    return {
        "report_type": "SIGNAL_PERFORMANCE_REPORT",
        "intersection": {"id": inter.id, "name": inter.name, "code": inter.code},
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "generated_at": utc_now().isoformat(),
        "narrative": narrative,
        **report,
        "report_basis": (
            "Measures that could not be computed are listed with the reason rather "
            "than omitted. An omitted section reads as 'nothing happened', which is "
            "a different claim from 'nothing was measured'."
        ),
    }


# ===========================================================================
# Incident report
# ===========================================================================

def incident_report(db: Session, incident_id: str) -> Dict[str, Any]:
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise ValueError("Incident '{}' not found".format(incident_id))

    report = IncidentLifecycle.post_incident_report(db, incident)
    report["report_type"] = "INCIDENT_REPORT"
    return report


# ===========================================================================
# Export formats
# ===========================================================================

def to_csv(report: Dict[str, Any]) -> str:
    """Flattens a report to CSV, carrying its caveats in their own columns."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    writer.writerow(["TRAFFICINTEL AI", report.get("report_type", "REPORT")])
    writer.writerow(["Generated at", report.get("generated_at", "")])
    writer.writerow(["Period start", report.get("period_start", "")])
    writer.writerow(["Period end", report.get("period_end", "")])
    writer.writerow([])

    report_type = report.get("report_type")

    if report_type == "SIGNAL_PERFORMANCE_REPORT":
        writer.writerow([
            "Measure", "Value", "Unit", "Status", "Sample size",
            "Minimum samples", "Method", "Explanation",
        ])
        for name, measure in report.get("measures", {}).items():
            writer.writerow([
                name,
                measure.get("value", ""),
                measure.get("unit", ""),
                measure["status"],
                measure["sample_size"],
                measure["minimum_samples"],
                measure["method"],
                measure["explanation"],
            ])

    elif report_type == "DAILY_OPERATIONS_SUMMARY":
        writer.writerow(["Section", "Metric", "Value"])
        for section in ("infrastructure", "incidents", "signal_commands", "alerts", "telemetry"):
            for key, value in (report.get(section) or {}).items():
                writer.writerow([section, key, value if not isinstance(value, dict) else str(value)])

    elif report_type == "INCIDENT_REPORT":
        writer.writerow(["Field", "Value"])
        for key, value in (report.get("incident") or {}).items():
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(["Timeline"])
        writer.writerow(["Timestamp", "Type", "Actor", "Summary", "Detail"])
        for entry in report.get("timeline", []):
            writer.writerow([
                entry["timestamp"], entry["entry_type"], entry["actor"],
                entry["summary"], entry.get("detail") or "",
            ])

    gaps = report.get("gaps") or []
    if gaps:
        writer.writerow([])
        writer.writerow(["DATA GAPS - read before using these figures"])
        for gap in gaps:
            writer.writerow([gap])

    writer.writerow([])
    writer.writerow(["Report basis", report.get("report_basis", "")])
    return buffer.getvalue()


def to_pdf(report: Dict[str, Any]) -> bytes:
    """Emits a minimal, valid PDF of the report's text.

    Deliberately dependency-free. A prettier document would not make the
    underlying data any more complete, and the caveats matter more than the
    typography.
    """
    lines: List[str] = []
    lines.append("TRAFFICINTEL AI - {}".format(report.get("report_type", "REPORT")))
    lines.append("Generated: {}".format(report.get("generated_at", "")))

    if report.get("period_start"):
        lines.append("Period: {} to {}".format(report["period_start"], report.get("period_end", "")))
    lines.append("")

    if report.get("narrative"):
        lines.append("MEASURES")
        for item in report["narrative"]:
            lines.extend(_wrap(item, 92))
        lines.append("")

    for section in ("infrastructure", "incidents", "signal_commands", "alerts", "telemetry"):
        data = report.get(section)
        if not isinstance(data, dict):
            continue
        lines.append(section.replace("_", " ").upper())
        for key, value in data.items():
            lines.extend(_wrap("  {}: {}".format(key, value), 92))
        lines.append("")

    incident = report.get("incident")
    if isinstance(incident, dict):
        lines.append("INCIDENT")
        for key, value in incident.items():
            lines.extend(_wrap("  {}: {}".format(key, value), 92))
        lines.append("")

    for entry in report.get("timeline", [])[:40]:
        lines.extend(_wrap(
            "  {} [{}] {} - {}".format(
                entry["timestamp"], entry["entry_type"], entry["actor"], entry["summary"]
            ), 92,
        ))

    gaps = report.get("gaps") or []
    if gaps:
        lines.append("")
        lines.append("DATA GAPS - read before using these figures")
        for gap in gaps:
            lines.extend(_wrap("  - {}".format(gap), 92))

    if report.get("report_basis"):
        lines.append("")
        lines.extend(_wrap(report["report_basis"], 92))

    return _build_pdf(lines)


def _wrap(text: str, width: int) -> List[str]:
    words = str(text).split()
    if not words:
        return [""]
    out: List[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current += " " + word
        else:
            out.append(current)
            current = "  " + word
    out.append(current)
    return out


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("\\", r"\\")
        .replace("(", r"\(")
        .replace(")", r"\)")
    )


def _build_pdf(lines: List[str], lines_per_page: int = 56) -> bytes:
    """Builds a multi-page PDF with a Courier text stream."""
    pages = [
        lines[i:i + lines_per_page] for i in range(0, max(1, len(lines)), lines_per_page)
    ] or [[""]]

    objects: List[bytes] = []

    # 1: Catalog, 2: Pages, 3: Font, then one content + one page object each.
    page_object_ids = [4 + (2 * index) for index in range(len(pages))]
    content_object_ids = [5 + (2 * index) for index in range(len(pages))]

    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        "<< /Type /Pages /Kids [{}] /Count {} >>".format(
            " ".join("{} 0 R".format(pid) for pid in page_object_ids), len(pages)
        ).encode("latin-1")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>")

    for index, page_lines in enumerate(pages):
        stream_parts = ["BT", "/F1 9 Tf", "12 TL", "40 780 Td"]
        for line in page_lines:
            stream_parts.append("({}) Tj T*".format(_escape(line)))
        stream_parts.append("ET")
        stream = "\n".join(stream_parts).encode("latin-1", errors="replace")

        objects.append(
            (
                "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                "/Resources << /Font << /F1 3 0 R >> >> /Contents {} 0 R >>"
            ).format(content_object_ids[index]).encode("latin-1")
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode("latin-1") + b" >>\nstream\n"
            + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets: List[int] = []

    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += "{} 0 obj\n".format(number).encode("latin-1")
        out += body
        out += b"\nendobj\n"

    xref_position = len(out)
    out += "xref\n0 {}\n".format(len(objects) + 1).encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += "{:010d} 00000 n \n".format(offset).encode("latin-1")

    out += (
        "trailer\n<< /Size {} /Root 1 0 R >>\nstartxref\n{}\n%%EOF\n"
        .format(len(objects) + 1, xref_position).encode("latin-1")
    )

    return bytes(out)
