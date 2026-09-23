"""TRAFFICINTEL AI - GIS Map Layer Endpoints

Serves the layered operations map. Every feature carries its own provenance:
what source produced it, when, and what data-quality state that timestamp puts
it in. A layer with no real records returns an empty feature list and a reason,
never a placeholder marker.

Cameras, sensors and incidents have no independent coordinates in the schema -
they are sited at their intersection - so their features inherit the junction
position and say so in `position_source`. That is a real limitation of the
data model, and the map states it rather than scattering markers around a
junction to look convincing.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    Camera, Incident, Intersection, Sensor, SignalController, TrafficMetric,
    TransitEvent, User, WeatherObservation,
)
from app.traffic.quality_engine import DataQualityEngine

router = APIRouter(prefix="/map", tags=["GIS Map"])

POSITION_FROM_JUNCTION = "INHERITED_FROM_INTERSECTION_NO_DEVICE_COORDINATES"


def _quality(timestamp: Optional[datetime], source: Optional[str]) -> Dict[str, Any]:
    """Uniform provenance envelope attached to every map feature."""
    state, age_sec = DataQualityEngine.evaluate_freshness(timestamp)
    return {
        "state": state,
        "age_sec": round(age_sec, 1) if age_sec >= 0 else None,
        "observed_at": timestamp.isoformat() if timestamp else None,
        "source": source,
    }


# Worst-wins ordering for rolling several sources up into one junction verdict.
_QUALITY_SEVERITY = [
    "FRESH", "UNKNOWN", "NO_DATA", "AGING", "STALE", "INVALID", "DISCONNECTED",
]


def _worst_quality(candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Rolls per-source provenance into one envelope, worst state winning.

    A junction marker must not read FRESH because one of its three sources is
    live. If its detectors went silent an hour ago the junction is degraded,
    and the map has to show that at a glance - averaging or taking the most
    recent source would hide exactly the junction worth looking at.
    """
    if not candidates:
        return {
            "state": "NO_DATA",
            "age_sec": None,
            "observed_at": None,
            "source": None,
        }

    def rank(candidate: Dict[str, Any]) -> int:
        try:
            return _QUALITY_SEVERITY.index(candidate.get("state", "UNKNOWN"))
        except ValueError:
            return _QUALITY_SEVERITY.index("UNKNOWN")

    worst = max(candidates, key=rank)
    sources = [c["source"] for c in candidates if c.get("source")]
    return {
        "state": worst["state"],
        "age_sec": worst["age_sec"],
        "observed_at": worst["observed_at"],
        "source": sources or None,
    }


@router.get("")
def get_map_layers(
    include: Optional[str] = Query(
        default=None,
        description="Comma-separated layer names. Omit for all layers.",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Returns every map layer with per-feature provenance and truthful empties."""
    requested = (
        {name.strip() for name in include.split(",") if name.strip()}
        if include else None
    )

    def wanted(layer: str) -> bool:
        return requested is None or layer in requested

    intersections = db.query(Intersection).all()
    by_id = {i.id: i for i in intersections}
    now = datetime.now(timezone.utc)

    layers: Dict[str, Any] = {}

    # --- Junctions --------------------------------------------------------
    if wanted("junctions"):
        features = []
        for inter in intersections:
            controller = (
                db.query(SignalController)
                .filter(SignalController.intersection_id == inter.id)
                .first()
            )
            metric = (
                db.query(TrafficMetric)
                .filter(TrafficMetric.intersection_id == inter.id)
                .order_by(TrafficMetric.timestamp.desc())
                .first()
            )
            open_incidents = (
                db.query(Incident)
                .filter(
                    Incident.intersection_id == inter.id,
                    Incident.status.in_(["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE"]),
                )
                .count()
            )

            controller_quality = _quality(
                controller.last_heartbeat if controller else None,
                f"controller:{controller.protocol}" if controller else None,
            )
            traffic_quality = _quality(
                metric.timestamp if metric else None,
                (metric.provenance or {}).get("sources_used") if metric else None,
            )

            # Only sources that are actually configured contribute. An
            # unconfigured camera is not a degraded camera.
            contributing = []
            if controller:
                contributing.append(controller_quality)
            if metric:
                contributing.append(traffic_quality)

            features.append({
                "id": inter.id,
                "name": inter.name,
                "code": inter.code,
                "quality": _worst_quality(contributing),
                "quality_basis": (
                    [c["source"] for c in contributing if c.get("source")]
                    or ["NO_SOURCE_CONFIGURED"]
                ),
                "latitude": inter.latitude,
                "longitude": inter.longitude,
                "position_source": "CONFIGURED_INTERSECTION_COORDINATES",
                "operational_status": inter.operational_status,
                "jurisdiction": inter.jurisdiction,
                "open_incident_count": open_incidents,
                "controller": {
                    "id": controller.id if controller else None,
                    "name": controller.name if controller else None,
                    "protocol": controller.protocol if controller else None,
                    "connection_status": controller.connection_status if controller else "NOT_CONFIGURED",
                    "active_phase": controller.active_phase if controller else None,
                    "clearing_phases": controller.clearing_phases if controller else None,
                    "quality": controller_quality,
                } if controller else {
                    "connection_status": "NOT_CONFIGURED",
                    "quality": _quality(None, None),
                },
                "traffic": {
                    "data_quality": metric.data_quality if metric else "NO_DATA",
                    "vehicle_count": metric.vehicle_count if metric else None,
                    "avg_speed_kph": metric.avg_speed_kph if metric else None,
                    "occupancy_pct": metric.occupancy_pct if metric else None,
                    "quality": traffic_quality,
                } if metric else {
                    "data_quality": "NO_DATA",
                    "status": "NO_TELEMETRY_RECORDED_FOR_THIS_JUNCTION",
                    "quality": _quality(None, None),
                },
            })

        layers["junctions"] = {
            "features": features,
            "empty_reason": None if features else "NO_INTERSECTIONS_CONFIGURED",
        }

    # --- Cameras ----------------------------------------------------------
    if wanted("cameras"):
        features = []
        for cam in db.query(Camera).all():
            inter = by_id.get(cam.intersection_id)
            if not inter:
                continue
            features.append({
                "id": cam.id,
                "name": cam.name,
                "latitude": inter.latitude,
                "longitude": inter.longitude,
                "position_source": POSITION_FROM_JUNCTION,
                "intersection_id": inter.id,
                "intersection_name": inter.name,
                "stream_status": cam.stream_status,
                "detection_enabled": cam.detection_enabled,
                # Null unless an RTSP session actually measured them.
                "fps": cam.fps or None,
                "resolution": cam.resolution if cam.stream_status == "CONNECTED" else None,
                "quality": _quality(cam.last_frame_timestamp, f"camera:{cam.name}"),
            })
        layers["cameras"] = {
            "features": features,
            "empty_reason": None if features else "NO_CAMERA_CONNECTED",
        }

    # --- Sensors ----------------------------------------------------------
    if wanted("sensors"):
        features = []
        for sensor in db.query(Sensor).all():
            inter = by_id.get(sensor.intersection_id)
            if not inter:
                continue
            features.append({
                "id": sensor.id,
                "name": sensor.name,
                "latitude": inter.latitude,
                "longitude": inter.longitude,
                "position_source": POSITION_FROM_JUNCTION,
                "intersection_id": inter.id,
                "intersection_name": inter.name,
                "sensor_type": sensor.sensor_type,
                "health_status": sensor.health_status,
                "quality": _quality(
                    sensor.last_observation_timestamp, f"sensor:{sensor.sensor_type}"
                ),
            })
        layers["sensors"] = {
            "features": features,
            "empty_reason": None if features else "NO_SENSOR_DATA_AVAILABLE",
        }

    # --- Incidents --------------------------------------------------------
    if wanted("incidents"):
        features = []
        open_incidents = (
            db.query(Incident)
            .filter(Incident.status.in_(["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE", "MITIGATED"]))
            .order_by(Incident.detected_at.desc())
            .all()
        )
        for inc in open_incidents:
            inter = by_id.get(inc.intersection_id)
            if not inter:
                continue
            features.append({
                "id": inc.id,
                "title": inc.title,
                "latitude": inter.latitude,
                "longitude": inter.longitude,
                "position_source": POSITION_FROM_JUNCTION,
                "intersection_id": inter.id,
                "intersection_name": inter.name,
                "type": inc.type,
                "severity": inc.severity,
                "status": inc.status,
                "confidence": inc.confidence,
                "quality": _quality(inc.detected_at, inc.source),
            })
        layers["incidents"] = {
            "features": features,
            "empty_reason": None if features else "NO_ACTIVE_INCIDENTS",
        }

    # --- Weather (stored observations only) -------------------------------
    if wanted("weather"):
        cutoff = now - timedelta(hours=3)
        features = []
        observations = (
            db.query(WeatherObservation)
            .filter(WeatherObservation.timestamp >= cutoff.replace(tzinfo=None))
            .order_by(WeatherObservation.timestamp.desc())
            .limit(200)
            .all()
        )
        for obs in observations:
            features.append({
                "id": obs.id,
                "latitude": obs.latitude,
                "longitude": obs.longitude,
                "position_source": "OBSERVATION_COORDINATES",
                "temperature_c": obs.temperature_c,
                "precipitation_mm": obs.precipitation_mm,
                "wind_speed_kph": obs.wind_speed_kph,
                "visibility_meters": obs.visibility_meters,
                "road_condition": obs.road_condition,
                "quality": _quality(obs.timestamp, obs.source),
            })
        layers["weather"] = {
            "features": features,
            # Weather is fetched per junction on request and only persisted when
            # a fetch succeeds; an empty layer means nothing has been stored.
            "empty_reason": None if features else "WEATHER_DATA_UNAVAILABLE",
        }

    # --- Transit ----------------------------------------------------------
    if wanted("transit"):
        features = []
        cutoff = now - timedelta(minutes=15)
        events = (
            db.query(TransitEvent)
            .filter(TransitEvent.timestamp >= cutoff.replace(tzinfo=None))
            .order_by(TransitEvent.timestamp.desc())
            .limit(500)
            .all()
        )
        for event in events:
            inter = by_id.get(event.intersection_id)
            if not inter:
                continue
            features.append({
                "id": event.id,
                "route_id": event.route_id,
                "vehicle_id": event.vehicle_id,
                "latitude": inter.latitude,
                "longitude": inter.longitude,
                "position_source": POSITION_FROM_JUNCTION,
                "intersection_id": inter.id,
                "delay_seconds": event.delay_seconds,
                "priority_requested": event.priority_requested,
                "priority_granted": event.priority_granted,
                "quality": _quality(event.timestamp, event.source),
            })
        layers["transit"] = {
            "features": features,
            "empty_reason": None if features else "TRANSIT_FEED_NOT_CONFIGURED",
        }

    return {
        "generated_at": now.isoformat(),
        "quality_thresholds_sec": {
            "fresh": DataQualityEngine.fresh_threshold_sec(),
            "aging": DataQualityEngine.aging_threshold_sec(),
            "stale": DataQualityEngine.stale_threshold_sec(),
        },
        "layers": layers,
    }
