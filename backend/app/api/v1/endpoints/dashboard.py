"""TRAFFICINTEL AI - Operational Dashboard Summary Endpoints

Purely reflects real system state.
Returns truthful zero/empty states on clean installation. Never fabricates KPI numbers.
"""

from typing import Dict, Any, List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    User, Intersection, SignalController, Camera, Sensor, Incident, Alert, Device, TrafficMetric
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
def get_dashboard_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Computes genuine operational platform summary.

    If infrastructure is empty, reports truthful NOT_CONFIGURED status.
    """
    total_intersections = db.query(Intersection).count()
    total_controllers = db.query(SignalController).count()
    connected_controllers = db.query(SignalController).filter(SignalController.connection_status == "CONNECTED").count()
    
    total_cameras = db.query(Camera).count()
    connected_cameras = db.query(Camera).filter(Camera.stream_status == "CONNECTED").count()
    
    total_sensors = db.query(Sensor).count()
    connected_sensors = db.query(Sensor).filter(Sensor.health_status == "CONNECTED").count()

    active_incidents = db.query(Incident).filter(Incident.status.in_(["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE"])).all()
    unacknowledged_alerts = db.query(Alert).filter(Alert.is_acknowledged == False).all()

    # Determine honest overall system status
    if total_intersections == 0 and total_controllers == 0 and total_cameras == 0:
        system_status = "SYSTEM_READY_NO_INFRASTRUCTURE_CONNECTED"
        status_message = "No traffic infrastructure is currently connected."
    elif connected_controllers == 0 and total_controllers > 0:
        system_status = "LIMITED_CONTROLLERS_OFFLINE"
        status_message = "Configured signal controllers are currently unreachable."
    else:
        system_status = "HEALTHY" if len(active_incidents) == 0 else "OPERATIONAL_INCIDENTS_ACTIVE"
        status_message = "System operational."

    return {
        "system_status": system_status,
        "status_message": status_message,
        "infrastructure": {
            "total_intersections": total_intersections,
            "controllers": {
                "total": total_controllers,
                "connected": connected_controllers,
                "status": "CONNECTED" if connected_controllers > 0 else ("NOT_CONNECTED" if total_controllers > 0 else "NOT_CONFIGURED")
            },
            "cameras": {
                "total": total_cameras,
                "connected": connected_cameras,
                "status": "ONLINE" if connected_cameras > 0 else ("OFFLINE" if total_cameras > 0 else "NOT_CONFIGURED")
            },
            "sensors": {
                "total": total_sensors,
                "connected": connected_sensors,
                "status": "CONNECTED" if connected_sensors > 0 else ("DISCONNECTED" if total_sensors > 0 else "NOT_CONFIGURED")
            }
        },
        "incidents": {
            "active_count": len(active_incidents),
            "status": "INCIDENTS_ACTIVE" if len(active_incidents) > 0 else "NO_INCIDENT_DATA_AVAILABLE",
            "items": [
                {
                    "id": inc.id,
                    "title": inc.title,
                    "type": inc.type,
                    "severity": inc.severity,
                    "status": inc.status,
                    "detected_at": inc.detected_at.isoformat() if inc.detected_at else None
                } for inc in active_incidents[:5]
            ]
        },
        "alerts": {
            "unacknowledged_count": len(unacknowledged_alerts),
            "items": [
                {
                    "id": alt.id,
                    "severity": alt.severity,
                    "category": alt.category,
                    "title": alt.title,
                    "timestamp": alt.timestamp.isoformat() if alt.timestamp else None
                } for alt in unacknowledged_alerts[:5]
            ]
        }
    }
