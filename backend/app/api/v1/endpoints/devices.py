"""TRAFFICINTEL AI - Devices Management Endpoints

Tracks physical roadside hardware (ITS cabinets, radar detectors, cameras, MMUs).
Telemetry status: ONLINE, OFFLINE, DEGRADED, NOT_CONFIGURED.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import User, Device, AuditLog, utc_now

router = APIRouter(prefix="/devices", tags=["Devices"])


@router.get("")
def list_devices(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Device).all()


@router.post("", status_code=status.HTTP_201_CREATED)
def register_device(
    device_type: str,
    name: str,
    ip_address: Optional[str] = None,
    port: Optional[int] = None,
    firmware_version: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    device = Device(
        device_type=device_type,
        name=name,
        ip_address=ip_address,
        port=port,
        firmware_version=firmware_version,
        status="NOT_CONFIGURED"
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.post("/{id}/ping")
def ping_device(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    device = db.query(Device).filter(Device.id == id).first()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    import socket, time
    online = False
    latency_ms = None
    if device.ip_address:
        try:
            start = time.time()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.5)
            sock.connect((device.ip_address, device.port or 80))
            latency_ms = round((time.time() - start) * 1000.0, 1)
            sock.close()
            online = True
        except Exception:
            online = False

    device.status = "ONLINE" if online else "OFFLINE"
    device.last_seen = utc_now() if online else device.last_seen
    device.health_metrics = {"latency_ms": latency_ms, "last_ping": utc_now().isoformat()}
    db.commit()

    return {
        "device_id": device.id,
        "name": device.name,
        "status": device.status,
        "latency_ms": latency_ms
    }
