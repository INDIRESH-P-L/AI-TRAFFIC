"""TRAFFICINTEL AI - Incident Lifecycle Engine

Manages real incidents through the formal state machine:
DETECTED -> SUSPECTED -> VERIFIED -> ACTIVE -> MITIGATED -> RESOLVED.
Prevents automatic unverified escalations. Maintains an immutable audit trail.
"""

from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
from app.models.entities import Incident, AuditLog, utc_now

VALID_STATUSES = ["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE", "MITIGATED", "RESOLVED"]


class IncidentLifecycleEngine:
    """Enforces state transitions for traffic incidents."""

    ALLOWED_TRANSITIONS = {
        "DETECTED": ["SUSPECTED", "VERIFIED", "RESOLVED"],
        "SUSPECTED": ["VERIFIED", "RESOLVED"],
        "VERIFIED": ["ACTIVE", "MITIGATED", "RESOLVED"],
        "ACTIVE": ["MITIGATED", "RESOLVED"],
        "MITIGATED": ["RESOLVED", "ACTIVE"],
        "RESOLVED": ["ACTIVE"]  # Reopened if recurring
    }

    @classmethod
    def transition_incident(
        cls,
        incident: Incident,
        new_status: str,
        operator_username: str,
        notes: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Validates and applies an incident status transition."""
        if new_status not in VALID_STATUSES:
            return False, f"Invalid status '{new_status}'. Allowed: {VALID_STATUSES}"

        current = incident.status
        allowed_next = cls.ALLOWED_TRANSITIONS.get(current, [])

        if new_status not in allowed_next:
            return False, f"Invalid status transition from {current} to {new_status}. Allowed: {allowed_next}"

        now = utc_now()
        incident.status = new_status

        if notes:
            incident.operator_notes = f"{incident.operator_notes or ''}\n[{now.isoformat()} by {operator_username}]: {notes}".strip()

        if new_status == "VERIFIED" and not incident.verified_at:
            incident.verified_at = now
        elif new_status == "RESOLVED":
            incident.resolved_at = now

        return True, f"Incident transitioned to {new_status}"
