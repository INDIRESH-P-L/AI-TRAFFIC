"""TRAFFICINTEL AI - Cameras API Endpoints

Interfacing with IP cameras and RTSP streams.
Performs real network socket reachability tests. Never fabricates camera frames.
"""

from typing import List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, Camera, Intersection, AuditLog, utc_now
from app.providers.camera_provider import NetworkCameraAdapter
from app.vision.pipeline import ComputerVisionPipeline, DetectedObject

router = APIRouter(prefix="/cameras", tags=["Cameras"])


@router.get("")
def list_cameras(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Camera).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def create_camera(
    intersection_id: str,
    name: str,
    stream_url: str,
    resolution: str = "1920x1080",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    camera = Camera(
        intersection_id=intersection_id,
        name=name,
        stream_url=stream_url,
        resolution=resolution,
        stream_status="OFFLINE"
    )
    db.add(camera)
    db.commit()
    db.refresh(camera)
    return camera


@router.post("/{id}/test-connection")
def test_camera_connection(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    camera = db.query(Camera).filter(Camera.id == id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    adapter = NetworkCameraAdapter(stream_url=camera.stream_url)
    info = adapter.get_stream_info()
    success = info["stream_status"] != "OFFLINE"

    # REACHABLE, not CONNECTED: a successful TCP handshake proves the host is
    # listening. CONNECTED is reserved for a camera that has actually delivered
    # frames through the ingest endpoint.
    camera.stream_status = "REACHABLE" if success else "OFFLINE"
    db.commit()

    return {
        "camera_id": camera.id,
        "name": camera.name,
        "stream_url": camera.stream_url,
        "stream_status": camera.stream_status,
        "test_result": info["message"],
        "measurement_status": info["measurement_status"],
        "fps": info["fps"],
        "resolution": info["resolution"],
        "last_frame_timestamp": camera.last_frame_timestamp.isoformat() if camera.last_frame_timestamp else None,
        "details": info["details"]
    }


@router.post("/{id}/diagnostic-ingest")
def diagnostic_frame_ingest(
    id: str,
    payload: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    """Processes an actual frame detection payload from an edge camera unit."""
    camera = db.query(Camera).filter(Camera.id == id).first()
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    pipeline = ComputerVisionPipeline(camera_id=camera.id)
    raw_detections = payload.get("detections", [])
    detection_objs = [
        DetectedObject(
            class_name=d["class_name"],
            confidence=float(d["confidence"]),
            bbox=d["bbox"],
            track_id=d.get("track_id")
        ) for d in raw_detections
    ]

    result = pipeline.process_frame(frame_timestamp=utc_now(), detections=detection_objs)
    camera.last_frame_timestamp = utc_now()
    camera.stream_status = "CONNECTED"
    db.commit()

    return result
