"""TRAFFICINTEL AI - Traffic Prediction & Model Registry Endpoints

Handles traffic demand forecasting models and validation datasets.
If insufficient historical observations exist, explicitly states
'INSUFFICIENT DATA FOR RELIABLE FORECAST'. Never generates synthetic forecast lines.
"""

from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User, AIModel, Intersection, TrafficObservation

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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        raise HTTPException(status_code=404, detail="Intersection not found")

    # Check volume of real historical observations for this intersection
    obs_count = db.query(TrafficObservation).filter(TrafficObservation.intersection_id == intersection_id).count()

    # Minimum threshold of historical observations required for statistical forecasting (e.g. 100 observations)
    MIN_OBSERVATIONS_REQUIRED = 100

    if obs_count < MIN_OBSERVATIONS_REQUIRED:
        return {
            "intersection_id": intersection_id,
            "intersection_name": inter.name,
            "forecast_status": "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST",
            "historical_observations_count": obs_count,
            "observations_required_threshold": MIN_OBSERVATIONS_REQUIRED,
            "message": "Forecasting requires a minimum of 100 historical telemetry observations. No synthetic forecast will be generated.",
            "forecast_points": []
        }

    # Sufficient history exists, but no forecasting model has been trained and
    # registered against it yet. Reporting a model name and error metrics here
    # would be fabrication: no model has been fitted, so no MAE or RMSE has
    # been measured.
    return {
        "intersection_id": intersection_id,
        "intersection_name": inter.name,
        "forecast_status": "NO_FORECAST_MODEL_REGISTERED",
        "historical_observations_count": obs_count,
        "observations_required_threshold": MIN_OBSERVATIONS_REQUIRED,
        "message": (
            "Sufficient historical observations exist, but no trained forecasting model is "
            "registered for this intersection. Register and activate a model under "
            "/api/v1/predictions/models to produce forecasts."
        ),
        "model_used": None,
        "validation_metrics": None,
        "forecast_points": []
    }
