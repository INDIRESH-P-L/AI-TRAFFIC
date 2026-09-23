"""TRAFFICINTEL AI - Phase 3 Operator Insights

Four surfaces that answer questions an operator actually asks:

  * **Trust** — how much of what I am looking at was recently measured?
  * **Verification** — did that change actually do anything?
  * **Stringline** — is this corridor coordinated?
  * **Handover** — what does the next shift need to know, including where we
    were blind?
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.analytics.stringline import Stringline
from app.analytics.trust import TrustScore
from app.analytics.verification import PostChangeVerification
from app.core.database import get_db
from app.core.security import Principal, get_current_user, require_scope
from app.governance import scopes as scope_vocab
from app.models.entities import ShiftHandover, User
from app.reporting.handover import ShiftHandoverService
from app.schemas.domain import HandoverCreate, HandoverUpdate

router = APIRouter(tags=["Operator Insights"])


# ===========================================================================
# Trust score
# ===========================================================================

@router.get("/trust/network")
def network_trust(
    window_minutes: int = Query(default=60, ge=5, le=1440),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Data-quality trust across every configured junction."""
    return TrustScore.for_network(db, window_minutes=window_minutes)


@router.get("/trust/{intersection_id}")
def junction_trust(
    intersection_id: str,
    window_minutes: int = Query(default=60, ge=5, le=1440),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One junction's trust score, with every component visible."""
    result = TrustScore.for_intersection(db, intersection_id, window_minutes)
    if result.get("band") == "UNRATED" and not result.get("components"):
        raise HTTPException(status_code=404, detail="Intersection not found")
    return result


# ===========================================================================
# Post-change verification
# ===========================================================================

@router.get("/verification/command/{command_id}")
def verify_command(
    command_id: str,
    window_minutes: int = Query(default=30, ge=5, le=480),
    settle_minutes: int = Query(default=2, ge=0, le=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Did this signal command measurably change anything?"""
    result = PostChangeVerification.verify_command(
        db, command_id, window_minutes=window_minutes, settle_minutes=settle_minutes,
    )
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=result["detail"])
    return result


@router.get("/verification/recent")
def recent_verifications(
    intersection_id: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    window_minutes: int = Query(default=30, ge=5, le=480),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Verification of the most recent executed commands."""
    return PostChangeVerification.recent_verifications(
        db, intersection_id=intersection_id, limit=limit, window_minutes=window_minutes,
    )


@router.get("/verification/window/{intersection_id}")
def verify_arbitrary_window(
    intersection_id: str,
    changed_at: datetime,
    window_minutes: int = Query(default=30, ge=5, le=480),
    settle_minutes: int = Query(default=2, ge=0, le=60),
    label: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Compare before/after around any moment the operator nominates."""
    return PostChangeVerification.verify_window(
        db, intersection_id, changed_at,
        window_minutes=window_minutes, settle_minutes=settle_minutes, label=label,
    )


# ===========================================================================
# Corridor time-space diagram
# ===========================================================================

@router.get("/stringline/{corridor_id}")
def corridor_stringline(
    corridor_id: str,
    minutes: int = Query(default=15, ge=1, le=240),
    phases: Optional[str] = Query(
        default=None, description="Comma-separated phase numbers to include."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Time-space diagram built from observed signal state."""
    phase_list: Optional[List[int]] = None
    if phases:
        try:
            phase_list = [int(p.strip()) for p in phases.split(",") if p.strip()]
        except ValueError:
            raise HTTPException(
                status_code=400, detail="phases must be comma-separated integers."
            )

    result = Stringline.build(db, corridor_id, minutes=minutes, phases=phase_list)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail=result["detail"])
    return result


# ===========================================================================
# Shift handover
# ===========================================================================

@router.get("/handover")
def list_handovers(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(ShiftHandover)
        .order_by(ShiftHandover.shift_end.desc())
        .limit(limit)
        .all()
    )
    return {
        "count": len(rows),
        "empty_reason": None if rows else "NO_HANDOVER_HAS_BEEN_CREATED",
        "handovers": [ShiftHandoverService.serialize(row) for row in rows],
    }


@router.get("/handover/preview")
def preview_handover(
    shift_hours: int = Query(default=8, ge=1, le=24),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The snapshot that would be generated, without creating a record."""
    from datetime import timedelta

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=shift_hours)
    return {
        "preview": True,
        "detail": "Nothing has been stored. Create a handover to record this.",
        "snapshot": ShiftHandoverService.generate_snapshot(db, start, end),
    }


@router.post("/handover", status_code=status.HTTP_201_CREATED)
def create_handover(
    data: HandoverCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope(scope_vocab.WRITE_INCIDENT)),
):
    """Generates a handover for the shift just ending."""
    handover = ShiftHandoverService.create(
        db,
        outgoing_operator=current_user.identity,
        shift_hours=data.shift_hours,
        incoming_operator=data.incoming_operator,
    )
    return ShiftHandoverService.serialize(handover)


@router.get("/handover/{handover_id}")
def get_handover(
    handover_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    handover = db.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
    if not handover:
        raise HTTPException(status_code=404, detail="Handover not found")
    return ShiftHandoverService.serialize(handover)


@router.patch("/handover/{handover_id}")
def update_handover(
    handover_id: str,
    data: HandoverUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope(scope_vocab.WRITE_INCIDENT)),
):
    """Edits a draft. The generated snapshot is never modified."""
    handover = db.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
    if not handover:
        raise HTTPException(status_code=404, detail="Handover not found")

    try:
        updated = ShiftHandoverService.update_draft(
            db, handover,
            operator_notes=data.operator_notes,
            pending_actions=(
                [action.model_dump() for action in data.pending_actions]
                if data.pending_actions is not None else None
            ),
            editor=current_user.identity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return ShiftHandoverService.serialize(updated)


@router.post("/handover/{handover_id}/sign-off")
def sign_off_handover(
    handover_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope(scope_vocab.WRITE_INCIDENT)),
):
    """Freezes the handover. It cannot be revised afterwards."""
    handover = db.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
    if not handover:
        raise HTTPException(status_code=404, detail="Handover not found")

    try:
        signed = ShiftHandoverService.sign_off(db, handover, current_user.identity)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return ShiftHandoverService.serialize(signed)


@router.post("/handover/{handover_id}/acknowledge")
def acknowledge_handover(
    handover_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_scope(scope_vocab.WRITE_INCIDENT)),
):
    """The incoming operator confirms they have read it."""
    handover = db.query(ShiftHandover).filter(ShiftHandover.id == handover_id).first()
    if not handover:
        raise HTTPException(status_code=404, detail="Handover not found")

    try:
        acknowledged = ShiftHandoverService.acknowledge(
            db, handover, current_user.identity
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    return ShiftHandoverService.serialize(acknowledged)
