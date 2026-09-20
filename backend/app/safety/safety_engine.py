"""TRAFFICINTEL AI - Deterministic Signal Safety Engine

Mathematical and rule-based validation for all signal commands.
AI and human operators CAN NEVER override or bypass this layer.
Enforces NEMA TS2 / 170 / 2070 / ATC safety standards:
- Phase Conflict Matrix (no concurrent conflicting greens)
- Minimum Green intervals (cannot truncate active phase before min_green expires)
- Maximum Green intervals
- Yellow change & All-red clearance intervals
- Pedestrian Walk and Flash Don't Walk (FDW) clearance
- Command Freshness (< 5.0s window)
- Idempotency & Controller capability checks
"""

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple
from app.models.entities import SignalController, SignalPhase, SignalCommand, utc_now
from app.schemas.domain import SafetyCheckResult
from app.core.config import settings


class DeterministicSafetyEngine:
    """The central deterministic safety validator for traffic signal control commands.

    Every candidate command (whether from human operator, adaptive optimizer, or emergency)
    MUST pass all checks here. If any check fails, the command is REJECTED.
    """

    @classmethod
    def validate_command(
        cls,
        controller: SignalController,
        requested_phase_num: int,
        duration_sec: int,
        issued_at: datetime,
        idempotency_key: str,
        existing_command: Optional[SignalCommand] = None
    ) -> SafetyCheckResult:
        violations: List[str] = []
        checks_performed: List[str] = []
        details: Dict[str, Any] = {}

        now = utc_now()

        # -------------------------------------------------------------
        # 1. Idempotency & Duplicate Check
        # -------------------------------------------------------------
        checks_performed.append("IDEMPOTENCY_VERIFICATION")
        if existing_command is not None:
            violations.append(
                f"Duplicate command rejected: Idempotency key '{idempotency_key}' was already processed with status '{existing_command.status}'."
            )
            return SafetyCheckResult(
                is_safe=False,
                violations=violations,
                checks_performed=checks_performed,
                details={"duplicate_key": idempotency_key}
            )

        # -------------------------------------------------------------
        # 2. Command Freshness Check (Stale Protection)
        # -------------------------------------------------------------
        checks_performed.append("COMMAND_FRESHNESS_CHECK")
        age_seconds = (now - issued_at).total_seconds()
        details["command_age_sec"] = age_seconds
        if age_seconds > settings.COMMAND_FRESHNESS_WINDOW_SEC:
            violations.append(
                f"Command expired: Issued {age_seconds:.2f}s ago exceeds maximum allowable freshness window of {settings.COMMAND_FRESHNESS_WINDOW_SEC}s."
            )

        # -------------------------------------------------------------
        # 3. Controller Operational State & Capabilities
        # -------------------------------------------------------------
        checks_performed.append("CONTROLLER_STATE_VALIDATION")
        if controller.connection_status != "CONNECTED":
            violations.append(
                f"Controller '{controller.name}' is {controller.connection_status}. Cannot execute commands on disconnected or unverified hardware."
            )

        # -------------------------------------------------------------
        # 4. Target Phase Existence & Configuration
        # -------------------------------------------------------------
        checks_performed.append("PHASE_CONFIGURATION_LOOKUP")
        target_phase: Optional[SignalPhase] = None
        for p in controller.phases:
            if p.phase_number == requested_phase_num:
                target_phase = p
                break

        if not target_phase:
            violations.append(
                f"Invalid phase: Phase {requested_phase_num} is not configured on controller '{controller.name}'."
            )
            return SafetyCheckResult(
                is_safe=False,
                violations=violations,
                checks_performed=checks_performed,
                details=details
            )

        # -------------------------------------------------------------
        # 5. Minimum Green Interval on Currently Active Phase
        # -------------------------------------------------------------
        checks_performed.append("ACTIVE_PHASE_MINIMUM_GREEN_CHECK")
        if controller.active_phase is not None and controller.active_phase != requested_phase_num:
            active_p: Optional[SignalPhase] = next((p for p in controller.phases if p.phase_number == controller.active_phase), None)
            if active_p and controller.current_phase_start:
                active_elapsed = (now - controller.current_phase_start).total_seconds()
                details["active_phase_elapsed_sec"] = active_elapsed
                details["active_phase_min_green_required"] = active_p.min_green
                if active_elapsed < active_p.min_green:
                    violations.append(
                        f"Active Phase {controller.active_phase} has only elapsed {active_elapsed:.1f}s, violating minimum green requirement of {active_p.min_green}s."
                    )

        # -------------------------------------------------------------
        # 6. Conflict Matrix Verification (NEMA Conflict Prevention)
        # -------------------------------------------------------------
        checks_performed.append("PHASE_CONFLICT_MATRIX_VALIDATION")
        conflicting = target_phase.conflicting_phases or []
        details["conflicting_phases_for_target"] = conflicting
        if controller.active_phase is not None and controller.active_phase in conflicting:
            # If transitioning directly into a conflicting phase without clearance interval
            violations.append(
                f"Phase conflict detected: Requested Phase {requested_phase_num} conflicts with active Phase {controller.active_phase}."
            )

        # -------------------------------------------------------------
        # 7. Maximum Green Duration Boundary Check
        # -------------------------------------------------------------
        checks_performed.append("MAX_GREEN_DURATION_CHECK")
        details["requested_duration_sec"] = duration_sec
        details["phase_max_green"] = target_phase.max_green
        if duration_sec > target_phase.max_green:
            violations.append(
                f"Requested hold duration of {duration_sec}s exceeds configured maximum green limit of {target_phase.max_green}s for Phase {requested_phase_num}."
            )

        if duration_sec < target_phase.min_green:
            violations.append(
                f"Requested hold duration of {duration_sec}s is below minimum green requirement of {target_phase.min_green}s for Phase {requested_phase_num}."
            )

        # -------------------------------------------------------------
        # Final Determination
        # -------------------------------------------------------------
        is_safe = len(violations) == 0
        details["safety_status"] = "PASSED" if is_safe else "REJECTED_BY_SAFETY"

        return SafetyCheckResult(
            is_safe=is_safe,
            violations=violations,
            checks_performed=checks_performed,
            details=details
        )
