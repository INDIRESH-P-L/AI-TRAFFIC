"""TRAFFICINTEL AI - Intersections API Endpoints

CRUD for real configured intersections, approach geometries, lanes, and GIS data.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import (
    User, Intersection, Approach, Lane, SignalController, Camera, Sensor, TrafficMetric, AuditLog, utc_now
)
from app.schemas.domain import (
    IntersectionCreate, IntersectionSummary, IntersectionDetail, TrafficMetricResponse, WeatherResponse
)
from app.providers.weather_provider import RealGISWeatherAdapter

router = APIRouter(prefix="/intersections", tags=["Intersections"])


@router.get("", response_model=List[IntersectionSummary])
def list_intersections(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    intersections = db.query(Intersection).all()
    results = []
    for inter in intersections:
        # Check controller status
        ctrl = db.query(SignalController).filter(SignalController.intersection_id == inter.id).first()
        ctrl_status = ctrl.connection_status if ctrl else "NOT_CONFIGURED"

        # Check camera status
        cam = db.query(Camera).filter(Camera.intersection_id == inter.id).first()
        cam_status = cam.stream_status if cam else "NOT_CONFIGURED"

        # Incidents count
        inc_count = len(inter.incidents)

        results.append(IntersectionSummary(
            id=inter.id,
            name=inter.name,
            code=inter.code,
            latitude=inter.latitude,
            longitude=inter.longitude,
            jurisdiction=inter.jurisdiction,
            operational_status=inter.operational_status,
            controller_status=ctrl_status,
            camera_status=cam_status,
            active_incidents_count=inc_count
        ))
    return results


@router.post("", response_model=IntersectionDetail, status_code=status.HTTP_201_CREATED)
def create_intersection(
    data: IntersectionCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    existing = db.query(Intersection).filter((Intersection.code == data.code) | (Intersection.name == data.name)).first()
    if existing:
        raise HTTPException(status_code=400, detail=f"Intersection code '{data.code}' or name '{data.name}' already exists.")

    inter = Intersection(
        name=data.name,
        code=data.code,
        latitude=data.latitude,
        longitude=data.longitude,
        jurisdiction=data.jurisdiction,
        corridor_id=data.corridor_id,
        operational_status="HEALTHY"
    )
    db.add(inter)
    db.flush()

    # Add approaches and lanes
    for app_data in data.approaches:
        approach = Approach(
            intersection_id=inter.id,
            direction=app_data.direction,
            road_name=app_data.road_name,
            speed_limit_kph=app_data.speed_limit_kph
        )
        db.add(approach)
        db.flush()

        for lane_data in app_data.lanes:
            lane = Lane(
                approach_id=approach.id,
                lane_number=lane_data.lane_number,
                movement_type=lane_data.movement_type,
                assigned_phase=lane_data.assigned_phase
            )
            db.add(lane)

    # Audit
    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="CREATE_INTERSECTION",
        resource_type="Intersection",
        resource_id=inter.id,
        result="EXECUTED",
        details={"name": data.name, "code": data.code, "lat": data.latitude, "lng": data.longitude}
    )
    db.add(audit)

    db.commit()
    db.refresh(inter)
    return inter


@router.get("/{id}", response_model=IntersectionDetail)
def get_intersection(id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inter = db.query(Intersection).filter(Intersection.id == id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")
    return inter


@router.get("/{id}/traffic", response_model=TrafficMetricResponse)
def get_intersection_traffic(id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    metric = db.query(TrafficMetric).filter(
        TrafficMetric.intersection_id == id
    ).order_by(TrafficMetric.timestamp.desc()).first()

    if not metric:
        return TrafficMetricResponse(
            intersection_id=id,
            timestamp=None,
            vehicle_count=None,
            flow_rate_vph=None,
            occupancy_pct=None,
            avg_speed_kph=None,
            queue_length_meters=None,
            avg_wait_time_sec=None,
            traffic_pressure=None,
            data_quality="NO_DATA",
            calculation_method="NO_OBSERVATIONS_LOGGED",
            provenance={"status": "NO_TELEMETRY_SOURCE_RECORDED"}
        )
    return metric


@router.get("/{id}/weather", response_model=WeatherResponse)
def get_intersection_weather(id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    inter = db.query(Intersection).filter(Intersection.id == id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    adapter = RealGISWeatherAdapter()
    success, msg, data = adapter.fetch_weather(inter.latitude, inter.longitude)

    if not success or not data:
        return WeatherResponse(
            latitude=inter.latitude,
            longitude=inter.longitude,
            status="WEATHER_DATA_UNAVAILABLE"
        )

    return WeatherResponse(**data)
