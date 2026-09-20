"""TRAFFICINTEL AI - Maintenance Work Orders Endpoints
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, MaintenanceEvent, utc_now

router = APIRouter(prefix="/maintenance", tags=["Maintenance"])


@router.get("")
def list_maintenance_events(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(MaintenanceEvent).order_by(MaintenanceEvent.scheduled_date.asc()).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_maintenance_order(
    device_id: str,
    title: str,
    description: str = "",
    scheduled_date: Optional[datetime] = None,
    technician_name: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    event = MaintenanceEvent(
        device_id=device_id,
        title=title,
        description=description,
        scheduled_date=scheduled_date or utc_now(),
        technician_name=technician_name,
        status="SCHEDULED"
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/{id}/complete")
def complete_maintenance(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    event = db.query(MaintenanceEvent).filter(MaintenanceEvent.id == id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Maintenance event not found")

    event.status = "COMPLETED"
    event.completed_date = utc_now()
    db.commit()
    return event
