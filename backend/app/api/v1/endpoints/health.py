"""TRAFFICINTEL AI - Provider Health Endpoints

Reports what the platform has measured about each external dependency. A
provider nobody has probed is `UNKNOWN`, never `HEALTHY`: absence of evidence
is reported as absence of evidence.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends

from app.core.security import get_current_user
from app.events.bus import event_bus
from app.health.monitor import provider_monitor
from app.models.entities import User
from app.api.v1.websocket import ws_manager

router = APIRouter(prefix="/health", tags=["Provider Health"])


@router.get("/providers")
def list_provider_health(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Health of every provider the platform has actually called."""
    providers = provider_monitor.all()

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "summary": provider_monitor.summary(),
        "providers": providers,
        "empty_reason": None if providers else (
            "NO_PROVIDER_HAS_BEEN_CONTACTED_YET"
        ),
        "note": (
            "States are derived from observed calls with hysteresis: a provider "
            "must fail repeatedly to degrade and succeed repeatedly to recover, "
            "so a flapping endpoint does not flood the notification centre."
        ),
    }


@router.get("/stream")
def stream_health(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Event bus and WebSocket gateway health, including dropped-event counts."""
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "bus": event_bus.stats(),
        "gateway": ws_manager.stats(),
        "note": (
            "dropped_events is non-zero when a console fell behind and the bus "
            "discarded its oldest queued events. That client's view has a gap."
        ),
    }


@router.get("/poller")
def poller_status(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Controller polling service status and its last cycle."""
    from app.ingest.poller import controller_poller
    return controller_poller.status()


@router.post("/poller/poll-now")
def poll_now(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Runs one poll cycle immediately and returns what it observed."""
    from app.ingest.poller import controller_poller
    return controller_poller.poll_once()
