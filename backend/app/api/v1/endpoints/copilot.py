"""TRAFFICINTEL AI - Copilot Assistant Endpoints

Operational grounded Copilot. Uses only actual database telemetry and indexed engineering standards.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User
from app.schemas.domain import CopilotQuery, CopilotResponse
from app.copilot.copilot_service import GroundedCopilotService

router = APIRouter(prefix="/copilot", tags=["AI Copilot"])


@router.post("/query", response_model=CopilotResponse)
def query_copilot(
    data: CopilotQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return GroundedCopilotService.answer_query(
        db=db,
        query=data.query,
        intersection_id=data.intersection_id
    )
