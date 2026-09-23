"""TRAFFICINTEL AI - Junction Timeline & Historical Replay

Two read-only views over what the platform has actually stored:

* `/timeline/{intersection_id}` merges incidents, signal commands, preemption
  calls and audit entries for one junction into a single chronological feed.

* `/timeline/{intersection_id}/replay` returns stored telemetry and signal
  events over a window so the console's time scrubber can replay them.

Both refuse to interpolate. The replay endpoint returns the samples that exist
and states how many there were; a gap in the data stays a gap, because a
smoothed line across a sensor outage would show an operator traffic that was
never measured.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    AuditLog, EmergencyEvent, Incident, Intersection, SignalCommand,
    SignalController, TrafficMetric, TrafficObservation, User,
)
from app.traffic.quality_engine import DataQualityEngine

router = APIRouter(prefix="/timeline", tags=["Timeline & Replay"])

# Below this many samples a replay window is reported as insufficient rather
# than drawn: two points across an hour is not a history, it is two points.
MIN_REPLAY_SAMPLES = 3


def _naive(dt: datetime) -> datetime:
    """Stored timestamps are naive UTC; comparisons must match that."""
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


@router.get("/{intersection_id}")
def get_junction_timeline(
    intersection_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Chronological feed of real recorded events for one junction."""
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    since = _naive(datetime.now(timezone.utc) - timedelta(hours=hours))
    events: List[Dict[str, Any]] = []

    for inc in (
        db.query(Incident)
        .filter(Incident.intersection_id == intersection_id, Incident.detected_at >= since)
        .all()
    ):
        events.append({
            "timestamp": _iso(inc.detected_at),
            "kind": "INCIDENT",
            "severity": inc.severity,
            "title": inc.title,
            "detail": f"{inc.type} reported by {inc.source} (status {inc.status})",
            "source": inc.source,
            "resource_type": "Incident",
            "resource_id": inc.id,
        })
        if inc.resolved_at:
            events.append({
                "timestamp": _iso(inc.resolved_at),
                "kind": "INCIDENT_RESOLVED",
                "severity": "INFO",
                "title": f"Resolved: {inc.title}",
                "detail": f"Incident cleared after {inc.type}",
                "source": inc.source,
                "resource_type": "Incident",
                "resource_id": inc.id,
            })

    controller_ids = [
        c.id for c in db.query(SignalController)
        .filter(SignalController.intersection_id == intersection_id).all()
    ]
    if controller_ids:
        for cmd in (
            db.query(SignalCommand)
            .filter(SignalCommand.controller_id.in_(controller_ids), SignalCommand.issued_at >= since)
            .all()
        ):
            payload = cmd.response_payload or {}
            post_state = payload.get("post_command_state") or {}
            events.append({
                "timestamp": _iso(cmd.issued_at),
                "kind": "SIGNAL_COMMAND",
                "severity": "WARNING" if cmd.status in ("REJECTED", "FAILED") else "INFO",
                "title": f"{cmd.command_type} phase {cmd.requested_phase} - {cmd.status}",
                "detail": (
                    "; ".join((cmd.safety_report or {}).get("violations", []))
                    or post_state.get("effect_verification")
                    or f"Held for {cmd.duration_sec}s"
                ),
                "source": "OPERATOR_COMMAND",
                "resource_type": "SignalCommand",
                "resource_id": cmd.id,
                "safety_passed": cmd.safety_check_passed,
            })

    for evp in (
        db.query(EmergencyEvent)
        .filter(EmergencyEvent.intersection_id == intersection_id, EmergencyEvent.timestamp >= since)
        .all()
    ):
        events.append({
            "timestamp": _iso(evp.timestamp),
            "kind": "PREEMPTION",
            "severity": "CRITICAL" if evp.status == "ACTIVE" else "WARNING",
            "title": f"{evp.vehicle_type} preemption {evp.status} (phase {evp.requested_phase})",
            "detail": (
                "; ".join((evp.safety_report or {}).get("violations", []))
                or "Cleared by the Deterministic Safety Engine"
            ),
            "source": evp.source,
            "resource_type": "EmergencyEvent",
            "resource_id": evp.id,
            "safety_passed": evp.safety_clearance_passed,
        })

    resource_ids = [intersection_id] + controller_ids
    for log in (
        db.query(AuditLog)
        .filter(AuditLog.resource_id.in_(resource_ids), AuditLog.timestamp >= since)
        .all()
    ):
        events.append({
            "timestamp": _iso(log.timestamp),
            "kind": "AUDIT",
            "severity": "WARNING" if log.result in ("REJECTED", "FAILED") else "INFO",
            "title": f"{log.action} - {log.result}",
            "detail": f"by {log.actor_username}",
            "source": "AUDIT_LEDGER",
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
        })

    events.sort(key=lambda e: e["timestamp"] or "", reverse=True)
    trimmed = events[:limit]

    return {
        "intersection_id": intersection_id,
        "intersection_name": inter.name,
        "window_hours": hours,
        "event_count": len(trimmed),
        "total_in_window": len(events),
        "events": trimmed,
        "empty_reason": None if trimmed else "NO_RECORDED_EVENTS_IN_WINDOW",
    }


@router.get("/{intersection_id}/replay")
def get_junction_replay(
    intersection_id: str,
    minutes: int = Query(default=60, ge=5, le=10080),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stored telemetry and signal events over a window, for the time scrubber.

    Returns only samples that were actually recorded. Nothing is interpolated
    across gaps, and a window with too few samples is reported as insufficient
    rather than rendered as a trend.
    """
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    now = datetime.now(timezone.utc)
    since = _naive(now - timedelta(minutes=minutes))

    observations = (
        db.query(TrafficObservation)
        .filter(
            TrafficObservation.intersection_id == intersection_id,
            TrafficObservation.timestamp >= since,
        )
        .order_by(TrafficObservation.timestamp.asc())
        .all()
    )
    metrics = (
        db.query(TrafficMetric)
        .filter(
            TrafficMetric.intersection_id == intersection_id,
            TrafficMetric.timestamp >= since,
        )
        .order_by(TrafficMetric.timestamp.asc())
        .all()
    )

    controller_ids = [
        c.id for c in db.query(SignalController)
        .filter(SignalController.intersection_id == intersection_id).all()
    ]
    commands = (
        db.query(SignalCommand)
        .filter(
            SignalCommand.controller_id.in_(controller_ids),
            SignalCommand.issued_at >= since,
        )
        .order_by(SignalCommand.issued_at.asc())
        .all()
        if controller_ids else []
    )

    sample_count = len(metrics) or len(observations)
    sufficient = sample_count >= MIN_REPLAY_SAMPLES

    return {
        "intersection_id": intersection_id,
        "intersection_name": inter.name,
        "window_minutes": minutes,
        "window_start": _iso(since),
        "window_end": now.isoformat(),
        "sufficient_data": sufficient,
        "sample_count": sample_count,
        "minimum_samples_required": MIN_REPLAY_SAMPLES,
        "empty_reason": None if sufficient else (
            "NO_STORED_TELEMETRY_FOR_THIS_WINDOW" if sample_count == 0
            else "INSUFFICIENT_SAMPLES_FOR_REPLAY"
        ),
        "interpolation": "NONE_GAPS_ARE_PRESERVED",
        "metrics": [
            {
                "timestamp": _iso(m.timestamp),
                "vehicle_count": m.vehicle_count,
                "flow_rate_vph": m.flow_rate_vph,
                "occupancy_pct": m.occupancy_pct,
                "avg_speed_kph": m.avg_speed_kph,
                "queue_length_meters": m.queue_length_meters,
                "traffic_pressure": m.traffic_pressure,
                "sample_window_sec": m.sample_window_sec,
                "data_quality": m.data_quality,
                "calculation_method": m.calculation_method,
                "provenance": m.provenance,
            }
            for m in metrics
        ],
        "observations": [
            {
                "timestamp": _iso(o.timestamp),
                "source": o.source,
                "vehicle_count": o.vehicle_count,
                "occupancy_pct": o.occupancy_pct,
                "avg_speed_kph": o.avg_speed_kph,
                "quality": o.quality,
            }
            for o in observations
        ],
        "signal_events": [
            {
                "timestamp": _iso(c.issued_at),
                "requested_phase": c.requested_phase,
                "command_type": c.command_type,
                "status": c.status,
                "safety_passed": c.safety_check_passed,
            }
            for c in commands
        ],
        "quality_thresholds_sec": {
            "fresh": DataQualityEngine.fresh_threshold_sec(),
            "aging": DataQualityEngine.aging_threshold_sec(),
            "stale": DataQualityEngine.stale_threshold_sec(),
        },
    }
