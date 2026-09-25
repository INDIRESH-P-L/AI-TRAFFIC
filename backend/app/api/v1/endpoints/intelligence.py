"""TRAFFICINTEL AI - Grounded Intelligence Endpoints

Anomaly detection and fusion-based incident detection, both computed from
stored telemetry only. Neither endpoint writes anything except the explicit
`/record` action, which creates incidents in DETECTED and never beyond it.

Forecasting lives at `/predictions/forecast/{id}`, where the refusal path it
replaces already was.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.analytics.anomaly import AnomalyDetector
from app.api.v1.websocket import ws_manager
from app.core.database import get_db
from app.core.security import get_current_user, require_scope
from app.governance import scopes as scope_vocab
from app.incidents.fusion import IncidentFusionDetector
from app.models.entities import User

router = APIRouter(prefix="/intelligence", tags=["Grounded Intelligence"])


def _or_404(result: Dict[str, Any]) -> Dict[str, Any]:
    if result.get("status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Intersection not found")
    return result


@router.get("/anomalies/{intersection_id}")
def detect_anomalies(
    intersection_id: str,
    test_minutes: int = Query(default=15, ge=5, le=120),
    history_days: int = Query(default=7, ge=1, le=30),
    as_of: Optional[datetime] = Query(
        default=None, description="Evaluate as of this instant instead of now."
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Point and sustained-shift anomalies in stored throughput, occupancy, speed."""
    return _or_404(AnomalyDetector.detect(
        db, intersection_id, as_of=as_of,
        test_minutes=test_minutes, history_days=history_days,
    ))


@router.get("/incident-fusion/{intersection_id}")
def evaluate_incident_fusion(
    intersection_id: str,
    recent_minutes: int = Query(default=10, ge=3, le=60),
    baseline_minutes: int = Query(default=60, ge=15, le=240),
    as_of: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Evaluates corroborated incident signatures per approach. Writes nothing."""
    return _or_404(IncidentFusionDetector.evaluate(
        db, intersection_id, as_of=as_of,
        recent_minutes=recent_minutes, baseline_minutes=baseline_minutes,
    ))


@router.post("/incident-fusion/{intersection_id}/record")
async def record_fusion_incidents(
    intersection_id: str,
    recent_minutes: int = Query(default=10, ge=3, le=60),
    baseline_minutes: int = Query(default=60, ge=15, le=240),
    as_of: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    principal=Depends(require_scope(scope_vocab.WRITE_INCIDENT)),
):
    """Records each corroborated probable incident as DETECTED, with evidence."""
    result = _or_404(IncidentFusionDetector.record(
        db, intersection_id, actor=principal.identity, as_of=as_of,
        recent_minutes=recent_minutes, baseline_minutes=baseline_minutes,
    ))
    for entry in result["recorded"]:
        await ws_manager.broadcast_event("incident.detected", {
            "incident_id": entry["incident_id"],
            "title": "Probable incident: {}".format(entry["approach"]),
            "severity": "MEDIUM",
            "intersection_id": intersection_id,
            "source": "FUSION_DETECTOR",
        })
    return result
