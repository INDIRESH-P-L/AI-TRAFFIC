"""TRAFFICINTEL AI - Signal Performance Measures

Automated Traffic Signal Performance Measures (ATSPM) computed from stored
observations and observed signal state. Nothing here is modelled, simulated or
back-filled.

Every measure returns the same shape:

    {
      "value": <number or None>,
      "status": "COMPUTED" | "INSUFFICIENT_DATA" | "NOT_COMPUTABLE",
      "sample_size": int,
      "minimum_samples": int,
      "method": "<named method with its source>",
      "inputs_used": [...],
      "explanation": "<why it is or is not computable>"
    }

`INSUFFICIENT_DATA` and `NOT_COMPUTABLE` are different, and the distinction
matters to an operator:

  * INSUFFICIENT_DATA - the right inputs exist but there are too few of them.
    Wait, or widen the window.
  * NOT_COMPUTABLE    - a required input does not exist at all (no signal log,
    no lane-to-phase mapping). Connect something; waiting will not help.

Minimum sample sizes are deliberately conservative. A delay figure computed
from four observations is not a measurement, it is an anecdote with a decimal
point.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.entities import (
    Approach, Lane, SignalController, SignalPhase, SignalStateLog,
    TrafficMetric, TrafficObservation,
)

logger = logging.getLogger("trafficintel.analytics")

COMPUTED = "COMPUTED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_COMPUTABLE = "NOT_COMPUTABLE"

# --- Minimum sample sizes --------------------------------------------------
MIN_SAMPLES_VOLUME = 5
MIN_SAMPLES_OCCUPANCY = 5
MIN_SAMPLES_SPEED = 5
MIN_SAMPLES_DELAY = 10
MIN_CYCLES_SPLIT_FAILURE = 3
MIN_ARRIVALS_AOG = 20
MIN_LOGS_PROGRESSION = 10

# Occupancy at the end of green above which the phase is treated as having
# failed to clear its queue. ATSPM practice uses ~80% green occupancy ratio.
SPLIT_FAILURE_OCCUPANCY_PCT = 80.0


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _result(
    value: Optional[float],
    status: str,
    sample_size: int,
    minimum: int,
    method: str,
    inputs: List[str],
    explanation: str,
    **extra: Any,
) -> Dict[str, Any]:
    return {
        "value": value,
        "status": status,
        "sample_size": sample_size,
        "minimum_samples": minimum,
        "method": method,
        "inputs_used": inputs,
        "explanation": explanation,
        **extra,
    }


class SignalPerformance:
    """Computes ATSPM-style measures from what the platform actually stored."""

    # ------------------------------------------------------------------
    # Volume & throughput
    # ------------------------------------------------------------------

    @classmethod
    def throughput(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Vehicles per hour, extrapolated only from windows we actually know."""
        metrics = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
                TrafficMetric.vehicle_count.isnot(None),
                TrafficMetric.sample_window_sec.isnot(None),
            )
            .all()
        )

        if not metrics:
            # Check whether counts exist but windows do not, so the operator is
            # told the real problem rather than "no data".
            unwindowed = (
                db.query(TrafficMetric)
                .filter(
                    TrafficMetric.intersection_id == intersection_id,
                    TrafficMetric.timestamp >= _naive(start),
                    TrafficMetric.timestamp <= _naive(end),
                    TrafficMetric.vehicle_count.isnot(None),
                )
                .count()
            )
            if unwindowed:
                return _result(
                    None, NOT_COMPUTABLE, unwindowed, MIN_SAMPLES_VOLUME,
                    "Sum of counts / observation window",
                    ["traffic_metrics.vehicle_count", "traffic_metrics.sample_window_sec"],
                    (
                        "{} counts exist in this window but none records the observation "
                        "window they were accumulated over, so they cannot be converted "
                        "to an hourly rate.".format(unwindowed)
                    ),
                )
            return _result(
                None, INSUFFICIENT_DATA, 0, MIN_SAMPLES_VOLUME,
                "Sum of counts / observation window",
                ["traffic_metrics.vehicle_count", "traffic_metrics.sample_window_sec"],
                "No vehicle counts were recorded in this window.",
            )

        if len(metrics) < MIN_SAMPLES_VOLUME:
            return _result(
                None, INSUFFICIENT_DATA, len(metrics), MIN_SAMPLES_VOLUME,
                "Sum of counts / observation window",
                ["traffic_metrics.vehicle_count", "traffic_metrics.sample_window_sec"],
                "{} samples is below the {} required to report a throughput rate.".format(
                    len(metrics), MIN_SAMPLES_VOLUME
                ),
            )

        total_vehicles = sum(m.vehicle_count for m in metrics)
        total_seconds = sum(m.sample_window_sec for m in metrics)
        vph = round(total_vehicles * 3600.0 / total_seconds, 1) if total_seconds > 0 else None

        return _result(
            vph, COMPUTED, len(metrics), MIN_SAMPLES_VOLUME,
            "Sum of counts / sum of observation windows, scaled to one hour",
            ["traffic_metrics.vehicle_count", "traffic_metrics.sample_window_sec"],
            "{} vehicles observed across {:.0f}s of measured windows.".format(
                total_vehicles, total_seconds
            ),
            unit="veh/h",
            total_vehicles=total_vehicles,
            observed_seconds=round(total_seconds, 1),
            coverage_pct=round(
                100.0 * total_seconds / max(1.0, (end - start).total_seconds()), 1
            ),
        )

    # ------------------------------------------------------------------
    # Occupancy & speed
    # ------------------------------------------------------------------

    @classmethod
    def occupancy(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        values = [
            m.occupancy_pct for m in db.query(TrafficMetric).filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
                TrafficMetric.occupancy_pct.isnot(None),
            ).all()
        ]

        if len(values) < MIN_SAMPLES_OCCUPANCY:
            return _result(
                None, INSUFFICIENT_DATA, len(values), MIN_SAMPLES_OCCUPANCY,
                "Arithmetic mean of measured occupancy",
                ["traffic_metrics.occupancy_pct"],
                "{} occupancy samples; {} required.".format(len(values), MIN_SAMPLES_OCCUPANCY),
            )

        return _result(
            round(statistics.mean(values), 1), COMPUTED, len(values), MIN_SAMPLES_OCCUPANCY,
            "Arithmetic mean of measured occupancy",
            ["traffic_metrics.occupancy_pct"],
            "Mean of {} measured occupancy samples.".format(len(values)),
            unit="%",
            p95=round(sorted(values)[min(len(values) - 1, int(0.95 * (len(values) - 1)))], 1),
            maximum=round(max(values), 1),
        )

    @classmethod
    def average_speed(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        values = [
            m.avg_speed_kph for m in db.query(TrafficMetric).filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
                TrafficMetric.avg_speed_kph.isnot(None),
            ).all()
        ]

        if len(values) < MIN_SAMPLES_SPEED:
            return _result(
                None, INSUFFICIENT_DATA, len(values), MIN_SAMPLES_SPEED,
                "Harmonic mean of measured approach speeds",
                ["traffic_metrics.avg_speed_kph"],
                "{} speed samples; {} required.".format(len(values), MIN_SAMPLES_SPEED),
            )

        # Space-mean speed is the harmonic mean; the arithmetic mean of spot
        # speeds overstates travel speed along a corridor.
        positive = [v for v in values if v > 0]
        harmonic = (
            round(statistics.harmonic_mean(positive), 1) if positive else 0.0
        )

        return _result(
            harmonic, COMPUTED, len(values), MIN_SAMPLES_SPEED,
            "Harmonic mean (space-mean speed) of measured approach speeds",
            ["traffic_metrics.avg_speed_kph"],
            "Harmonic mean of {} measured speed samples. The arithmetic mean would "
            "overstate corridor travel speed.".format(len(values)),
            unit="km/h",
            arithmetic_mean=round(statistics.mean(values), 1),
        )

    # ------------------------------------------------------------------
    # Control delay
    # ------------------------------------------------------------------

    @classmethod
    def control_delay(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Average control delay per vehicle, from measured wait times.

        Uses the stored `avg_wait_time_sec`, which the state engine derives
        from the measured queue and a declared discharge rate. That derivation
        is an estimate, and it is labelled as one here rather than presented as
        a stopwatch measurement.
        """
        rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
                TrafficMetric.avg_wait_time_sec.isnot(None),
            )
            .all()
        )

        if len(rows) < MIN_SAMPLES_DELAY:
            return _result(
                None, INSUFFICIENT_DATA, len(rows), MIN_SAMPLES_DELAY,
                "Mean of queue-derived wait time (HCM 6th ed. queue discharge)",
                ["traffic_metrics.avg_wait_time_sec"],
                "{} delay samples; {} required before reporting an average.".format(
                    len(rows), MIN_SAMPLES_DELAY
                ),
            )

        values = [r.avg_wait_time_sec for r in rows]
        mean_delay = round(statistics.mean(values), 1)

        # HCM 6th edition signalised-intersection LOS thresholds (control
        # delay per vehicle, seconds).
        los = (
            "A" if mean_delay <= 10 else
            "B" if mean_delay <= 20 else
            "C" if mean_delay <= 35 else
            "D" if mean_delay <= 55 else
            "E" if mean_delay <= 80 else "F"
        )

        return _result(
            mean_delay, COMPUTED, len(rows), MIN_SAMPLES_DELAY,
            "Mean of queue-derived wait time; LOS per HCM 6th ed. Exhibit 19-8",
            ["traffic_metrics.avg_wait_time_sec", "traffic_metrics.queue_length_meters"],
            (
                "Mean of {} queue-derived wait estimates. This is derived from measured "
                "queue length and a declared discharge rate, not from timing individual "
                "vehicles.".format(len(rows))
            ),
            unit="s/veh",
            level_of_service=los,
            estimate_basis="DERIVED_FROM_MEASURED_QUEUE_NOT_DIRECTLY_TIMED",
        )

    # ------------------------------------------------------------------
    # Signal-log measures
    # ------------------------------------------------------------------

    @classmethod
    def _green_intervals(
        cls, logs: List[SignalStateLog]
    ) -> Dict[int, List[Tuple[datetime, datetime]]]:
        """Reconstructs per-phase green intervals from polled state.

        Each interval is bounded by the first and last poll that saw the phase
        green. Because these are polls rather than a continuous feed, an
        interval's true edges lie within one poll period of the reported ones —
        stated on the result rather than smoothed away.
        """
        intervals: Dict[int, List[Tuple[datetime, datetime]]] = defaultdict(list)
        open_start: Dict[int, datetime] = {}
        last_seen: Dict[int, datetime] = {}

        for log in logs:
            greens = set(log.green_phases or [])

            for phase in list(open_start):
                if phase not in greens:
                    intervals[phase].append((open_start[phase], last_seen[phase]))
                    del open_start[phase]
                    del last_seen[phase]

            for phase in greens:
                if phase not in open_start:
                    open_start[phase] = log.timestamp
                last_seen[phase] = log.timestamp

        # Intervals still open at the end of the window are closed at the last
        # observation, not extrapolated forward.
        for phase, started in open_start.items():
            intervals[phase].append((started, last_seen[phase]))

        return intervals

    @classmethod
    def split_failures(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Green intervals that ended with the approach still occupied."""
        logs = (
            db.query(SignalStateLog)
            .filter(
                SignalStateLog.intersection_id == intersection_id,
                SignalStateLog.timestamp >= _naive(start),
                SignalStateLog.timestamp <= _naive(end),
            )
            .order_by(SignalStateLog.timestamp.asc())
            .all()
        )

        if not logs:
            return _result(
                None, NOT_COMPUTABLE, 0, MIN_CYCLES_SPLIT_FAILURE,
                "Occupancy at end of green vs. threshold (ATSPM split failure)",
                ["signal_state_logs", "traffic_metrics.occupancy_pct"],
                (
                    "No signal state was observed in this window, so green intervals "
                    "cannot be reconstructed. Connect an NTCIP 1202 controller; waiting "
                    "will not produce this measure."
                ),
            )

        occupancy_rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
                TrafficMetric.occupancy_pct.isnot(None),
            )
            .order_by(TrafficMetric.timestamp.asc())
            .all()
        )

        if not occupancy_rows:
            return _result(
                None, NOT_COMPUTABLE, len(logs), MIN_CYCLES_SPLIT_FAILURE,
                "Occupancy at end of green vs. threshold (ATSPM split failure)",
                ["signal_state_logs", "traffic_metrics.occupancy_pct"],
                (
                    "Signal state was observed but no occupancy was measured, so whether "
                    "a queue cleared cannot be determined. Connect a detector."
                ),
            )

        intervals = cls._green_intervals(logs)
        total_intervals = sum(len(v) for v in intervals.values())

        if total_intervals < MIN_CYCLES_SPLIT_FAILURE:
            return _result(
                None, INSUFFICIENT_DATA, total_intervals, MIN_CYCLES_SPLIT_FAILURE,
                "Occupancy at end of green vs. threshold (ATSPM split failure)",
                ["signal_state_logs", "traffic_metrics.occupancy_pct"],
                "{} complete green intervals observed; {} required.".format(
                    total_intervals, MIN_CYCLES_SPLIT_FAILURE
                ),
            )

        failures: List[Dict[str, Any]] = []
        evaluated = 0

        for phase, phase_intervals in intervals.items():
            for started, ended in phase_intervals:
                # Occupancy sample closest to the end of green, within one
                # interval length; otherwise this interval is not evaluated.
                tolerance = max(5.0, (ended - started).total_seconds())
                candidates = [
                    row for row in occupancy_rows
                    if abs((row.timestamp - ended).total_seconds()) <= tolerance
                ]
                if not candidates:
                    continue

                evaluated += 1
                closest = min(candidates, key=lambda r: abs((r.timestamp - ended).total_seconds()))
                if closest.occupancy_pct >= SPLIT_FAILURE_OCCUPANCY_PCT:
                    failures.append({
                        "phase": phase,
                        "green_started_at": started.isoformat(),
                        "green_ended_at": ended.isoformat(),
                        "green_duration_sec": round((ended - started).total_seconds(), 1),
                        "occupancy_at_end_pct": round(closest.occupancy_pct, 1),
                        "occupancy_observed_at": closest.timestamp.isoformat(),
                    })

        if evaluated < MIN_CYCLES_SPLIT_FAILURE:
            return _result(
                None, INSUFFICIENT_DATA, evaluated, MIN_CYCLES_SPLIT_FAILURE,
                "Occupancy at end of green vs. threshold (ATSPM split failure)",
                ["signal_state_logs", "traffic_metrics.occupancy_pct"],
                (
                    "{} green intervals had an occupancy sample close enough to their end "
                    "to evaluate; {} required.".format(evaluated, MIN_CYCLES_SPLIT_FAILURE)
                ),
            )

        rate = round(100.0 * len(failures) / evaluated, 1)

        return _result(
            rate, COMPUTED, evaluated, MIN_CYCLES_SPLIT_FAILURE,
            "Share of green intervals ending at or above {}% occupancy".format(
                SPLIT_FAILURE_OCCUPANCY_PCT
            ),
            ["signal_state_logs.green_phases", "traffic_metrics.occupancy_pct"],
            "{} of {} evaluated green intervals ended with the approach still "
            "occupied.".format(len(failures), evaluated),
            unit="% of greens",
            failure_count=len(failures),
            evaluated_intervals=evaluated,
            threshold_pct=SPLIT_FAILURE_OCCUPANCY_PCT,
            failures=failures[:20],
            interval_edge_uncertainty="BOUNDED_BY_POLL_INTERVAL",
        )

    @classmethod
    def arrival_on_green(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Share of observed arrivals that occurred during green for their phase."""
        logs = (
            db.query(SignalStateLog)
            .filter(
                SignalStateLog.intersection_id == intersection_id,
                SignalStateLog.timestamp >= _naive(start),
                SignalStateLog.timestamp <= _naive(end),
            )
            .order_by(SignalStateLog.timestamp.asc())
            .all()
        )

        if not logs:
            return _result(
                None, NOT_COMPUTABLE, 0, MIN_ARRIVALS_AOG,
                "Arrivals during green / total arrivals (ATSPM AoG)",
                ["signal_state_logs", "traffic_observations", "lanes.assigned_phase"],
                (
                    "No signal state was observed, so arrivals cannot be classified as "
                    "on-green or on-red."
                ),
            )

        # Lane -> phase mapping is required to know which phase serves an
        # observation. Without it, an arrival cannot be attributed.
        lane_to_phase: Dict[str, int] = {}
        approaches = db.query(Approach).filter(Approach.intersection_id == intersection_id).all()
        for approach in approaches:
            for lane in approach.lanes:
                if lane.assigned_phase is not None:
                    lane_to_phase[lane.id] = lane.assigned_phase

        if not lane_to_phase:
            return _result(
                None, NOT_COMPUTABLE, 0, MIN_ARRIVALS_AOG,
                "Arrivals during green / total arrivals (ATSPM AoG)",
                ["signal_state_logs", "traffic_observations", "lanes.assigned_phase"],
                (
                    "No lane at this junction has an assigned phase, so an arrival cannot "
                    "be attributed to the phase that serves it. Configure lane-to-phase "
                    "assignments."
                ),
            )

        observations = (
            db.query(TrafficObservation)
            .filter(
                TrafficObservation.intersection_id == intersection_id,
                TrafficObservation.timestamp >= _naive(start),
                TrafficObservation.timestamp <= _naive(end),
                TrafficObservation.lane_id.isnot(None),
                TrafficObservation.vehicle_count > 0,
            )
            .order_by(TrafficObservation.timestamp.asc())
            .all()
        )

        attributable = [o for o in observations if o.lane_id in lane_to_phase]
        total_arrivals = sum(o.vehicle_count for o in attributable)

        if total_arrivals < MIN_ARRIVALS_AOG:
            return _result(
                None, INSUFFICIENT_DATA, total_arrivals, MIN_ARRIVALS_AOG,
                "Arrivals during green / total arrivals (ATSPM AoG)",
                ["signal_state_logs", "traffic_observations", "lanes.assigned_phase"],
                "{} attributable arrivals; {} required.".format(
                    total_arrivals, MIN_ARRIVALS_AOG
                ),
            )

        intervals = cls._green_intervals(logs)
        on_green = 0

        for observation in attributable:
            phase = lane_to_phase[observation.lane_id]
            timestamp = observation.timestamp
            in_green = any(
                started <= timestamp <= ended
                for started, ended in intervals.get(phase, [])
            )
            if in_green:
                on_green += observation.vehicle_count

        aog_pct = round(100.0 * on_green / total_arrivals, 1)

        return _result(
            aog_pct, COMPUTED, total_arrivals, MIN_ARRIVALS_AOG,
            "Arrivals within an observed green interval for the serving phase",
            [
                "signal_state_logs.green_phases",
                "traffic_observations.vehicle_count",
                "lanes.assigned_phase",
            ],
            "{} of {} attributable arrivals fell inside an observed green "
            "interval.".format(on_green, total_arrivals),
            unit="% of arrivals",
            arrivals_on_green=on_green,
            total_arrivals=total_arrivals,
            unattributable_observations=len(observations) - len(attributable),
            interval_edge_uncertainty="BOUNDED_BY_POLL_INTERVAL",
        )

    # ------------------------------------------------------------------
    # Time-of-day profile
    # ------------------------------------------------------------------

    @classmethod
    def time_of_day_profile(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Per-hour volume and occupancy, from stored samples only.

        Hours with no stored samples are returned with null values and a
        sample count of zero rather than omitted or interpolated: a missing
        hour is information.
        """
        rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp <= _naive(end),
            )
            .all()
        )

        buckets: Dict[int, Dict[str, List[float]]] = {
            hour: {"volume": [], "occupancy": [], "speed": []} for hour in range(24)
        }
        for row in rows:
            bucket = buckets[row.timestamp.hour]
            if row.vehicle_count is not None:
                bucket["volume"].append(float(row.vehicle_count))
            if row.occupancy_pct is not None:
                bucket["occupancy"].append(row.occupancy_pct)
            if row.avg_speed_kph is not None:
                bucket["speed"].append(row.avg_speed_kph)

        profile = []
        for hour in range(24):
            bucket = buckets[hour]
            sample_size = len(bucket["volume"])
            profile.append({
                "hour_utc": hour,
                "sample_size": sample_size,
                "mean_vehicle_count": (
                    round(statistics.mean(bucket["volume"]), 1) if bucket["volume"] else None
                ),
                "mean_occupancy_pct": (
                    round(statistics.mean(bucket["occupancy"]), 1) if bucket["occupancy"] else None
                ),
                "mean_speed_kph": (
                    round(statistics.mean(bucket["speed"]), 1) if bucket["speed"] else None
                ),
                "status": COMPUTED if sample_size else "NO_SAMPLES_IN_THIS_HOUR",
            })

        hours_with_data = sum(1 for entry in profile if entry["sample_size"] > 0)

        return {
            "profile": profile,
            "hours_with_data": hours_with_data,
            "hours_without_data": 24 - hours_with_data,
            "total_samples": len(rows),
            "status": COMPUTED if rows else INSUFFICIENT_DATA,
            "method": "Mean of stored samples grouped by UTC hour",
            "explanation": (
                "Hours with no stored samples are reported as such. Nothing is "
                "interpolated across them."
                if rows else
                "No telemetry is stored for this junction in the selected window."
            ),
        }

    # ------------------------------------------------------------------
    # Composite report
    # ------------------------------------------------------------------

    @classmethod
    def intersection_report(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        measures = {
            "throughput": cls.throughput(db, intersection_id, start, end),
            "occupancy": cls.occupancy(db, intersection_id, start, end),
            "average_speed": cls.average_speed(db, intersection_id, start, end),
            "control_delay": cls.control_delay(db, intersection_id, start, end),
            "split_failures": cls.split_failures(db, intersection_id, start, end),
            "arrival_on_green": cls.arrival_on_green(db, intersection_id, start, end),
        }

        computed = [k for k, v in measures.items() if v["status"] == COMPUTED]
        insufficient = [k for k, v in measures.items() if v["status"] == INSUFFICIENT_DATA]
        not_computable = [k for k, v in measures.items() if v["status"] == NOT_COMPUTABLE]

        return {
            "intersection_id": intersection_id,
            "window_start": start.isoformat(),
            "window_end": end.isoformat(),
            "measures": measures,
            "summary": {
                "computed": computed,
                "insufficient_data": insufficient,
                "not_computable": not_computable,
            },
            "time_of_day": cls.time_of_day_profile(db, intersection_id, start, end),
        }
