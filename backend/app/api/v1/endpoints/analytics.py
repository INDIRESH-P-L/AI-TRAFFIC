"""TRAFFICINTEL AI - Operational Analytics Endpoints

Signal performance measures computed from stored observations and observed
signal state. Every measure reports its own sample size, its method, and — when
it cannot be produced — whether the problem is too little data or a missing
input entirely.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.analytics.performance import SignalPerformance
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import (
    Incident, Intersection, SignalStateLog, TrafficObservation, User,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary")
def get_analytics_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Network-wide totals, from stored records only."""
    total_observations = db.query(TrafficObservation).count()

    if total_observations == 0:
        return {
            "status": "NO_HISTORICAL_DATA_AVAILABLE",
            "message": (
                "Historical analytics become available once traffic sensor or camera "
                "observation feeds are connected."
            ),
            "data_completeness_pct": 0.0,
            "metrics": {
                "total_volume_logged": 0,
                "avg_speed_kph": None,
                "avg_delay_sec": None,
                "incidents_recorded": db.query(Incident).count(),
            },
            "provenance": {
                "source_period": "None",
                "calculation_method": "ZERO_OBSERVATIONS_LOGGED",
            },
        }

    avg_speed = (
        db.query(func.avg(TrafficObservation.avg_speed_kph))
        .filter(TrafficObservation.avg_speed_kph.isnot(None))
        .scalar()
    )
    total_volume = db.query(func.sum(TrafficObservation.vehicle_count)).scalar() or 0
    signal_logs = db.query(SignalStateLog).count()

    return {
        "status": "ANALYTICS_AVAILABLE",
        "metrics": {
            "total_volume_logged": int(total_volume),
            "avg_speed_kph": round(float(avg_speed), 1) if avg_speed else None,
            "incidents_recorded": db.query(Incident).count(),
            "observation_records_count": total_observations,
            "signal_state_readings": signal_logs,
        },
        "capability": {
            "signal_performance_measures": (
                "AVAILABLE" if signal_logs else "UNAVAILABLE_NO_SIGNAL_STATE_LOGGED"
            ),
            "detail": (
                "Arrival-on-green, split failures and progression need observed signal "
                "state. Connect an NTCIP 1202 controller to record it."
                if not signal_logs else
                "{} signal state readings are stored.".format(signal_logs)
            ),
        },
        "provenance": {
            "source_period": "Lifetime ingested telemetry",
            "calculation_method": "DATABASE_AGGREGATE_ARITHMETIC_MEAN",
        },
    }


@router.get("/performance/{intersection_id}")
def intersection_performance(
    intersection_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Full ATSPM-style performance report for one junction."""
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)

    report = SignalPerformance.intersection_report(db, intersection_id, start, end)
    report["intersection_name"] = inter.name
    report["window_hours"] = hours
    report["note"] = (
        "INSUFFICIENT_DATA means the right inputs exist but there are too few of "
        "them - widen the window. NOT_COMPUTABLE means a required input does not "
        "exist at all - connect a source; waiting will not help."
    )
    return report


@router.get("/performance/{intersection_id}/{measure}")
def single_measure(
    intersection_id: str,
    measure: str,
    hours: int = Query(default=24, ge=1, le=720),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """One performance measure, with its full method and sample size."""
    available = {
        "throughput": SignalPerformance.throughput,
        "occupancy": SignalPerformance.occupancy,
        "speed": SignalPerformance.average_speed,
        "delay": SignalPerformance.control_delay,
        "split-failures": SignalPerformance.split_failures,
        "arrival-on-green": SignalPerformance.arrival_on_green,
    }
    if measure not in available:
        raise HTTPException(
            status_code=404,
            detail="Unknown measure '{}'. Available: {}".format(
                measure, sorted(available)
            ),
        )

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    result = available[measure](db, intersection_id, start, end)
    result["measure"] = measure
    result["window_start"] = start.isoformat()
    result["window_end"] = end.isoformat()
    return result


@router.get("/time-of-day/{intersection_id}")
def time_of_day(
    intersection_id: str,
    days: int = Query(default=7, ge=1, le=90),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-hour profile. Hours with no samples are reported as such."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    profile = SignalPerformance.time_of_day_profile(db, intersection_id, start, end)
    profile["intersection_id"] = intersection_id
    profile["window_days"] = days
    return profile
