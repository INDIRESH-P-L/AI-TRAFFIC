"""TRAFFICINTEL AI - Transit Signal Priority (TSP) Endpoints

Interface for GTFS and GTFS-Realtime transit priority feeds.
Never fabricates fictional buses or arrival ETAs.
"""

from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User, TransitEvent

router = APIRouter(prefix="/transit", tags=["Transit Priority"])


@router.get("")
def list_transit_events(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    events = db.query(TransitEvent).order_by(TransitEvent.timestamp.desc()).all()
    status_label = "ACTIVE_TRANSIT_FEED" if events else "TRANSIT_FEED_NOT_CONFIGURED"
    return {
        "status": status_label,
        "message": "Connected to GTFS-RT feed" if events else "No GTFS or transit telemetry source currently configured.",
        "active_buses_count": len(events),
        "events": events
    }
