"""TRAFFICINTEL AI - Corridor Time-Space (Stringline) Diagram

Builds the classic signal-coordination diagram from **observed** signal state:
distance along the corridor on one axis, time on the other, with each
junction's green intervals drawn as bands.

Two things make this honest rather than decorative:

1. **Bands come from polled observations, so their edges are uncertain by up
   to one poll interval.** A conventional stringline drawn from a timing plan
   has exact edges because the plan is a specification. This one is drawn from
   measurements, so each band carries the poll interval that bounds it, and
   the UI renders that uncertainty rather than implying a precision the data
   does not have.

2. **Gaps in observation are gaps in the diagram.** When polling stopped for
   four minutes, the diagram shows four minutes of nothing, not a band
   stretched across the hole. Those gaps are returned explicitly so the client
   can hatch them.

Progression speed is reported only between adjacent junctions that both have
observed green starts in the window. Where one does not, the segment says so
instead of interpolating a band through it.
"""

from __future__ import annotations

import logging
import math
import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.entities import Corridor, Intersection, SignalStateLog

logger = logging.getLogger("trafficintel.analytics.stringline")

#: A gap larger than this multiple of the median poll spacing is treated as an
#: observation outage rather than normal jitter.
GAP_MULTIPLE = 4.0

#: Minimum observed green starts at a junction pair before a progression speed
#: is reported. Two green starts give one offset, which is an anecdote.
MIN_OFFSETS_FOR_SPEED = 3

#: An implied speed above this is not a plausible progression speed on an urban
#: arterial; it is the arithmetic of dividing a real distance by an offset too
#: small to have been measured. Reported as implausible rather than printed.
MAX_PLAUSIBLE_PROGRESSION_KPH = 160.0

EARTH_RADIUS_M = 6_371_000.0


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


class Stringline:
    """Time-space diagram data for one corridor, from observed signal state."""

    @classmethod
    def build(
        cls,
        db: Session,
        corridor_id: str,
        minutes: int = 15,
        phases: Optional[List[int]] = None,
    ) -> Dict[str, Any]:
        corridor = db.query(Corridor).filter(Corridor.id == corridor_id).first()
        if corridor is None:
            return {"status": "NOT_FOUND", "detail": "No such corridor."}

        junctions = sorted(
            corridor.intersections,
            key=lambda i: (i.latitude, i.longitude),
        )

        if len(junctions) < 2:
            return {
                "status": "NOT_COMPUTABLE",
                "corridor_id": corridor_id,
                "corridor_name": corridor.name,
                "junction_count": len(junctions),
                "detail": (
                    "A time-space diagram needs at least two junctions on the corridor. "
                    "This corridor has {}.".format(len(junctions))
                ),
                "junctions": [],
            }

        now = datetime.now(timezone.utc)
        window_start = _naive(now - timedelta(minutes=minutes))
        window_end = _naive(now)

        # Cumulative distance along the corridor from the first junction.
        positions: Dict[str, float] = {junctions[0].id: 0.0}
        cumulative = 0.0
        for previous, current in zip(junctions, junctions[1:]):
            cumulative += haversine_m(
                previous.latitude, previous.longitude,
                current.latitude, current.longitude,
            )
            positions[current.id] = cumulative

        junction_data: List[Dict[str, Any]] = []
        for junction in junctions:
            junction_data.append(
                cls._junction_bands(db, junction, positions[junction.id],
                                    window_start, window_end, phases)
            )

        with_bands = [j for j in junction_data if j["bands"]]

        return {
            "status": "COMPUTED" if with_bands else "INSUFFICIENT_DATA",
            "corridor_id": corridor_id,
            "corridor_name": corridor.name,
            "coordination_mode": corridor.coordination_mode,
            "configured_cycle_length_sec": corridor.cycle_length_sec,
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "window_minutes": minutes,
            "corridor_length_m": round(cumulative, 1),
            "junction_count": len(junctions),
            "junctions_with_observations": len(with_bands),
            "junctions": junction_data,
            "progression": cls._progression(junction_data),
            "empty_reason": (
                None if with_bands else
                "NO_SIGNAL_STATE_OBSERVED_ON_THIS_CORRIDOR_IN_WINDOW"
            ),
            "data_basis": (
                "Bands are drawn from polled observations, not from a timing plan. "
                "Each band's edges are uncertain by up to one poll interval, and "
                "periods with no observations are returned as gaps rather than "
                "drawn through."
            ),
            "distance_basis": (
                "Straight-line (great-circle) distance between junction coordinates, "
                "not road centreline distance. Progression speeds derived from it are "
                "therefore a lower bound on the true travel distance."
            ),
        }

    # ------------------------------------------------------------------

    @classmethod
    def _junction_bands(
        cls,
        db: Session,
        junction: Intersection,
        position_m: float,
        window_start: datetime,
        window_end: datetime,
        phases: Optional[List[int]],
    ) -> Dict[str, Any]:
        logs = (
            db.query(SignalStateLog)
            .filter(
                SignalStateLog.intersection_id == junction.id,
                SignalStateLog.timestamp >= window_start,
                SignalStateLog.timestamp <= window_end,
            )
            .order_by(SignalStateLog.timestamp.asc())
            .all()
        )

        if not logs:
            return {
                "intersection_id": junction.id,
                "name": junction.name,
                "code": junction.code,
                "position_m": round(position_m, 1),
                "bands": [],
                "gaps": [],
                "observation_count": 0,
                "poll_interval_sec": None,
                "empty_reason": "NO_SIGNAL_STATE_OBSERVED_IN_WINDOW",
            }

        timestamps = [log.timestamp for log in logs]
        spacings = [
            (b - a).total_seconds() for a, b in zip(timestamps, timestamps[1:])
        ]
        median_spacing = statistics.median(spacings) if spacings else None

        # Observation outages, returned so the client can hatch them rather
        # than the diagram implying continuous coverage.
        gaps: List[Dict[str, Any]] = []
        if median_spacing and median_spacing > 0:
            threshold = median_spacing * GAP_MULTIPLE
            for previous, current in zip(timestamps, timestamps[1:]):
                delta = (current - previous).total_seconds()
                if delta > threshold:
                    gaps.append({
                        "start": previous.isoformat(),
                        "end": current.isoformat(),
                        "duration_sec": round(delta, 1),
                        "reason": "NO_OBSERVATIONS_RECORDED",
                    })

        # Reconstruct green intervals per phase from consecutive observations.
        bands: List[Dict[str, Any]] = []
        open_intervals: Dict[int, datetime] = {}
        last_seen: Dict[int, datetime] = {}

        for log in logs:
            greens = set(log.green_phases or [])
            if phases:
                greens &= set(phases)

            for phase in list(open_intervals):
                if phase not in greens:
                    bands.append({
                        "phase": phase,
                        "start": open_intervals[phase].isoformat(),
                        "end": last_seen[phase].isoformat(),
                        "duration_sec": round(
                            (last_seen[phase] - open_intervals[phase]).total_seconds(), 1
                        ),
                        "closed": True,
                    })
                    del open_intervals[phase]
                    del last_seen[phase]

            for phase in greens:
                if phase not in open_intervals:
                    open_intervals[phase] = log.timestamp
                last_seen[phase] = log.timestamp

        # Intervals still green at the window edge are marked open rather than
        # given an end time nobody observed.
        for phase, started in open_intervals.items():
            bands.append({
                "phase": phase,
                "start": started.isoformat(),
                "end": last_seen[phase].isoformat(),
                "duration_sec": round(
                    (last_seen[phase] - started).total_seconds(), 1
                ),
                "closed": False,
            })

        bands.sort(key=lambda b: b["start"])

        return {
            "intersection_id": junction.id,
            "name": junction.name,
            "code": junction.code,
            "position_m": round(position_m, 1),
            "bands": bands,
            "gaps": gaps,
            "observation_count": len(logs),
            "poll_interval_sec": round(median_spacing, 2) if median_spacing else None,
            "edge_uncertainty_sec": round(median_spacing, 2) if median_spacing else None,
            "empty_reason": None,
        }

    # ------------------------------------------------------------------

    @classmethod
    def _progression(cls, junction_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Observed offsets and implied progression speed between neighbours."""
        segments: List[Dict[str, Any]] = []

        for upstream, downstream in zip(junction_data, junction_data[1:]):
            distance = downstream["position_m"] - upstream["position_m"]

            up_starts = [
                datetime.fromisoformat(b["start"]) for b in upstream["bands"]
            ]
            down_starts = [
                datetime.fromisoformat(b["start"]) for b in downstream["bands"]
            ]

            if not up_starts or not down_starts:
                segments.append({
                    "from": upstream["name"],
                    "to": downstream["name"],
                    "distance_m": round(distance, 1),
                    "status": "NOT_COMPUTABLE",
                    "detail": (
                        "No observed green starts at {}, so no offset can be "
                        "measured across this segment.".format(
                            upstream["name"] if not up_starts else downstream["name"]
                        )
                    ),
                })
                continue

            # For each upstream green start, the nearest following downstream
            # green start. Offsets are measured, never assumed from a plan.
            offsets: List[float] = []
            for start in up_starts:
                following = [d for d in down_starts if d >= start]
                if following:
                    offsets.append((min(following) - start).total_seconds())

            if len(offsets) < MIN_OFFSETS_FOR_SPEED:
                segments.append({
                    "from": upstream["name"],
                    "to": downstream["name"],
                    "distance_m": round(distance, 1),
                    "status": "INSUFFICIENT_DATA",
                    "offsets_observed": len(offsets),
                    "minimum_offsets": MIN_OFFSETS_FOR_SPEED,
                    "detail": (
                        "{} observed offset(s); {} are required before reporting a "
                        "progression speed.".format(len(offsets), MIN_OFFSETS_FOR_SPEED)
                    ),
                })
                continue

            median_offset = statistics.median(offsets)

            # An offset cannot be measured more finely than the interval
            # between observations. Below that resolution the two junctions are
            # simply indistinguishable in time, and dividing a real distance by
            # a sub-resolution offset produces an arbitrarily large number that
            # looks like a measurement. This is the single most dangerous
            # arithmetic on the page, because a slightly larger noise offset
            # yields a *plausible* speed rather than an obviously absurd one.
            resolution = max(
                upstream.get("poll_interval_sec") or 0.0,
                downstream.get("poll_interval_sec") or 0.0,
            )

            if median_offset <= resolution:
                segments.append({
                    "from": upstream["name"],
                    "to": downstream["name"],
                    "distance_m": round(distance, 1),
                    "status": "OFFSET_BELOW_MEASUREMENT_RESOLUTION",
                    "offsets_observed": len(offsets),
                    "median_offset_sec": round(median_offset, 2),
                    "measurement_resolution_sec": round(resolution, 2),
                    "implied_progression_speed_kph": None,
                    "detail": (
                        "The median observed offset ({:.2f}s) is at or below the "
                        "observation resolution ({:.2f}s), so it cannot be "
                        "distinguished from zero. These junctions appear synchronised "
                        "within the resolution of the measurement; no progression "
                        "speed can be derived from an offset this small."
                        .format(median_offset, resolution)
                    ),
                })
                continue

            speed_kph = (distance / median_offset) * 3.6

            if speed_kph > MAX_PLAUSIBLE_PROGRESSION_KPH:
                segments.append({
                    "from": upstream["name"],
                    "to": downstream["name"],
                    "distance_m": round(distance, 1),
                    "status": "IMPLIED_SPEED_IMPLAUSIBLE",
                    "offsets_observed": len(offsets),
                    "median_offset_sec": round(median_offset, 2),
                    "measurement_resolution_sec": round(resolution, 2),
                    "implied_progression_speed_kph": None,
                    "detail": (
                        "The observed offset implies {:.0f} km/h over {:.0f}m, which is "
                        "not a plausible progression speed. The offset is most likely "
                        "coincidental rather than the result of coordination, so no "
                        "speed is reported."
                        .format(speed_kph, distance)
                    ),
                })
                continue

            segments.append({
                "from": upstream["name"],
                "to": downstream["name"],
                "distance_m": round(distance, 1),
                "status": "COMPUTED",
                "offsets_observed": len(offsets),
                "median_offset_sec": round(median_offset, 2),
                "offset_spread_sec": round(max(offsets) - min(offsets), 2),
                "measurement_resolution_sec": round(resolution, 2),
                "implied_progression_speed_kph": round(speed_kph, 1),
                "caveat": (
                    "Implied from straight-line distance and the median observed "
                    "offset. It is not a measured vehicle speed, and road distance "
                    "exceeds straight-line distance, so the true speed is higher. "
                    "The offset itself is uncertain by up to {:.2f}s."
                    .format(resolution)
                ),
            })

        computed = [s for s in segments if s["status"] == "COMPUTED"]
        below_resolution = [
            s for s in segments
            if s["status"] == "OFFSET_BELOW_MEASUREMENT_RESOLUTION"
        ]

        return {
            "segments": segments,
            "segments_computed": len(computed),
            "segments_total": len(segments),
            "segments_below_resolution": len(below_resolution),
            "empty_reason": (
                None if computed
                else "ALL_OFFSETS_BELOW_MEASUREMENT_RESOLUTION" if below_resolution
                else "NO_SEGMENT_HAS_ENOUGH_OBSERVED_OFFSETS"
            ),
            "resolution_note": (
                "A progression speed is reported only when the observed offset "
                "exceeds the interval between observations. Below that, the offset "
                "cannot be distinguished from zero and any speed derived from it "
                "would be an artefact of the division, not a measurement."
            ),
        }
