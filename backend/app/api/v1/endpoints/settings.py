"""TRAFFICINTEL AI - System Settings & Provider Connection Wizards

Validates real external hardware, GIS, and weather endpoints.
Prevents marking an integration as 'connected' unless actual network validation passes.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db, engine
from app.core.security import get_current_user, require_roles
from app.models.entities import User
from app.providers.controller_provider import GenericIPControllerAdapter
from app.providers.camera_provider import NetworkCameraAdapter
from app.providers.weather_provider import RealGISWeatherAdapter
from app.core.config import settings
from app.core.migrations import check_schema_is_current

logger = logging.getLogger("trafficintel.settings")

router = APIRouter(prefix="/settings", tags=["Settings & Integrations"])


@router.get("/status")
def get_system_integrations_status(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Returns the honest configuration state of each subsystem.

    "Configured" and "verified" are different claims and are reported as such:
    a provider with a URL in settings is CONFIGURED; only a subsystem this
    request actually exercised is reported as reachable.
    """
    # Database: measured by executing a query, not inferred from settings.
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "CONNECTED"
        db_dialect = engine.dialect.name
    except Exception as exc:  # noqa: BLE001
        db_status = "UNREACHABLE"
        db_dialect = engine.dialect.name
        logger.error("Database probe failed in settings status: %s", exc)

    schema_current, schema_message = check_schema_is_current()

    return {
        "system_version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "subsystems": {
            "database": {
                "status": db_status,
                "dialect": db_dialect,
                "schema_current": schema_current,
                "schema_detail": schema_message,
                "verification": "MEASURED_THIS_REQUEST",
            },
            "map_provider": {
                "provider": "Esri World Light Gray / OpenStreetMap tiles (browser-side)",
                "status": "CONFIGURED",
                "verification": "NOT_MEASURED_TILES_LOADED_BY_BROWSER",
            },
            "weather_provider": {
                "provider": "Open-Meteo",
                "endpoint": settings.OPEN_METEO_API_URL,
                "status": "CONFIGURED",
                "verification": "NOT_MEASURED_PROBED_PER_INTERSECTION_REQUEST",
            },
            "signal_control": {
                "implemented_protocols": ["NTCIP_1202"],
                "status": "CONFIGURED",
                "note": (
                    "Controllers on other protocols are reachability-tested only and "
                    "cannot accept commands."
                ),
            },
            "vision_inference": {
                "provider": None,
                "status": "NOT_CONFIGURED",
                "note": (
                    "No detection model is installed. The frame pipeline accepts "
                    "detections posted by an edge unit; it runs no model itself."
                ),
            },
            "llm_copilot": {
                "provider": settings.LLM_MODEL if settings.LLM_API_KEY else None,
                "status": "CONFIGURED" if settings.LLM_API_KEY else "NOT_CONFIGURED",
                "note": (
                    "The Copilot answers from database records and indexed standards. "
                    "No LLM is called when no API key is configured."
                ),
            },
            "safety_engine": {
                "specification": "NEMA TS2 deterministic dual-ring barrier validation",
                "status": "IN_COMMAND_PATH",
                "note": (
                    "Structural, not a liveness reading: every signal command and "
                    "preemption call is validated before reaching an adapter."
                ),
            },
        }
    }


@router.post("/test-controller-wizard")
def test_controller_wizard(
    ip_address: str,
    port: int = 501,
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    """Connection wizard tool: tests physical controller reachability before configuration."""
    adapter = GenericIPControllerAdapter(ip_address=ip_address, port=port)
    success, msg = adapter.connect()
    return {
        "reachable": success,
        "message": msg,
        "latency_ms": adapter.last_latency_ms if success else None,
        "allowed_to_save_as_connected": success
    }


@router.post("/test-camera-wizard")
def test_camera_wizard(
    stream_url: str,
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    """Connection wizard tool: tests camera RTSP / IP port reachability before saving."""
    adapter = NetworkCameraAdapter(stream_url=stream_url)
    success, msg, details = adapter.test_connection()
    return {
        "reachable": success,
        "message": msg,
        "details": details,
        "allowed_to_save_as_connected": success
    }
