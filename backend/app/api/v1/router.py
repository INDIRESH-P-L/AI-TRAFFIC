"""TRAFFICINTEL AI - API v1 Master Router
"""

from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    dashboard,
    intersections,
    signals,
    cameras,
    sensors,
    incidents,
    emergency,
    transit,
    predictions,
    analytics,
    corridors,
    copilot,
    devices,
    maintenance,
    audit,
    settings,
    users,
    map_layers,
    timeline,
    health,
    rules,
    optimizer,
    governance,
    ingest,
    reports,
    insights,
    readiness,
)

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(dashboard.router)
api_router.include_router(intersections.router)
api_router.include_router(signals.router)
api_router.include_router(cameras.router)
api_router.include_router(sensors.router)
api_router.include_router(incidents.router)
api_router.include_router(emergency.router)
api_router.include_router(transit.router)
api_router.include_router(predictions.router)
api_router.include_router(analytics.router)
api_router.include_router(corridors.router)
api_router.include_router(copilot.router)
api_router.include_router(devices.router)
api_router.include_router(maintenance.router)
api_router.include_router(audit.router)
api_router.include_router(settings.router)
api_router.include_router(users.router)
api_router.include_router(map_layers.router)
api_router.include_router(timeline.router)
api_router.include_router(readiness.router)
api_router.include_router(health.router)
api_router.include_router(rules.router)
api_router.include_router(optimizer.router)
api_router.include_router(governance.router)
api_router.include_router(ingest.router)
api_router.include_router(reports.router)
api_router.include_router(insights.router)
