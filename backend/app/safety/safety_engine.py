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

    # ==================================================================
    # Coordination timing plans
    # ==================================================================

    #: Protocols with an implemented channel for writing timing plans. A
    #: controller reached over anything else cannot receive one, and the engine
    #: says so rather than letting the adapter fail later.
    TIMING_PLAN_PROTOCOLS = {"NTCIP_1202"}
    TIMING_PLAN_MIN_CYCLE_SEC = 30
    TIMING_PLAN_MAX_CYCLE_SEC = 180

    @classmethod
    def validate_timing_plan(
        cls,
        controller: SignalController,
        cycle_sec: int,
        offset_sec: int,
        splits: Dict[Any, Any],
        coord_phase: int,
        issued_at: datetime,
        idempotency_key: str,
        existing_command: Optional[SignalCommand] = None,
    ) -> SafetyCheckResult:
        """Validates a coordination plan (cycle, per-phase splits, offset).

        A phase hold asks "may this phase stay green now?". A timing plan asks
        something larger: "is every cycle this controller will run under this
        plan safe?". So beyond readability and freshness it checks the
        structure of the plan - that each split leaves room for minimum green
        and full clearance, that each ring accounts for exactly one cycle, and
        that both rings reach every barrier at the same instant. A plan failing
        the last check would have ring 1 cross into the next barrier group while
        ring 2 is still green in the previous one: two conflicting movements
        green together.
        """
        ledger = _Ledger()
        now = utc_now()
        splits = {int(phase): int(value) for phase, value in (splits or {}).items()}
        ledger.details.update({
            "cycle_sec": cycle_sec, "offset_sec": offset_sec,
            "splits": splits, "coord_phase": coord_phase,
        })

        # 1. Idempotency
        if existing_command is not None:
            ledger.record(
                "IDEMPOTENCY_VERIFICATION", "Duplicate command", False,
                "Duplicate timing plan rejected: idempotency key '{}' was already processed "
                "with status '{}'.".format(idempotency_key, existing_command.status),
            )
            return ledger.result()
        ledger.record("IDEMPOTENCY_VERIFICATION", "Duplicate command", True,
                      "This timing plan has not been issued before.")

        # 2. Freshness
        age = (now - _as_utc(issued_at)).total_seconds()
        window = settings.COMMAND_FRESHNESS_WINDOW_SEC
        fresh = age <= window
        ledger.record(
            "COMMAND_FRESHNESS_CHECK", "Command freshness", fresh,
            "Plan age {:.2f}s is within the {}s window.".format(age, window) if fresh else
            "Plan expired: issued {:.2f}s ago, beyond the {}s freshness window.".format(age, window),
            standard="Stale-command protection",
        )

        # 3. Readability
        readable = controller.connection_status == "CONNECTED"
        ledger.record(
            "CONTROLLER_STATE_VALIDATION", "Controller state readable", readable,
            "Controller '{}' has a live protocol session.".format(controller.name) if readable else
            "Controller '{}' is {}. A timing plan cannot be written to hardware whose state "
            "cannot be read and verified.".format(controller.name, controller.connection_status),
        )

        # 4. Capability
        capable = (controller.protocol or "").upper() in cls.TIMING_PLAN_PROTOCOLS
        ledger.record(
            "CONTROLLER_CAPABILITY_CHECK", "Timing plan channel", capable,
            "Protocol {} has an implemented timing-plan channel.".format(controller.protocol)
            if capable else
            "Protocol {} has no implemented channel for writing timing plans; only {} do.".format(
                controller.protocol, sorted(cls.TIMING_PLAN_PROTOCOLS)),
        )

        # 5. Cycle bounds
        low, high = cls.TIMING_PLAN_MIN_CYCLE_SEC, cls.TIMING_PLAN_MAX_CYCLE_SEC
        cycle_ok = low <= cycle_sec <= high
        ledger.record(
            "CYCLE_LENGTH_BOUNDS", "Cycle length within bounds", cycle_ok,
            "Cycle {}s is {} [{}, {}]s.".format(cycle_sec, "within" if cycle_ok else "outside", low, high),
        )

        # 6. Offset range
        offset_ok = 0 <= offset_sec < max(cycle_sec, 1)
        ledger.record(
            "OFFSET_RANGE_CHECK", "Offset within cycle", offset_ok,
            "Offset {}s lies within the {}s cycle.".format(offset_sec, cycle_sec) if offset_ok else
            "Offset {}s must lie in [0, {}).".format(offset_sec, cycle_sec),
        )

        # 7. Every configured phase has a split, and every split is configured.
        configured = {p.phase_number: p for p in controller.phases}
        unknown = sorted(set(splits) - set(configured))
        unserved = sorted(set(configured) - set(splits))
        phases_ok = not unknown and not unserved
        ledger.record(
            "PHASE_CONFIGURATION_LOOKUP", "Splits match configured phases", phases_ok,
            "Every configured phase has a split and no split names an unknown phase."
            if phases_ok else
            "Split(s) for unconfigured phase(s): {}. Configured phase(s) that would never be "
            "served: {}.".format(unknown or "none", unserved or "none"),
        )
        if unknown:
            # The structural checks below would be meaningless.
            return ledger.result()

        coord_ok = coord_phase in splits
        ledger.record(
            "COORDINATED_PHASE_CHECK", "Coordinated phase present", coord_ok,
            "Coordinated phase {} has a split.".format(coord_phase) if coord_ok else
            "Coordinated phase {} has no split in this plan.".format(coord_phase),
        )

        # 8. Each split leaves room for minimum green and full clearance.
        short, long_green, ped_short = [], [], []
        for number, split in sorted(splits.items()):
            phase = configured[number]
            clearance = (phase.yellow_change or 0) + (phase.red_clearance or 0)
            green = split - clearance
            if split < (phase.min_green or 0) + clearance:
                short.append("phase {}: {}s < {}s min green + {}s clearance".format(
                    number, split, phase.min_green, clearance))
            if green > (phase.max_green or 0):
                long_green.append("phase {}: green {}s > {}s max".format(number, green, phase.max_green))
            ped = (phase.ped_walk or 0) + (phase.ped_clearance or 0)
            # Conservative MUTCD 4E.06 reading: walk and pedestrian clearance
            # complete before the vehicle yellow begins.
            if ped and green < ped:
                ped_short.append("phase {}: green {}s < {}s walk + ped clearance".format(number, green, ped))
        ledger.record(
            "SPLIT_CLEARANCE_CHECK", "Splits allow minimum green and clearance", not short,
            "Every split covers minimum green, yellow change and all-red clearance."
            if not short else "Split too short - " + "; ".join(short),
            standard="MUTCD 4D.26 / NEMA TS 2 minimum green and clearance",
        )
        ledger.record(
            "MAX_GREEN_DURATION_CHECK", "Split green within maximum green", not long_green,
            "No split's green exceeds the phase's configured maximum green."
            if not long_green else "Green too long - " + "; ".join(long_green),
            standard="NEMA TS 2 maximum green",
        )
        ledger.record(
            "PEDESTRIAN_CLEARANCE_CHECK", "Pedestrian walk and clearance fit", not ped_short,
            "Every split's green accommodates its configured walk and pedestrian clearance."
            if not ped_short else "Pedestrian timing does not fit - " + "; ".join(ped_short),
            standard="MUTCD 4E.06 pedestrian intervals",
        )

        # 9. Each ring accounts for exactly one cycle.
        rings: Dict[int, int] = {}
        for number, split in splits.items():
            ring = configured[number].ring
            rings[ring] = rings.get(ring, 0) + split
        bad_rings = {ring: total for ring, total in rings.items() if total != cycle_sec}
        ledger.record(
            "RING_SUM_CHECK", "Each ring sums to the cycle", not bad_rings,
            "Ring totals {} each equal the {}s cycle.".format(rings, cycle_sec) if not bad_rings else
            "Ring totals {} do not equal the {}s cycle.".format(bad_rings, cycle_sec),
            standard="NEMA TS 2 dual-ring structure",
        )

        # 10. Both rings reach every barrier at the same instant.
        by_barrier: Dict[int, Dict[int, int]] = {}
        for number, split in splits.items():
            phase = configured[number]
            group = by_barrier.setdefault(phase.barrier, {})
            group[phase.ring] = group.get(phase.ring, 0) + split
        misaligned = {b: t for b, t in by_barrier.items() if len(set(t.values())) > 1}
        ledger.record(
            "BARRIER_ALIGNMENT_CHECK", "Rings cross each barrier together", not misaligned,
            "Both rings spend the same time in every barrier group, so neither crosses a "
            "barrier while the other is still green in the previous group."
            if not misaligned else
            "Barrier group totals differ between rings: {}. One ring would cross into the next "
            "barrier group while the other is still green in the previous one.".format(misaligned),
            standard="NEMA TS 2 dual-ring barrier",
        )

        # 11. Phases that run concurrently must not be declared conflicting.
        concurrent_conflicts = []
        phases = list(configured.values())
        for a in phases:
            for b in phases:
                if a.phase_number < b.phase_number and a.barrier == b.barrier and a.ring != b.ring:
                    if (b.phase_number in (a.conflicting_phases or [])
                            or a.phase_number in (b.conflicting_phases or [])):
                        concurrent_conflicts.append((a.phase_number, b.phase_number))
        ledger.record(
            "PHASE_CONFLICT_MATRIX_VALIDATION", "Concurrent phases are compatible", not concurrent_conflicts,
            "No pair of phases this plan runs concurrently is declared conflicting."
            if not concurrent_conflicts else
            "Phase pair(s) {} share a barrier in opposite rings, so this plan would run them "
            "together, but they are configured as conflicting.".format(concurrent_conflicts),
            standard="NEMA TS 2 dual-ring barrier conflict matrix",
        )

        return ledger.result()
