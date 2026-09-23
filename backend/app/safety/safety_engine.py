"""TRAFFICINTEL AI - Deterministic Signal Safety Engine

Mathematical and rule-based validation for all signal commands.
AI and human operators CAN NEVER override or bypass this layer.
Enforces NEMA TS2 / 170 / 2070 / ATC safety standards:
- Phase Conflict Matrix (no concurrent conflicting greens)
- Clearance Interval Occupancy (yellow change / all-red still occupies the box)
- Minimum Green intervals (cannot truncate active phase before min_green expires)
- Maximum Green intervals
- Command Freshness (< 5.0s window)
- Controller state readability, idempotency, and capability checks

Every check records a structured verdict, not just a failure string. The
operations console renders one row per rule with its own pass/fail state and a
plain-language explanation, so an operator sees *which* rule stopped a command
and why - not a wall of text after the fact.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.models.entities import SignalCommand, SignalController, SignalPhase, utc_now
from app.schemas.domain import SafetyCheck, SafetyCheckResult


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Normalises a timestamp to timezone-aware UTC.

    SQLAlchemy's DateTime column returns naive datetimes on SQLite (and on
    PostgreSQL columns declared without a timezone), while the engine works in
    aware UTC. Subtracting the two raises, which would have turned every
    minimum-green check on a persisted controller into a 500. Timestamps
    without a zone are interpreted as UTC, which is what the writers store.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class _Ledger:
    """Accumulates per-rule verdicts and derives the legacy summary fields."""

    def __init__(self) -> None:
        self.checks: List[SafetyCheck] = []
        self.details: Dict[str, Any] = {}

    def record(
        self,
        code: str,
        label: str,
        passed: bool,
        detail: str,
        standard: Optional[str] = None,
    ) -> None:
        self.checks.append(
            SafetyCheck(
                code=code, label=label, passed=passed, detail=detail, standard=standard
            )
        )

    def result(self) -> SafetyCheckResult:
        violations = [c.detail for c in self.checks if not c.passed]
        is_safe = not violations
        self.details["safety_status"] = "PASSED" if is_safe else "REJECTED_BY_SAFETY"
        return SafetyCheckResult(
            is_safe=is_safe,
            violations=violations,
            checks_performed=[c.code for c in self.checks],
            checks=self.checks,
            details=self.details,
        )


class DeterministicSafetyEngine:
    """The central deterministic safety validator for traffic signal control commands.

    Every candidate command (whether from human operator, adaptive optimizer, or
    emergency preemption) MUST pass all checks here. If any check fails, the
    command is REJECTED.
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
        ledger = _Ledger()
        now = utc_now()

        # -------------------------------------------------------------
        # 1. Idempotency & Duplicate Check
        # -------------------------------------------------------------
        if existing_command is not None:
            ledger.details["duplicate_key"] = idempotency_key
            ledger.record(
                "IDEMPOTENCY_VERIFICATION",
                "Duplicate command",
                False,
                f"Duplicate command rejected: Idempotency key '{idempotency_key}' was already "
                f"processed with status '{existing_command.status}'.",
            )
            return ledger.result()

        ledger.record(
            "IDEMPOTENCY_VERIFICATION",
            "Duplicate command",
            True,
            "This command has not been issued before.",
        )

        # -------------------------------------------------------------
        # 2. Command Freshness Check (Stale Protection)
        # -------------------------------------------------------------
        age_seconds = (now - _as_utc(issued_at)).total_seconds()
        ledger.details["command_age_sec"] = age_seconds
        fresh = age_seconds <= settings.COMMAND_FRESHNESS_WINDOW_SEC
        ledger.record(
            "COMMAND_FRESHNESS_CHECK",
            "Command freshness",
            fresh,
            f"Command age {age_seconds:.2f}s is within the {settings.COMMAND_FRESHNESS_WINDOW_SEC}s window."
            if fresh else
            f"Command expired: Issued {age_seconds:.2f}s ago exceeds maximum allowable "
            f"freshness window of {settings.COMMAND_FRESHNESS_WINDOW_SEC}s.",
            standard="Stale-command protection",
        )

        # -------------------------------------------------------------
        # 3. Controller Operational State & Readability
        # -------------------------------------------------------------
        ledger.details["controller_connection_status"] = controller.connection_status
        if controller.connection_status == "REACHABLE":
            # The cabinet answers on its port but its phase state cannot be
            # read, so no conflict or minimum-green check can be grounded in
            # reality. Commanding blind is exactly what this engine prevents.
            ledger.record(
                "CONTROLLER_STATE_VALIDATION",
                "Controller state readable",
                False,
                f"Controller '{controller.name}' answers on the network but its phase state cannot be read "
                f"(no protocol session). Commands are refused while the current phase is unknown, because "
                f"conflict and minimum-green checks cannot be verified against real hardware state.",
            )
        elif controller.connection_status != "CONNECTED":
            ledger.record(
                "CONTROLLER_STATE_VALIDATION",
                "Controller state readable",
                False,
                f"Controller '{controller.name}' is {controller.connection_status}. "
                f"Cannot execute commands on disconnected or unverified hardware.",
            )
        else:
            ledger.record(
                "CONTROLLER_STATE_VALIDATION",
                "Controller state readable",
                True,
                f"Controller '{controller.name}' has a live protocol session and its phase state was read.",
            )

        # -------------------------------------------------------------
        # 4. Target Phase Existence & Configuration
        # -------------------------------------------------------------
        target_phase: Optional[SignalPhase] = next(
            (p for p in controller.phases if p.phase_number == requested_phase_num), None
        )

        if not target_phase:
            ledger.record(
                "PHASE_CONFIGURATION_LOOKUP",
                "Phase configured",
                False,
                f"Invalid phase: Phase {requested_phase_num} is not configured on controller '{controller.name}'.",
            )
            return ledger.result()

        ledger.record(
            "PHASE_CONFIGURATION_LOOKUP",
            "Phase configured",
            True,
            f"Phase {requested_phase_num} ({target_phase.name}) is configured on ring "
            f"{target_phase.ring}, barrier {target_phase.barrier}.",
        )

        # -------------------------------------------------------------
        # 5. Minimum Green Interval on Currently Active Phase
        # -------------------------------------------------------------
        min_green_passed = True
        min_green_detail = (
            "No other phase is currently green, so no minimum green interval would be truncated."
        )
        if controller.active_phase is not None and controller.active_phase != requested_phase_num:
            active_p = next(
                (p for p in controller.phases if p.phase_number == controller.active_phase), None
            )
            phase_start = _as_utc(controller.current_phase_start)
            if active_p and phase_start:
                active_elapsed = (now - phase_start).total_seconds()
                ledger.details["active_phase_elapsed_sec"] = active_elapsed
                ledger.details["active_phase_min_green_required"] = active_p.min_green
                if active_elapsed < active_p.min_green:
                    min_green_passed = False
                    min_green_detail = (
                        f"Active Phase {controller.active_phase} has only elapsed {active_elapsed:.1f}s, "
                        f"violating minimum green requirement of {active_p.min_green}s."
                    )
                else:
                    min_green_detail = (
                        f"Active Phase {controller.active_phase} has run {active_elapsed:.1f}s, "
                        f"satisfying its {active_p.min_green}s minimum green."
                    )
        ledger.record(
            "ACTIVE_PHASE_MINIMUM_GREEN_CHECK",
            "Minimum green on active phase",
            min_green_passed,
            min_green_detail,
            standard="MUTCD 4D.26 / NEMA TS 2 minimum green",
        )

        # -------------------------------------------------------------
        # 6. Conflict Matrix Verification (NEMA Conflict Prevention)
        # -------------------------------------------------------------
        conflicting = target_phase.conflicting_phases or []
        ledger.details["conflicting_phases_for_target"] = conflicting
        conflict_with_active = (
            controller.active_phase is not None and controller.active_phase in conflicting
        )
        ledger.record(
            "PHASE_CONFLICT_MATRIX_VALIDATION",
            "Phase conflict matrix",
            not conflict_with_active,
            f"Phase conflict detected: Requested Phase {requested_phase_num} conflicts with "
            f"active Phase {controller.active_phase}."
            if conflict_with_active else
            f"Phase {requested_phase_num} does not conflict with the phase currently displaying green.",
            standard="NEMA TS 2 dual-ring barrier conflict matrix",
        )

        # A phase in yellow change or all-red clearance still occupies the
        # intersection, and no phase reads green during that interval. Checking
        # only the green phase would approve a conflicting movement while the
        # opposing approach is still clearing.
        clearing = list(controller.clearing_phases or [])
        ledger.details["phases_in_clearance"] = clearing
        conflicting_in_clearance = [p for p in clearing if p in conflicting]
        ledger.record(
            "CLEARANCE_INTERVAL_CONFLICT_CHECK",
            "Clearance interval occupancy",
            not conflicting_in_clearance,
            f"Clearance conflict detected: Requested Phase {requested_phase_num} conflicts with "
            f"Phase(s) {conflicting_in_clearance} still in yellow change or all-red clearance. "
            f"The opposing approach has not finished clearing the intersection."
            if conflicting_in_clearance else
            (
                f"Phase(s) {clearing} are clearing but do not conflict with Phase {requested_phase_num}."
                if clearing else
                "No phase is in a yellow change or all-red clearance interval."
            ),
            standard="MUTCD 4D.26 clearance intervals",
        )

        # -------------------------------------------------------------
        # 7. Requested Duration Within the Phase's Green Envelope
        # -------------------------------------------------------------
        ledger.details["requested_duration_sec"] = duration_sec
        ledger.details["phase_max_green"] = target_phase.max_green
        ledger.details["phase_min_green"] = target_phase.min_green

        if duration_sec > target_phase.max_green:
            ledger.record(
                "MAX_GREEN_DURATION_CHECK",
                "Hold duration within green envelope",
                False,
                f"Requested hold duration of {duration_sec}s exceeds configured maximum green "
                f"limit of {target_phase.max_green}s for Phase {requested_phase_num}.",
                standard="NEMA TS 2 maximum green",
            )
        elif duration_sec < target_phase.min_green:
            ledger.record(
                "MAX_GREEN_DURATION_CHECK",
                "Hold duration within green envelope",
                False,
                f"Requested hold duration of {duration_sec}s is below minimum green requirement "
                f"of {target_phase.min_green}s for Phase {requested_phase_num}.",
                standard="NEMA TS 2 minimum green",
            )
        else:
            ledger.record(
                "MAX_GREEN_DURATION_CHECK",
                "Hold duration within green envelope",
                True,
                f"Requested {duration_sec}s sits within Phase {requested_phase_num}'s "
                f"{target_phase.min_green}-{target_phase.max_green}s green envelope.",
                standard="NEMA TS 2 green intervals",
            )

        return ledger.result()
