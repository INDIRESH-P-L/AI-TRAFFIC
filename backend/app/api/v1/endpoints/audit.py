"""TRAFFICINTEL AI - Audit Log Endpoints

Immutable operational action ledger.
Tracks operator commands, configuration changes, safety checks, and security events.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.entities import User, AuditLog
from app.schemas.domain import AuditLogResponse

router = APIRouter(prefix="/audit", tags=["Audit Log"])


@router.get("", response_model=List[AuditLogResponse])
def list_audit_logs(
    action: Optional[str] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action)
    return q.order_by(AuditLog.timestamp.desc()).limit(limit).all()
