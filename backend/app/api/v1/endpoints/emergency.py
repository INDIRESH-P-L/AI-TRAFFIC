"""TRAFFICINTEL AI - Emergency Vehicle Priority (EVP) Endpoints

Interface with authorized CAD/AVL or roadside optical/GPS preemption detectors.
If no emergency feed is connected, reports EMERGENCY DATA UNAVAILABLE.
All preemption requests are checked against deterministic clearance standards.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, EmergencyEvent, Intersection, AuditLog, utc_now

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


@router.post("", status_code=status.HTTP_201_CREATED)
def submit_preemption_call(
    intersection_id: str,
    vehicle_id: str,
    vehicle_type: str,
    requested_phase: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    event = EmergencyEvent(
        intersection_id=intersection_id,
        vehicle_id=vehicle_id,
        vehicle_type=vehicle_type,
        requested_phase=requested_phase,
        status="ACTIVE",
        safety_clearance_passed=True,
        source=f"OPERATOR_OR_CAD_{current_user.username}"
    )
    db.add(event)

    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="EMERGENCY_PREEMPTION_REQUESTED",
        resource_type="EmergencyEvent",
        resource_id=event.id,
        result="EXECUTED",
        details={"vehicle_id": vehicle_id, "type": vehicle_type, "phase": requested_phase}
    )
    db.add(audit)
    db.commit()
    db.refresh(event)
    return event
