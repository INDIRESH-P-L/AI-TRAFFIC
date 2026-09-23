"""TRAFFICINTEL AI - Copilot Endpoints

Grounded operations assistant. Answers come from tool calls against real
stored state, every claim carries a citation, and a question the records
cannot answer gets a refusal rather than a plausible guess.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.copilot import tools as tool_registry
from app.copilot.copilot_service import GroundedCopilotService
from app.copilot.copilot_v2 import GroundedCopilotV2, conversation_memory
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User
from app.schemas.domain import CopilotQuery, CopilotResponse

router = APIRouter(prefix="/copilot", tags=["AI Copilot"])


@router.post("/query", response_model=CopilotResponse)
def query_copilot(
    data: CopilotQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Legacy single-shot endpoint, kept for existing console callers."""
    return GroundedCopilotService.answer_query(
        db=db,
        query=data.query,
        intersection_id=data.intersection_id
    )


@router.post("/ask")
def ask_copilot(
    data: CopilotQuery,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Copilot 2.0: tool-calling, mandatory citations, session memory.

    The session is keyed per operator, so one operator's conversation context
    never leaks into another's.
    """
    session_id = "user:{}".format(current_user.username)
    return GroundedCopilotV2.answer(
        db=db,
        question=data.query,
        session_id=session_id,
        intersection_id=data.intersection_id,
    )


@router.get("/tools")
def list_tools(current_user: User = Depends(get_current_user)):
    """The tools the Copilot can call, and what each returns."""
    return {
        "tools": tool_registry.describe_tools(),
        "contract": [
            "A citation points at something checkable: a record id and timestamp, "
            "or a standard and section.",
            "A tool that finds nothing returns NO_DATA with a reason, never an "
            "empty result that could be read as zero.",
            "No tool computes a new number. Tools retrieve; the analytics and "
            "safety modules compute.",
        ],
    }


@router.get("/session")
def get_session(
    current_user: User = Depends(get_current_user)
):
    """This operator's conversation memory."""
    session_id = "user:{}".format(current_user.username)
    session = conversation_memory.get(session_id)
    return {
        "session_id": session_id,
        "turn_count": len(session["turns"]),
        "focus_intersection_id": session["focus_intersection_id"],
        "turns": session["turns"],
        "memory_policy": conversation_memory.stats(),
    }


@router.delete("/session")
def clear_session(
    current_user: User = Depends(get_current_user)
):
    """Forgets this operator's conversation."""
    session_id = "user:{}".format(current_user.username)
    cleared = conversation_memory.clear(session_id)
    return {"session_id": session_id, "cleared": cleared}
