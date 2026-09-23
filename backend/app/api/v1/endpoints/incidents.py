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
from app.models.entities import (
    User, Incident, IncidentEvidence, IncidentTimelineEntry, AuditLog, utc_now,
)
from app.schemas.domain import IncidentCreate, IncidentResponse, IncidentStatusUpdate
from app.incidents.incident_engine import IncidentLifecycleEngine
from app.incidents.lifecycle import IncidentLifecycle
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
    # SLA targets are copied on now, from the severity, so a later policy
    # change cannot retroactively rewrite whether this incident met its target.
    IncidentLifecycle.apply_sla_policy(inc)

    db.add(inc)
    db.flush()

    IncidentLifecycle.append_timeline(
        db, inc.id, "STATUS_CHANGE", current_user.username,
        "Incident reported",
        detail="Reported by {} via {}".format(current_user.username, data.source),
        context={
            "to": "DETECTED",
            "severity": data.severity,
            "sla_acknowledge_sec": inc.sla_acknowledge_sec,
            "sla_resolve_sec": inc.sla_resolve_sec,
        },
    )

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

    success, msg = IncidentLifecycle.transition(
        db=db,
        incident=inc,
        new_status=update.status,
        actor=current_user.username,
        notes=update.operator_notes,
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


# ===========================================================================
# Triage, assignment, SLA
# ===========================================================================

@router.post("/{id}/acknowledge")
def acknowledge_incident(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Starts the response clock. Acknowledging twice is a no-op, not an error."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = IncidentLifecycle.acknowledge(db, inc, current_user.username)

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="ACKNOWLEDGE_INCIDENT",
        resource_type="Incident",
        resource_id=inc.id,
        result="EXECUTED" if result["changed"] else "NO_CHANGE",
        details={"title": inc.title},
    ))
    db.commit()
    return result


@router.post("/{id}/assign")
def assign_incident(
    id: str,
    assignee: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    result = IncidentLifecycle.assign(db, inc, assignee, current_user.username)

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="ASSIGN_INCIDENT",
        resource_type="Incident",
        resource_id=inc.id,
        result="EXECUTED",
        details={"assigned_to": assignee},
    ))
    db.commit()
    return result


@router.get("/{id}/sla")
def incident_sla(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """SLA standing computed from real timestamps."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return {"incident_id": inc.id, **IncidentLifecycle.sla_status(inc)}


@router.post("/sla/check")
def check_sla_breaches(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Marks newly breached SLAs and records each on its incident timeline."""
    breached = IncidentLifecycle.check_sla_breaches(db)
    return {
        "checked_at": utc_now().isoformat(),
        "newly_breached": breached,
        "count": len(breached),
        "empty_reason": None if breached else "NO_NEW_SLA_BREACHES",
    }


# ===========================================================================
# Timeline
# ===========================================================================

@router.get("/{id}/timeline")
def incident_timeline(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Append-only history of this incident."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    entries = (
        db.query(IncidentTimelineEntry)
        .filter(IncidentTimelineEntry.incident_id == id)
        .order_by(IncidentTimelineEntry.timestamp.asc())
        .all()
    )

    return {
        "incident_id": id,
        "count": len(entries),
        "empty_reason": None if entries else "NO_TIMELINE_ENTRIES",
        "append_only": True,
        "note": (
            "This timeline has no update or delete path. A correction is a new entry "
            "referencing the one it corrects, so a review can see both what was "
            "believed at the time and what was later established."
        ),
        "entries": [
            {
                "id": entry.id,
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "entry_type": entry.entry_type,
                "actor": entry.actor,
                "summary": entry.summary,
                "detail": entry.detail,
                "context": entry.context,
                "corrects_entry_id": entry.corrects_entry_id,
            }
            for entry in entries
        ],
    }


@router.post("/{id}/timeline/note")
def add_timeline_note(
    id: str,
    summary: str,
    detail: Optional[str] = None,
    corrects_entry_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Appends a note, optionally correcting an earlier entry."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    if corrects_entry_id:
        target = db.query(IncidentTimelineEntry).filter(
            IncidentTimelineEntry.id == corrects_entry_id,
            IncidentTimelineEntry.incident_id == id,
        ).first()
        if not target:
            raise HTTPException(
                status_code=404,
                detail="The entry being corrected does not exist on this incident.",
            )

    entry = IncidentLifecycle.append_timeline(
        db, id,
        "CORRECTION" if corrects_entry_id else "NOTE",
        current_user.username,
        summary, detail,
        corrects_entry_id=corrects_entry_id,
    )
    db.commit()

    return {
        "entry_id": entry.id,
        "entry_type": entry.entry_type,
        "timestamp": entry.timestamp.isoformat(),
        "corrects_entry_id": corrects_entry_id,
    }


# ===========================================================================
# Evidence
# ===========================================================================

@router.get("/evidence/sources")
def evidence_sources(current_user: User = Depends(get_current_user)):
    """Which kinds of evidence can be attached, and what each references."""
    from app.incidents.lifecycle import EVIDENCE_SOURCES
    return {
        "sources": [
            {"evidence_type": key, "source_table": table}
            for key, (table, _model) in sorted(EVIDENCE_SOURCES.items())
        ],
        "note": (
            "Evidence must reference a record the platform stored. There is no "
            "free-form upload path: an item nobody can trace back to a recorded "
            "observation is an assertion, not evidence."
        ),
    }


@router.post("/{id}/evidence")
def attach_evidence(
    id: str,
    evidence_type: str,
    source_id: str,
    note: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Attaches a reference to something the platform actually recorded."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    try:
        result = IncidentLifecycle.attach_evidence(
            db, inc, evidence_type, source_id, current_user.username, note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="ATTACH_INCIDENT_EVIDENCE",
        resource_type="Incident",
        resource_id=inc.id,
        result="EXECUTED",
        details={"evidence_type": evidence_type, "source_id": source_id},
    ))
    db.commit()
    return result


@router.get("/{id}/evidence")
def list_evidence(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    items = (
        db.query(IncidentEvidence)
        .filter(IncidentEvidence.incident_id == id)
        .order_by(IncidentEvidence.attached_at.asc())
        .all()
    )
    return {
        "incident_id": id,
        "count": len(items),
        "empty_reason": None if items else "NO_EVIDENCE_ATTACHED",
        "evidence": [
            {
                "id": item.id,
                "evidence_type": item.evidence_type,
                "source_table": item.source_table,
                "source_id": item.source_id,
                "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                "attached_by": item.attached_by,
                "attached_at": item.attached_at.isoformat() if item.attached_at else None,
                "note": item.note,
                "snapshot": item.snapshot,
            }
            for item in items
        ],
    }


# ===========================================================================
# Post-incident report
# ===========================================================================

@router.get("/{id}/report")
def post_incident_report(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Assembles a post-incident report from recorded facts only."""
    inc = db.query(Incident).filter(Incident.id == id).first()
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentLifecycle.post_incident_report(db, inc)
