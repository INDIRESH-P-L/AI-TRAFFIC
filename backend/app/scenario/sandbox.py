"""TRAFFICINTEL AI - Scenario Sandbox

Computes the effect of a hypothetical timing change from operator-entered
volumes or real stored telemetry, and stamps the result SCENARIO.

The isolation rules, which are the whole point of this module:

1. **Scenario results live in their own table** (`scenario_runs`). They are not
   `TrafficMetric` rows with a flag, because a flag is one forgotten `WHERE`
   clause away from a hypothetical number appearing on the operations map as an
   observation.

2. **Nothing here writes to any observed-data table.** The functions below take
   a session only to read inputs and to write into `scenario_runs`.

3. **Every output field is prefixed and labelled.** A scenario result cannot be
   deserialised into a `TrafficMetric`: the field names differ deliberately.

4. **Baselines are real or absent.** A scenario may be compared against measured
   telemetry when enough of it exists; otherwise the comparison is refused
   rather than computed against an assumed baseline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.entities import (
    Intersection, ScenarioRun, SignalController, SignalPhase, TrafficMetric, utc_now,
)
from app.optimization.webster import (
    DEFAULT_SATURATION_FLOW_VPHPL, MovementDemand, WebsterOptimizer,
)

logger = logging.getLogger("trafficintel.scenario")

SCENARIO_STAMP = "SCENARIO / HYPOTHETICAL"
MIN_BASELINE_SAMPLES = 10


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


class ScenarioSandbox:
    """Runs hypothetical timing scenarios. Never touches observed-data tables."""

    @classmethod
    def run(
        cls,
        db: Session,
        intersection_id: Optional[str],
        movements: List[Dict[str, Any]],
        label: str,
        operator: str,
        lost_time_per_phase_sec: float = 4.0,
        compare_to_measured: bool = False,
        baseline_window_minutes: int = 60,
    ) -> Dict[str, Any]:
        """Computes a hypothetical timing plan and stores it as a scenario."""
        demands: List[MovementDemand] = []
        for movement in movements:
            demands.append(MovementDemand(
                phase_number=int(movement["phase_number"]),
                name=movement.get("name") or "Phase {}".format(movement["phase_number"]),
                volume_vph=float(movement["volume_vph"]),
                lanes=int(movement.get("lanes") or 1),
                # Present-but-None defeats `.get(key, default)`, so the
                # default is applied by coalescing.
                saturation_flow_vphpl=float(
                    movement.get("saturation_flow_vphpl") or DEFAULT_SATURATION_FLOW_VPHPL
                ),
                min_green_sec=int(movement.get("min_green_sec") or 7),
                max_green_sec=int(movement.get("max_green_sec") or 65),
                # Volumes supplied to the sandbox are operator input by
                # definition. Nothing here fabricates a volume.
                source="OPERATOR_ENTERED",
                sample_size=0,
            ))

        result = WebsterOptimizer.optimize(
            demands, lost_time_per_phase_sec=lost_time_per_phase_sec
        )

        baseline = None
        if compare_to_measured and intersection_id:
            baseline = cls._measured_baseline(db, intersection_id, baseline_window_minutes)

        comparison = None
        if baseline and baseline["status"] == "AVAILABLE" and result.expected_delay:
            scenario_delay = result.expected_delay["volume_weighted_delay_sec_per_veh"]
            measured_delay = baseline["measured_delay_sec_per_veh"]
            if scenario_delay is not None and measured_delay is not None:
                change = scenario_delay - measured_delay
                comparison = {
                    "measured_delay_sec_per_veh": measured_delay,
                    "scenario_delay_sec_per_veh": scenario_delay,
                    "change_sec_per_veh": round(change, 1),
                    "direction": "IMPROVEMENT" if change < 0 else "DEGRADATION",
                    "caveat": (
                        "The measured figure is derived from real stored telemetry; the "
                        "scenario figure is a Webster estimate from volumes you entered. "
                        "They are computed by different methods, so this comparison "
                        "indicates direction, not a guaranteed outcome."
                    ),
                }

        run = ScenarioRun(
            intersection_id=intersection_id,
            label=label,
            operator=operator,
            input_movements=[m.__dict__ for m in demands],
            scenario_cycle_length_sec=result.cycle_length_sec,
            scenario_splits=result.splits,
            scenario_expected_delay=result.expected_delay,
            calculation_trace=result.trace,
            status=result.status,
            refusal_reason=result.reason,
            measured_baseline=baseline,
            comparison=comparison,
            created_at=utc_now(),
        )
        db.add(run)
        db.commit()
        db.refresh(run)

        return cls.serialize(run)

    @classmethod
    def _measured_baseline(
        cls, db: Session, intersection_id: str, window_minutes: int
    ) -> Dict[str, Any]:
        """Real measured delay for comparison, or a refusal."""
        since = _naive(datetime.now(timezone.utc) - timedelta(minutes=window_minutes))
        rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= since,
                TrafficMetric.avg_wait_time_sec.isnot(None),
            )
            .all()
        )

        if len(rows) < MIN_BASELINE_SAMPLES:
            return {
                "status": "INSUFFICIENT_DATA",
                "sample_size": len(rows),
                "minimum_samples": MIN_BASELINE_SAMPLES,
                "window_minutes": window_minutes,
                "measured_delay_sec_per_veh": None,
                "explanation": (
                    "{} measured delay samples in the last {} minutes; {} are required "
                    "before a scenario can be compared against observed conditions. No "
                    "assumed baseline is substituted.".format(
                        len(rows), window_minutes, MIN_BASELINE_SAMPLES
                    )
                ),
            }

        values = [row.avg_wait_time_sec for row in rows]
        return {
            "status": "AVAILABLE",
            "sample_size": len(values),
            "minimum_samples": MIN_BASELINE_SAMPLES,
            "window_minutes": window_minutes,
            "measured_delay_sec_per_veh": round(sum(values) / len(values), 1),
            "explanation": "Mean of {} measured delay samples.".format(len(values)),
        }

    @classmethod
    def movements_from_controller(
        cls, db: Session, controller_id: str
    ) -> List[Dict[str, Any]]:
        """Phase envelopes from a real controller, as a starting point.

        Returns phase configuration only — minimum green, maximum green, name.
        No volume is supplied, because the platform does not invent demand: the
        operator enters it or it comes from measured telemetry.
        """
        controller = db.query(SignalController).filter(
            SignalController.id == controller_id
        ).first()
        if not controller:
            return []

        return [
            {
                "phase_number": phase.phase_number,
                "name": phase.name,
                "min_green_sec": phase.min_green,
                "max_green_sec": phase.max_green,
                "volume_vph": None,
                "volume_status": "NOT_SUPPLIED_ENTER_A_VOLUME_OR_USE_MEASURED_TELEMETRY",
            }
            for phase in sorted(controller.phases, key=lambda p: p.phase_number)
        ]

    @classmethod
    def serialize(cls, run: ScenarioRun) -> Dict[str, Any]:
        """Scenario wire format. Field names differ from observed metrics on purpose."""
        return {
            # Loud, first, and in every response.
            "result_type": SCENARIO_STAMP,
            "is_hypothetical": True,
            "not_observed_data": True,
            "scenario_id": run.id,
            "label": run.label,
            "operator": run.operator,
            "intersection_id": run.intersection_id,
            "status": run.status,
            "refusal_reason": run.refusal_reason,
            "scenario_cycle_length_sec": run.scenario_cycle_length_sec,
            "scenario_splits": run.scenario_splits,
            "scenario_expected_delay": run.scenario_expected_delay,
            "calculation_trace": run.calculation_trace,
            "input_movements": run.input_movements,
            "measured_baseline": run.measured_baseline,
            "comparison": run.comparison,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "disclaimer": (
                "These figures are computed from hypothetical inputs. They are not "
                "measurements, they are stored separately from observed telemetry, and "
                "they are never used by the operations map, analytics or alerting."
            ),
        }
