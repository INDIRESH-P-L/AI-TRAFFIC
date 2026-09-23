"""TRAFFICINTEL AI - Emergency Vehicle Priority (EVP) Endpoints

Interface with authorized CAD/AVL or roadside optical/GPS preemption detectors.
If no emergency feed is connected, reports EMERGENCY DATA UNAVAILABLE.

Preemption raises a movement's priority. It does not raise its permission: every
preemption call is validated by the Deterministic Safety Engine on the same
terms as an operator command, and a call that would create a conflicting green,
truncate a minimum green, or reach unreadable hardware is recorded as REJECTED.
"""

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import (
    User, EmergencyEvent, Intersection, SignalController, AuditLog, utc_now
)
from app.safety.safety_engine import DeterministicSafetyEngine
from app.schemas.domain import PreemptionRequest, PreemptionResponse, SafetyCheckResult

router = APIRouter(prefix="/emergency", tags=["Emergency Priority"])


@router.get("")
def list_emergency_events(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    events = db.query(EmergencyEvent).order_by(EmergencyEvent.timestamp.desc()).all()
    status_label = "ACTIVE_EVENTS" if events else "EMERGENCY_DATA_UNAVAILABLE"
    return {
        "status": status_label,
        "active_count": len(events),
        "events": events
    }


@router.post("", response_model=PreemptionResponse, status_code=status.HTTP_201_CREATED)
def submit_preemption_call(
    call: PreemptionRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Records a preemption call after deterministic safety validation."""
    inter = db.query(Intersection).filter(Intersection.id == call.intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    controller: Optional[SignalController] = (
        db.query(SignalController)
        .filter(SignalController.intersection_id == call.intersection_id)
        .first()
    )

    if not controller:
        safety_result = SafetyCheckResult(
            is_safe=False,
            violations=[
                f"No signal controller is configured at {inter.name}. Preemption cannot be granted "
                f"for an intersection with no controllable hardware."
            ],
            checks_performed=["CONTROLLER_PRESENCE_VALIDATION"],
            details={"intersection_id": inter.id},
        )
    else:
        # Dwell defaults to the target phase's own minimum green, so the call is
        # validated against the controller's configured envelope rather than an
        # arbitrary number chosen here.
        dwell_sec = call.dwell_sec
        if dwell_sec is None:
            target = next(
                (p for p in controller.phases if p.phase_number == call.requested_phase),
                None,
            )
            dwell_sec = target.min_green if target else 0

        safety_result = DeterministicSafetyEngine.validate_command(
            controller=controller,
            requested_phase_num=call.requested_phase,
            duration_sec=dwell_sec,
            issued_at=utc_now(),
            idempotency_key=f"evp-{call.vehicle_id}-{uuid.uuid4()}",
            existing_command=None,
        )

    event = EmergencyEvent(
        intersection_id=call.intersection_id,
        vehicle_id=call.vehicle_id,
        vehicle_type=call.vehicle_type,
        priority_level=call.priority_level,
        requested_phase=call.requested_phase,
        status="ACTIVE" if safety_result.is_safe else "REJECTED",
        safety_clearance_passed=safety_result.is_safe,
        safety_report=safety_result.model_dump(),
        source=call.source or f"OPERATOR_{current_user.username}",
    )
    db.add(event)
    db.flush()

    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="EMERGENCY_PREEMPTION_REQUESTED",
        resource_type="EmergencyEvent",
        resource_id=event.id,
        result="EXECUTED" if safety_result.is_safe else "REJECTED",
        details={
            "vehicle_id": call.vehicle_id,
            "type": call.vehicle_type,
            "phase": call.requested_phase,
            "safety_violations": safety_result.violations,
        },
    )
    db.add(audit)
    db.commit()
    db.refresh(event)

    return PreemptionResponse(
        event_id=event.id,
        intersection_id=event.intersection_id,
        vehicle_id=event.vehicle_id,
        vehicle_type=event.vehicle_type,
        requested_phase=event.requested_phase,
        status=event.status,
        safety_clearance_passed=event.safety_clearance_passed,
        safety_report=safety_result,
        controller_id=controller.id if controller else None,
        timestamp=event.timestamp,
    )
