"""TRAFFICINTEL AI - Traffic Sensors API Endpoints
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, Sensor, TrafficObservation, Intersection, utc_now
from app.providers.sensor_provider import RoadsideSensorAdapter

router = APIRouter(prefix="/sensors", tags=["Sensors"])


@router.get("")
def list_sensors(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Sensor).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_sensor(
    intersection_id: str,
    name: str,
    sensor_type: str,
    telemetry_endpoint: str = "",
    lane_id: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    sensor = Sensor(
        intersection_id=intersection_id,
        name=name,
        sensor_type=sensor_type,
        telemetry_endpoint=telemetry_endpoint,
        lane_id=lane_id,
        health_status="DISCONNECTED"
    )
    db.add(sensor)
    db.commit()
    db.refresh(sensor)
    return sensor


@router.post("/{id}/telemetry")
def ingest_sensor_telemetry(
    id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db)
):
    """Ingests raw sensor telemetry with physical range validation."""
    sensor = db.query(Sensor).filter(Sensor.id == id).first()
    if not sensor:
        raise HTTPException(status_code=404, detail="Sensor not found")

    adapter = RoadsideSensorAdapter(sensor.id, sensor.sensor_type, sensor.telemetry_endpoint)
    validated = adapter.ingest_telemetry(payload)

    sensor.health_status = "CONNECTED"
    sensor.last_observation_timestamp = utc_now()
    sensor.quality = validated["quality"]

    obs = TrafficObservation(
        intersection_id=sensor.intersection_id,
        lane_id=sensor.lane_id,
        source=f"sensor_{sensor.name}",
        source_id=sensor.id,
        timestamp=utc_now(),
        vehicle_count=validated["vehicle_count"],
        occupancy_pct=validated["occupancy_pct"],
        avg_speed_kph=validated["avg_speed_kph"],
        quality=validated["quality"],
        provenance=validated["provenance"]
    )
    db.add(obs)
    db.commit()

    return {"status": "INGESTED", "validated_quality": validated["quality"]}
