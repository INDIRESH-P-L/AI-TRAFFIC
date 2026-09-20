"""TRAFFICINTEL AI - Incident Management API Endpoints

Enforces incident state transitions:
DETECTED -> SUSPECTED -> VERIFIED -> ACTIVE -> MITIGATED -> RESOLVED.
Never marks incidents verified without explicit operator or algorithmic verification rule.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, Incident, AuditLog, utc_now
from app.schemas.domain import IncidentCreate, IncidentResponse, IncidentStatusUpdate
from app.incidents.incident_engine import IncidentLifecycleEngine
from app.api.v1.websocket import ws_manager

router = APIRouter(prefix="/incidents", tags=["Incidents"])


@router.get("", response_model=List[IncidentResponse])
def list_incidents(
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(Incident)
    if status_filter:
        q = q.filter(Incident.status == status_filter)
    return q.order_by(Incident.detected_at.desc()).all()


@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
async def create_incident(
    data: IncidentCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    inc = Incident(
        intersection_id=data.intersection_id,
        title=data.title,
        type=data.type,
        severity=data.severity,
        status="DETECTED",
        source=data.source,
        affected_lanes=data.affected_lanes,
        evidence=data.evidence,
        operator_notes=f"[{utc_now().isoformat()} by {current_user.username}]: Initial report."
    )
    db.add(inc)
    db.commit()
    db.refresh(inc)

    # Broadcast event
    await ws_manager.broadcast_event("incident.detected", {
        "incident_id": inc.id,
        "title": inc.title,
        "severity": inc.severity,
        "intersection_id": inc.intersection_id
    })

    return inc


@router.patch("/{id}/status", response_model=IncidentResponse)
async def update_incident_status(
    id: str,
    update: IncidentStatusUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    success, msg = IncidentLifecycleEngine.transition_incident(
        incident=inc,
        new_status=update.status,
        operator_username=current_user.username,
        notes=update.operator_notes
    )

    if not success:
        raise HTTPException(status_code=400, detail=msg)

    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="INCIDENT_STATUS_TRANSITION",
        resource_type="Incident",
        resource_id=inc.id,
        result="EXECUTED",
        details={"new_status": update.status, "notes": update.operator_notes}
    )
    db.add(audit)
    db.commit()
    db.refresh(inc)

    # Broadcast event
    await ws_manager.broadcast_event("incident.updated", {
        "incident_id": inc.id,
        "status": inc.status,
        "operator": current_user.username
    })

    return inc
