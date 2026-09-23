"""TRAFFICINTEL AI - Explainable Signal Optimiser & Scenario Sandbox

Two endpoints that look similar and are deliberately kept apart:

  `/optimizer/...`  produces a proposal intended to be ACTED ON. It runs on
                    real measured demand or operator-entered volumes, and its
                    result is validated by the Deterministic Safety Engine
                    before it is offered to an operator.

  `/scenario/...`   produces a HYPOTHETICAL. It is stamped SCENARIO, stored in
                    its own table, and is never routed to a controller.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.trust import TrustScore
from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.events import topics
from app.events.bus import event_bus
from app.models.entities import (
    AuditLog, Intersection, Lane, Approach, OptimizerRecommendation, ScenarioRun,
    SignalController, TrafficMetric, TrafficObservation, User, utc_now,
)
from app.optimization.webster import (
    DEFAULT_SATURATION_FLOW_VPHPL, MIN_SAMPLES_PER_MOVEMENT, MovementDemand,
    WebsterOptimizer,
)
from app.safety.safety_engine import DeterministicSafetyEngine
from app.scenario.sandbox import ScenarioSandbox
from app.schemas.domain import ScenarioRequest, OptimizerRequest

router = APIRouter(tags=["Optimiser & Scenarios"])


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _measured_demand(
    db: Session, intersection_id: str, controller: SignalController, window_minutes: int
) -> Dict[str, Any]:
    """Per-phase measured demand from stored observations.

    Requires lane-to-phase assignments: without them an observation cannot be
    attributed to the phase that serves it, and the optimiser is told so rather
    than spreading volume evenly as a guess.
    """
    lane_to_phase: Dict[str, int] = {}
    for approach in db.query(Approach).filter(
        Approach.intersection_id == intersection_id
    ).all():
        for lane in approach.lanes:
            if lane.assigned_phase is not None:
                lane_to_phase[lane.id] = lane.assigned_phase

    if not lane_to_phase:
        return {
            "status": "NOT_COMPUTABLE",
            "reason": "NO_LANE_TO_PHASE_ASSIGNMENTS",
            "detail": (
                "No lane at this junction has an assigned phase, so measured volumes "
                "cannot be attributed to the phases that serve them. Configure lane "
                "assignments, or supply volumes directly."
            ),
            "movements": [],
            "missing_inputs": ["lanes.assigned_phase"],
        }

    since = _naive(datetime.now(timezone.utc) - timedelta(minutes=window_minutes))
    observations = (
        db.query(TrafficObservation)
        .filter(
            TrafficObservation.intersection_id == intersection_id,
            TrafficObservation.timestamp >= since,
            TrafficObservation.lane_id.isnot(None),
        )
        .all()
    )

    by_phase: Dict[int, Dict[str, Any]] = {}
    for observation in observations:
        phase = lane_to_phase.get(observation.lane_id)
        if phase is None:
            continue
        bucket = by_phase.setdefault(phase, {"count": 0, "samples": 0, "lanes": set()})
        bucket["count"] += observation.vehicle_count or 0
        bucket["samples"] += 1
        bucket["lanes"].add(observation.lane_id)

    if not by_phase:
        return {
            "status": "INSUFFICIENT_DATA",
            "reason": "NO_MEASURED_VOLUMES_IN_WINDOW",
            "detail": (
                "No lane-attributed observations were recorded in the last {} minutes."
                .format(window_minutes)
            ),
            "movements": [],
            "missing_inputs": ["traffic_observations.vehicle_count"],
        }

    phases = {p.phase_number: p for p in controller.phases} if controller else {}
    window_hours = window_minutes / 60.0
    movements: List[Dict[str, Any]] = []
    missing: List[str] = []

    for phase_number, bucket in sorted(by_phase.items()):
        phase = phases.get(phase_number)
        if phase is None:
            missing.append("phase {} configuration".format(phase_number))
            continue
        movements.append({
            "phase_number": phase_number,
            "name": phase.name,
            "volume_vph": round(bucket["count"] / window_hours, 1),
            "lanes": max(1, len(bucket["lanes"])),
            "min_green_sec": phase.min_green,
            "max_green_sec": phase.max_green,
            "source": "MEASURED_DETECTOR",
            "sample_size": bucket["samples"],
        })

    # Phases with no measured demand are named, not assumed to be zero: a
    # phase with a broken detector is not a phase with no traffic.
    for phase_number, phase in phases.items():
        if phase_number not in by_phase:
            missing.append(
                "measured volume for phase {} ({})".format(phase_number, phase.name)
            )

    return {
        "status": "COMPUTED",
        "movements": movements,
        "missing_inputs": missing,
        "window_minutes": window_minutes,
    }


# ===========================================================================
# Optimiser
# ===========================================================================

@router.post("/optimizer/recommend")
def recommend_timing(
    request: OptimizerRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"])),
):
    """Produces a timing proposal and routes it through the Safety Engine."""
    inter = db.query(Intersection).filter(Intersection.id == request.intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    controller = (
        db.query(SignalController)
        .filter(SignalController.intersection_id == request.intersection_id)
        .first()
    )

    # Trust is computed up front because it is reported on every result,
    # but it is only *enforced* after the structural checks below: no
    # amount of data quality fixes a missing lane-to-phase mapping, so
    # telling an operator about staleness first would send them to fix the
    # wrong thing.
    trust = TrustScore.for_intersection(db, request.intersection_id)

    # --- demand ---------------------------------------------------------
    if request.movements:
        demand_source = "OPERATOR_ENTERED"
        movement_dicts = [m.model_dump() for m in request.movements]
        missing_inputs: List[str] = []
    else:
        if not controller:
            raise HTTPException(
                status_code=400,
                detail=(
                    "No controller is configured at this junction and no volumes were "
                    "supplied, so there is nothing to optimise against."
                ),
            )
        demand = _measured_demand(
            db, request.intersection_id, controller, request.window_minutes
        )
        if demand["status"] != "COMPUTED":
            record = OptimizerRecommendation(
                intersection_id=request.intersection_id,
                controller_id=controller.id if controller else None,
                method_version=WebsterOptimizer.optimize([]).method_version,
                demand_source="MEASURED_DETECTOR",
                inputs=[],
                missing_inputs=demand["missing_inputs"],
                status="REFUSED",
                refusal_reason=demand["reason"],
                created_by=current_user.username,
            )
            db.add(record)
            db.commit()
            return {
                "recommendation_id": record.id,
                "status": "REFUSED",
                "reason": demand["reason"],
                "detail": demand["detail"],
                "missing_inputs": demand["missing_inputs"],
                "demand_source": "MEASURED_DETECTOR",
            }
        # Structural checks passed; now the data-quality gate applies. It only
        # ever applies to MEASURED demand: a volume an operator typed in is
        # their own assertion, and the platform has no business second-guessing
        # it on the strength of detector staleness.
        if not trust["ai_gate"]["allowed"]:
            record = OptimizerRecommendation(
                intersection_id=request.intersection_id,
                controller_id=controller.id if controller else None,
                method_version=WebsterOptimizer.optimize([]).method_version,
                demand_source="MEASURED_DETECTOR",
                inputs=[],
                missing_inputs=["data_quality_trust_score"],
                status="REFUSED",
                refusal_reason="TRUST_SCORE_BELOW_AI_GATE",
                created_by=current_user.username,
            )
            db.add(record)
            db.commit()
            return {
                "recommendation_id": record.id,
                "status": "REFUSED",
                "reason": "TRUST_SCORE_BELOW_AI_GATE",
                "detail": trust["ai_gate"]["reason"],
                "trust": {
                    "score": trust["score"],
                    "band": trust["band"],
                    "threshold": trust["ai_gate"]["threshold"],
                    "weakest_component": trust.get("weakest_component"),
                },
                "remedy": (
                    "Enter volumes directly to override the gate - an operator-supplied "
                    "volume is their own assertion and is not blocked - or restore the "
                    "data sources this junction is missing."
                ),
                "demand_source": "MEASURED_DETECTOR",
            }

        demand_source = "MEASURED_DETECTOR"
        movement_dicts = demand["movements"]
        missing_inputs = demand["missing_inputs"]

    demands = [
        MovementDemand(
            phase_number=int(m["phase_number"]),
            name=m.get("name") or "Phase {}".format(m["phase_number"]),
            volume_vph=float(m["volume_vph"]),
            lanes=int(m.get("lanes") or 1),
            # `.get(key, default)` is not enough: the field is present with a
            # value of None when the operator omitted it, so the default has
            # to be applied by coalescing rather than by key absence.
            saturation_flow_vphpl=float(
                m.get("saturation_flow_vphpl") or DEFAULT_SATURATION_FLOW_VPHPL
            ),
            min_green_sec=int(m.get("min_green_sec") or 7),
            max_green_sec=int(m.get("max_green_sec") or 65),
            source=m.get("source") or demand_source,
            sample_size=int(m.get("sample_size") or 0),
        )
        for m in movement_dicts
    ]

    result = WebsterOptimizer.optimize(demands)

    # --- safety verdict --------------------------------------------------
    safety_verdict = None
    safety_passed = False

    if result.status == "COMPUTED" and controller and result.splits:
        # The proposal is validated exactly like an operator command: the
        # longest proposed green is the binding case for the phase envelope.
        critical = max(result.splits, key=lambda s: s["effective_green_sec"])
        verdict = DeterministicSafetyEngine.validate_command(
            controller=controller,
            requested_phase_num=int(critical["phase"]),
            duration_sec=int(round(critical["effective_green_sec"])),
            issued_at=utc_now(),
            idempotency_key="optimizer-preview-{}".format(utc_now().timestamp()),
            existing_command=None,
        )
        safety_verdict = verdict.model_dump()
        safety_passed = verdict.is_safe

    record = OptimizerRecommendation(
        intersection_id=request.intersection_id,
        controller_id=controller.id if controller else None,
        method_version=result.method_version,
        demand_source=demand_source,
        inputs=result.inputs,
        missing_inputs=missing_inputs,
        status=result.status,
        refusal_reason=result.reason,
        proposed_cycle_length_sec=result.cycle_length_sec,
        proposed_splits=result.splits,
        expected_delay=result.expected_delay,
        calculation_trace=result.trace,
        safety_verdict=safety_verdict,
        safety_passed=safety_passed,
        created_by=current_user.username,
    )
    db.add(record)
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="OPTIMIZER_RECOMMENDATION",
        resource_type="Intersection",
        resource_id=request.intersection_id,
        result=result.status,
        details={
            "demand_source": demand_source,
            "cycle_length_sec": result.cycle_length_sec,
            "safety_passed": safety_passed,
        },
    ))
    db.commit()
    db.refresh(record)

    event_bus.publish(topics.OPTIMIZER_RECOMMENDATION, {
        "recommendation_id": record.id,
        "intersection_id": request.intersection_id,
        "status": result.status,
        "safety_passed": safety_passed,
    })

    return {
        "recommendation_id": record.id,
        "intersection_id": request.intersection_id,
        "intersection_name": inter.name,
        "demand_source": demand_source,
        "missing_inputs": missing_inputs,
        "safety_verdict": safety_verdict,
        "safety_passed": safety_passed,
        "actionable": safety_passed,
        "trust": {
            "score": trust["score"],
            "band": trust["band"],
            "ai_gate_allowed": trust["ai_gate"]["allowed"],
            "note": (
                "Demand was entered by the operator, so the trust gate does not apply."
                if demand_source == "OPERATOR_ENTERED" else
                "Demand came from detectors at this junction; its trust band is shown "
                "so the recommendation can be weighed against the quality of its inputs."
            ),
        },
        "actionable_note": (
            "Proposals are applied through the guided command workflow, which "
            "re-validates against live controller state. A proposal is never sent "
            "to hardware directly."
        ),
        **result.as_dict(),
    }


@router.get("/optimizer/recommendations/{intersection_id}")
def list_recommendations(
    intersection_id: str,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(OptimizerRecommendation)
        .filter(OptimizerRecommendation.intersection_id == intersection_id)
        .order_by(OptimizerRecommendation.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "intersection_id": intersection_id,
        "count": len(rows),
        "empty_reason": None if rows else "NO_RECOMMENDATION_HAS_BEEN_PRODUCED",
        "recommendations": [
            {
                "id": row.id,
                "status": row.status,
                "refusal_reason": row.refusal_reason,
                "demand_source": row.demand_source,
                "proposed_cycle_length_sec": row.proposed_cycle_length_sec,
                "proposed_splits": row.proposed_splits,
                "expected_delay": row.expected_delay,
                "missing_inputs": row.missing_inputs,
                "safety_passed": row.safety_passed,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "created_by": row.created_by,
            }
            for row in rows
        ],
    }


# ===========================================================================
# Scenario sandbox
# ===========================================================================

@router.post("/scenario/run", status_code=status.HTTP_201_CREATED)
def run_scenario(
    request: ScenarioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"])),
):
    """Runs a hypothetical timing scenario. Output is stamped SCENARIO."""
    if not request.movements:
        raise HTTPException(
            status_code=400,
            detail=(
                "A scenario needs movement volumes. The platform does not generate "
                "demand: enter volumes, or use the optimiser against measured telemetry."
            ),
        )

    return ScenarioSandbox.run(
        db=db,
        intersection_id=request.intersection_id,
        movements=[m.model_dump() for m in request.movements],
        label=request.label,
        operator=current_user.username,
        lost_time_per_phase_sec=request.lost_time_per_phase_sec,
        compare_to_measured=request.compare_to_measured,
        baseline_window_minutes=request.baseline_window_minutes,
    )


@router.get("/scenario/template/{controller_id}")
def scenario_template(
    controller_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Phase envelopes from a real controller as a starting point.

    Volumes are deliberately null: the operator supplies them.
    """
    movements = ScenarioSandbox.movements_from_controller(db, controller_id)
    if not movements:
        raise HTTPException(status_code=404, detail="Controller not found or has no phases")
    return {
        "controller_id": controller_id,
        "movements": movements,
        "note": (
            "Phase minimum and maximum green come from the real controller "
            "configuration. Volumes are not supplied and must be entered."
        ),
    }


@router.get("/scenario/runs")
def list_scenarios(
    intersection_id: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(ScenarioRun)
    if intersection_id:
        query = query.filter(ScenarioRun.intersection_id == intersection_id)
    rows = query.order_by(ScenarioRun.created_at.desc()).limit(limit).all()

    return {
        "result_type": "SCENARIO / HYPOTHETICAL",
        "count": len(rows),
        "empty_reason": None if rows else "NO_SCENARIO_HAS_BEEN_RUN",
        "scenarios": [ScenarioSandbox.serialize(row) for row in rows],
    }
