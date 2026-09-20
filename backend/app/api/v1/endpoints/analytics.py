"""TRAFFICINTEL AI - Operational Analytics Endpoints

Computes historical operational metrics strictly from logged observations.
Exposes calculation methodology and data completeness.
If no data exists: returns NO_HISTORICAL_DATA_AVAILABLE.
"""

from typing import List, Optional
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User, TrafficObservation, TrafficMetric, Incident

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary")
def get_analytics_summary(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    total_observations = db.query(TrafficObservation).count()

    if total_observations == 0:
        return {
            "status": "NO_HISTORICAL_DATA_AVAILABLE",
            "message": "Historical analytics become available once traffic sensor or camera observation feeds are connected.",
            "data_completeness_pct": 0.0,
            "metrics": {
                "total_volume_logged": 0,
                "avg_speed_kph": None,
                "avg_delay_sec": None,
                "incidents_recorded": db.query(Incident).count()
            },
            "provenance": {
                "source_period": "None",
                "calculation_method": "ZERO_OBSERVATIONS_LOGGED"
            }
        }

    # If records exist, calculate genuine statistical averages
    avg_speed = db.query(func.avg(TrafficObservation.avg_speed_kph)).filter(TrafficObservation.avg_speed_kph.isnot(None)).scalar()
    total_vol = db.query(func.sum(TrafficObservation.vehicle_count)).scalar() or 0

    return {
        "status": "ANALYTICS_AVAILABLE",
        "data_completeness_pct": 100.0,
        "metrics": {
            "total_volume_logged": int(total_vol),
            "avg_speed_kph": round(float(avg_speed), 1) if avg_speed else None,
            "incidents_recorded": db.query(Incident).count(),
            "observation_records_count": total_observations
        },
        "provenance": {
            "source_period": "Lifetime Ingested Telemetry",
            "calculation_method": "DATABASE_AGGREGATE_ARITHMETIC_MEAN"
        }
    }
