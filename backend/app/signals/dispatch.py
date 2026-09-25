"""TRAFFICINTEL AI - The Single Path to a Signal Controller

Every instruction that changes what a signal controller does passes through
this module: operator phase holds, emergency preemption (manual and AVL),
transit signal priority, and coordination timing plans. It is the only code in
the platform that calls an adapter's `send_command` or `write_timing_plan`.

Before this module existed the command path lived inline in one endpoint, and
the emergency preemption endpoint validated calls with the Safety Engine and
then recorded them as EXECUTED without ever sending anything to the hardware.
One shared dispatcher makes that impossible to repeat: a caller cannot obtain a
"dispatched" result without the Safety Engine having passed it and the adapter
having been asked.

The sequence is fixed and not configurable by callers:

    1. Deterministic Safety Engine validation.
    2. A SignalCommand row, REJECTED or PENDING, written either way.
    3. Rejected: an audit entry, and stop. Nothing reaches the hardware.
    4. Otherwise the adapter is asked; its acknowledgement is recorded.
    5. The controller is re-read, and what it is *actually* displaying is
       recorded beside what was requested - never assumed from the request.
    6. An audit entry whose result is the real outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.models.entities import AuditLog, SignalCommand, SignalController, utc_now
from app.providers.controller_provider import get_controller_adapter
from app.providers.controller_sync import apply_post_command_reading
from app.safety.safety_engine import DeterministicSafetyEngine
from app.schemas.domain import SafetyCheckResult

EXECUTED = "EXECUTED"
REJECTED = "REJECTED"
FAILED = "FAILED"


@dataclass
class DispatchResult:
    """The outcome of one attempt to change what a controller does."""

    command: SignalCommand
    safety: SafetyCheckResult
    status: str
    acknowledgement: Optional[str] = None
    post_state: Dict[str, Any] = field(default_factory=dict)
    effect_observed: bool = False
    readback: Optional[Dict[str, Any]] = None

    @property
    def executed(self) -> bool:
        return self.status == EXECUTED


def _adapter_for(controller: SignalController):
    return get_controller_adapter(
        controller.vendor, controller.model, controller.protocol,
        controller.ip_address, controller.port,
    )


class SignalCommandDispatcher:
    """Validates, records, dispatches, reads back and audits."""

    @classmethod
    def dispatch_phase_hold(
        cls,
        db: Session,
        controller: SignalController,
        requested_phase: int,
        duration_sec: int,
        idempotency_key: str,
        actor_id: Optional[str],
        actor_name: str,
        command_type: str = "PHASE_HOLD",
        origin: str = "OPERATOR",
        context: Optional[Dict[str, Any]] = None,
        issued_at: Optional[datetime] = None,
    ) -> DispatchResult:
        """A phase hold, from any origin, through the one validated path."""
        issued_at = issued_at or utc_now()
        existing = (
            db.query(SignalCommand)
            .filter(SignalCommand.idempotency_key == idempotency_key)
            .first()
        )
        safety = DeterministicSafetyEngine.validate_command(
            controller=controller,
            requested_phase_num=requested_phase,
            duration_sec=duration_sec,
            issued_at=issued_at,
            idempotency_key=idempotency_key,
            existing_command=existing,
        )

        record = SignalCommand(
            idempotency_key=idempotency_key,
            controller_id=controller.id,
            requested_phase=requested_phase,
            command_type=command_type,
            duration_sec=duration_sec,
            safety_check_passed=safety.is_safe,
            safety_report=safety.model_dump(),
            status=REJECTED if not safety.is_safe else "PENDING",
            operator_id=actor_id,
            issued_at=issued_at,
            expires_at=issued_at + timedelta(seconds=duration_sec),
        )
        db.add(record)
        db.flush()

        if not safety.is_safe:
            db.add(AuditLog(
                actor_id=actor_id,
                actor_username=actor_name,
                action="SIGNAL_COMMAND_REJECTED_BY_SAFETY",
                resource_type="SignalCommand",
                resource_id=record.id,
                result=REJECTED,
                details={**safety.model_dump(), "origin": origin, "command_type": command_type,
                         **(context or {})},
            ))
            db.commit()
            return DispatchResult(command=record, safety=safety, status=REJECTED)

        adapter = _adapter_for(controller)
        success, ack_msg, payload = adapter.send_command(requested_phase, duration_sec)

        if success:
            post_state, effect_observed = apply_post_command_reading(
                controller, adapter, requested_phase, db=db
            )
            record.status = EXECUTED
            record.controller_acknowledged_at = utc_now()
            record.response_payload = {
                "acknowledgement": payload,
                "post_command_state": post_state,
                "effect_observed": effect_observed,
            }
        else:
            post_state = {"effect_verification": "NOT_ATTEMPTED_COMMAND_FAILED"}
            effect_observed = False
            record.status = FAILED
            record.response_payload = {"error": ack_msg, "details": payload}

        db.add(AuditLog(
            actor_id=actor_id,
            actor_username=actor_name,
            action="SIGNAL_COMMAND_ISSUED",
            resource_type="SignalCommand",
            resource_id=record.id,
            result=record.status,
            details={
                "controller_id": controller.id,
                "phase": requested_phase,
                "duration": duration_sec,
                "ack": ack_msg,
                "origin": origin,
                "command_type": command_type,
                "effect_verification": post_state.get("effect_verification"),
                "observed_active_phase": post_state.get("observed_active_phase"),
                **(context or {}),
            },
        ))
        db.commit()

        return DispatchResult(
            command=record, safety=safety, status=record.status,
            acknowledgement=ack_msg, post_state=post_state,
            effect_observed=effect_observed,
        )

    @classmethod
    def dispatch_timing_plan(
        cls,
        db: Session,
        controller: SignalController,
        plan: Dict[str, Any],
        idempotency_key: str,
        actor_id: Optional[str],
        actor_name: str,
        origin: str = "COORDINATION",
        context: Optional[Dict[str, Any]] = None,
        issued_at: Optional[datetime] = None,
    ) -> DispatchResult:
        """A coordination timing plan (cycle, splits, offset), same sequence.

        Recorded as a SignalCommand of type TIMING_PLAN so that post-change
        verification can measure whether the plan helped, exactly as it can
        for a phase hold. `requested_phase` holds the coordinated phase and
        `duration_sec` the cycle length.
        """
        issued_at = issued_at or utc_now()
        existing = (
            db.query(SignalCommand)
            .filter(SignalCommand.idempotency_key == idempotency_key)
            .first()
        )
        safety = DeterministicSafetyEngine.validate_timing_plan(
            controller=controller,
            cycle_sec=plan["cycle_sec"],
            offset_sec=plan["offset_sec"],
            splits=plan["splits"],
            coord_phase=plan["coord_phase"],
            issued_at=issued_at,
            idempotency_key=idempotency_key,
            existing_command=existing,
        )

        record = SignalCommand(
            idempotency_key=idempotency_key,
            controller_id=controller.id,
            requested_phase=plan["coord_phase"],
            command_type="TIMING_PLAN",
            duration_sec=plan["cycle_sec"],
            safety_check_passed=safety.is_safe,
            safety_report=safety.model_dump(),
            status=REJECTED if not safety.is_safe else "PENDING",
            operator_id=actor_id,
            issued_at=issued_at,
            # A timing plan does not lapse like a hold; expiry records the end of
            # the first full cycle under it, the earliest it can be observed.
            expires_at=issued_at + timedelta(seconds=plan["cycle_sec"]),
        )
        db.add(record)
        db.flush()

        if not safety.is_safe:
            db.add(AuditLog(
                actor_id=actor_id, actor_username=actor_name,
                action="TIMING_PLAN_REJECTED_BY_SAFETY",
                resource_type="SignalCommand", resource_id=record.id,
                result=REJECTED,
                details={**safety.model_dump(), "origin": origin, "plan": plan, **(context or {})},
            ))
            db.commit()
            return DispatchResult(command=record, safety=safety, status=REJECTED)

        adapter = _adapter_for(controller)
        success, ack_msg, payload = adapter.write_timing_plan(
            pattern_number=plan.get("pattern_number", 1),
            cycle_sec=plan["cycle_sec"],
            offset_sec=plan["offset_sec"],
            splits=plan["splits"],
            coord_phase=plan["coord_phase"],
        )

        readback = payload.get("readback") if isinstance(payload, dict) else None
        # The plan is only "applied" when the controller reports back the
        # values that were written. An acknowledged SET whose read-back differs
        # is recorded as FAILED, not as a success with a footnote.
        if success and readback and readback.get("matches_request"):
            record.status = EXECUTED
            record.controller_acknowledged_at = utc_now()
        else:
            record.status = FAILED
        record.response_payload = {"acknowledgement": ack_msg, "details": payload}

        db.add(AuditLog(
            actor_id=actor_id, actor_username=actor_name,
            action="TIMING_PLAN_WRITTEN",
            resource_type="SignalCommand", resource_id=record.id,
            result=record.status,
            details={
                "controller_id": controller.id, "ack": ack_msg, "origin": origin,
                "plan": plan, "readback": readback, **(context or {}),
            },
        ))
        db.commit()

        return DispatchResult(
            command=record, safety=safety, status=record.status,
            acknowledgement=ack_msg, readback=readback,
            effect_observed=bool(readback and readback.get("matches_request")),
        )
