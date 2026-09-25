"""TRAFFICINTEL AI - Arterial Coordination Endpoints

Propose a green-wave plan for a corridor, apply it through the Safety Engine and
the single command dispatcher, and verify it against what the stringline
observes the controllers doing.

Proposing needs `optimizer:run`. Applying needs `signal:configure`: a timing
plan changes how a controller runs every cycle from then on, which is an
engineering decision rather than a momentary operator hold.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.coordination.green_wave import GreenWavePlanner
from app.core.database import get_db
from app.core.security import get_current_user, require_scope
from app.governance import scopes as scope_vocab
from app.models.entities import CoordinationPlan, User

router = APIRouter(prefix="/coordination", tags=["Arterial Coordination"])


class MovementInput(BaseModel):
    phase_number: int
    name: Optional[str] = None
    volume_vph: float = Field(ge=0)
    lanes: int = Field(default=1, ge=1, le=8)


class ProposeRequest(BaseModel):
    direction: str = Field(default="ASCENDING", description="ASCENDING or DESCENDING corridor order")
    design_speed_kph: Optional[float] = Field(default=None, description="Operator-entered; else the configured speed limit")
    cycle_sec: Optional[int] = Field(default=None, description="Operator-entered common cycle; else the critical junction's Webster optimum")
    coord_phase: int = Field(default=2, ge=1, le=16)
    movements: Optional[Dict[str, List[MovementInput]]] = Field(
        default=None, description="Per-junction volumes keyed by intersection id; omitted junctions use measured demand"
    )
    measured_window_minutes: int = Field(default=60, ge=15, le=1440)


def _principal_user_id(principal) -> Optional[str]:
    user = getattr(principal, "user", None)
    return getattr(user, "id", None)


@router.post("/corridors/{corridor_id}/propose")
def propose_plan(
    corridor_id: str,
    request: ProposeRequest,
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.RUN_OPTIMIZER)),
):
    """Computes a green-wave plan and validates it with the Safety Engine. Sends nothing."""
    try:
        result = GreenWavePlanner.propose(
            db, corridor_id, actor=principal.identity,
            direction=request.direction,
            design_speed_kph=request.design_speed_kph,
            cycle_sec=request.cycle_sec,
            coord_phase=request.coord_phase,
            movements={k: [m.model_dump() for m in v] for k, v in (request.movements or {}).items()},
            measured_window_minutes=request.measured_window_minutes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Corridor not found")
    return result


@router.get("/plans")
def list_plans(
    corridor_id: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(CoordinationPlan)
    if corridor_id:
        query = query.filter(CoordinationPlan.corridor_id == corridor_id)
    plans = query.order_by(CoordinationPlan.created_at.desc()).limit(limit).all()
    return {
        "count": len(plans),
        "empty_reason": None if plans else "NO_COORDINATION_PLAN_HAS_BEEN_PROPOSED",
        "plans": [GreenWavePlanner.serialize(p) for p in plans],
    }


@router.get("/plans/{plan_id}")
def get_plan(plan_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    plan = db.query(CoordinationPlan).filter(CoordinationPlan.id == plan_id).first()
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")
    return GreenWavePlanner.serialize(plan)


@router.post("/plans/{plan_id}/apply")
def apply_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.CONFIGURE_SIGNAL)),
):
    """Re-validates every controller, then writes the plan through the dispatcher."""
    result = GreenWavePlanner.apply(db, plan_id, _principal_user_id(principal), principal.identity)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Plan not found")
    if result.get("status") == "CONFLICT":
        raise HTTPException(status_code=409, detail=result["detail"])
    return result


@router.get("/plans/{plan_id}/verify")
def verify_plan(
    plan_id: str,
    minutes: int = Query(default=15, ge=3, le=240),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Planned offsets against the offsets the stringline actually observes."""
    result = GreenWavePlanner.verify(db, plan_id, minutes=minutes)
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Plan not found")
    return result
