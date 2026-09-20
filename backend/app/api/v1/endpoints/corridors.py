"""TRAFFICINTEL AI - Coordinated Corridors Endpoints
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, Corridor, Intersection

router = APIRouter(prefix="/corridors", tags=["Corridors"])


@router.get("")
def list_corridors(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    corridors = db.query(Corridor).all()
    res = []
    for c in corridors:
        res.append({
            "id": c.id,
            "name": c.name,
            "description": c.description,
            "coordination_mode": c.coordination_mode,
            "cycle_length_sec": c.cycle_length_sec,
            "intersection_count": len(c.intersections)
        })
    return res


@router.post("", status_code=status.HTTP_201_CREATED)
def create_corridor(
    name: str,
    description: str = "",
    coordination_mode: str = "GREEN_WAVE",
    cycle_length_sec: int = 90,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    corridor = Corridor(
        name=name,
        description=description,
        coordination_mode=coordination_mode,
        cycle_length_sec=cycle_length_sec
    )
    db.add(corridor)
    db.commit()
    db.refresh(corridor)
    return corridor
