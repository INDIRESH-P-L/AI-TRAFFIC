"""TRAFFICINTEL AI - Emergency Vehicle Priority (EVP) Endpoints

Two triggers, one path to the controller:

* `POST /emergency`      - an operator requests preemption for a named vehicle.
* `POST /emergency/avl`  - a vehicle's position report (NMEA 0183 RMC, or decoded
                           fields) selects the junction and phase itself.

Both go through PreemptionService and SignalCommandDispatcher: the same
Deterministic Safety Engine validation, the same command record, the same audit
trail. Preemption raises a movement's priority, never its permission.

If no emergency feed is connected, the list reports EMERGENCY DATA UNAVAILABLE.

The AVL endpoint requires `signal:command`. API keys can never hold that scope
(see governance/api_keys.py), so a CAD/AVL integration authenticates as a
dedicated OPERATOR service account - deliberately, because an integration that
can trigger preemption is an integration that can change signals.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles, require_scope
from app.emergency.nmea import NmeaError, parse_rmc
from app.emergency.preemption import AvlPosition, PreemptionService
from app.governance import scopes as scope_vocab
from app.models.entities import AuditLog, EmergencyEvent, Intersection, User
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
    """Validates a preemption call and, if it passes, sends it to the controller."""
    inter = db.query(Intersection).filter(Intersection.id == call.intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    outcome = PreemptionService.preempt(
        db, inter, call.requested_phase, call.vehicle_id, call.vehicle_type,
        actor_id=current_user.id, actor_name=current_user.username,
        trigger="MANUAL", source=call.source or "OPERATOR_{}".format(current_user.username),
        priority_level=call.priority_level, dwell_sec=call.dwell_sec,
    )
    event = outcome["event"]
    db.refresh(event)
    return PreemptionResponse(
        event_id=event.id,
        intersection_id=event.intersection_id,
        vehicle_id=event.vehicle_id,
        vehicle_type=event.vehicle_type,
        requested_phase=event.requested_phase,
        status=event.status,
        safety_clearance_passed=event.safety_clearance_passed,
        safety_report=SafetyCheckResult(**outcome["safety"]),
        controller_id=outcome["controller"].id if outcome["controller"] else None,
        timestamp=event.timestamp,
        trigger=event.trigger,
        command_id=event.command_id,
        command_status=event.command_status,
    )


class AvlReport(BaseModel):
    """One position report from an emergency vehicle's AVL unit.

    Supply either `nmea` (a raw RMC sentence, checksum and all) or the decoded
    fields. The raw sentence is preferred: its checksum and validity flag are
    verified here rather than trusted from whoever decoded it.
    """

    vehicle_id: str = Field(min_length=1, max_length=64)
    vehicle_type: str
    source: str = Field(default="AVL", max_length=64)
    nmea: Optional[str] = None
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)
    speed_kph: Optional[float] = Field(default=None, ge=0, le=300)
    heading_deg: Optional[float] = Field(default=None, ge=0, lt=360)
    reported_at: Optional[datetime] = None


@router.post("/avl")
def receive_avl_report(
    report: AvlReport,
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.COMMAND_SIGNAL)),
):
    """Decides from a vehicle's own position whether, where and which phase to preempt."""
    actor_id = getattr(getattr(principal, "user", None), "id", None)

    if report.nmea:
        try:
            fix = parse_rmc(report.nmea)
        except NmeaError as exc:
            db.add(AuditLog(
                actor_id=actor_id, actor_username=principal.identity,
                action="AVL_REPORT_NOT_ACTED_ON", resource_type="AvlReport",
                resource_id=report.vehicle_id, result=exc.code,
                details={"detail": str(exc), "sentence": report.nmea},
            ))
            db.commit()
            raise HTTPException(status_code=422, detail={"decision": exc.code, "detail": str(exc)})
        position = AvlPosition(
            vehicle_id=report.vehicle_id, vehicle_type=report.vehicle_type.upper(),
            latitude=fix.latitude, longitude=fix.longitude, speed_kph=fix.speed_kph,
            heading_deg=fix.heading_deg, reported_at=fix.reported_at, source=report.source,
        )
    else:
        missing = [name for name in ("latitude", "longitude", "speed_kph", "reported_at")
                   if getattr(report, name) is None]
        if missing:
            raise HTTPException(status_code=422, detail={
                "decision": "INCOMPLETE_POSITION",
                "detail": "Supply an NMEA sentence or all of: {}.".format(", ".join(missing)),
            })
        position = AvlPosition(
            vehicle_id=report.vehicle_id, vehicle_type=report.vehicle_type.upper(),
            latitude=report.latitude, longitude=report.longitude, speed_kph=report.speed_kph,
            heading_deg=report.heading_deg, reported_at=report.reported_at, source=report.source,
        )

    return PreemptionService.handle_avl(db, position, actor_id, principal.identity)
