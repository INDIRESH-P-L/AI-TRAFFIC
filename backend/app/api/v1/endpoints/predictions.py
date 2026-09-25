"""TRAFFICINTEL AI - Traffic Prediction & Model Registry Endpoints

Short-horizon forecasting from stored telemetry (see analytics/forecasting.py).
A forecast is offered only when a model fitted to this junction's own history
has demonstrated skill over naive persistence in a rolling-origin backtest;
otherwise the response is INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST with the
reason, and - where a model was fitted - that model and its measured error.
Never generates synthetic forecast lines.
"""

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.analytics.forecasting import ShortHorizonForecaster
from app.models.entities import User, AIModel

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.get("/models")
def list_ai_models(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    models = db.query(AIModel).all()
    return {
        "status": "CONFIGURED" if models else "AI_MODELS_NOT_CONFIGURED",
        "models": models
    }


@router.get("/forecast/{intersection_id}")
def get_traffic_forecast(
    intersection_id: str,
    metric: str = Query(default="flow_rate_vph", description="flow_rate_vph, occupancy_pct or avg_speed_kph"),
    bin_minutes: int = Query(default=15, description="5, 15 or 60"),
    horizon_bins: int = Query(default=4, ge=1, le=8),
    history_days: int = Query(default=7, ge=1, le=30),
    as_of: Optional[datetime] = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Short-horizon ARIMA(p,d,0) forecast from this junction's stored history.

    Refuses with INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST when the history is too
    short or gapped, when the latest data is too old, or when the fitted model's
    measured backtest skill over naive persistence is too low - in which case
    the refusal reports that model and its error. Never draws a line it has not
    earned.
    """
    try:
        result = ShortHorizonForecaster.forecast(
            db, intersection_id, metric=metric, bin_minutes=bin_minutes,
            horizon_bins=horizon_bins, history_days=history_days, as_of=as_of,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if result.get("forecast_status") == "NOT_FOUND":
        raise HTTPException(status_code=404, detail="Intersection not found")
    return result
