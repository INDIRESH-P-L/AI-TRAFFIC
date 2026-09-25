"""TRAFFICINTEL AI - Traffic Signal Controller & Safety-Validated Command Endpoints

Enforces the full mandatory safety chain:
Frontend -> Authenticated API -> Authorization -> Traffic Control Service -> Safety Validation -> Controller Capability Validation -> Signal Controller Adapter -> Real Controller -> Acknowledgement -> Audit Log.
"""

from typing import List
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import (
    User, SignalController, SignalPhase, SignalCommand, AuditLog, utc_now
)
from app.schemas.domain import (
    SignalControllerCreate,
    SignalControllerResponse,
    SignalCommandRequest,
    SignalCommandResponse,
    SignalCommandPreview,
    SafetyCheckResult,
)
from app.safety.safety_engine import DeterministicSafetyEngine
from app.signals.dispatch import SignalCommandDispatcher
from app.providers.controller_provider import get_controller_adapter
from app.providers.controller_sync import (
    apply_controller_reading,
    apply_post_command_reading,
)
from app.api.v1.websocket import ws_manager

router = APIRouter(prefix="/signals", tags=["Signal Control"])


@router.get("/controllers", response_model=List[SignalControllerResponse])
def list_controllers(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(SignalController).all()


@router.post("/controllers", response_model=SignalControllerResponse, status_code=status.HTTP_201_CREATED)
def create_controller(
    data: SignalControllerCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    ctrl = SignalController(
        intersection_id=data.intersection_id,
        name=data.name,
        vendor=data.vendor,
        model=data.model,
        protocol=data.protocol,
        ip_address=data.ip_address,
        port=data.port,
        cycle_length=data.cycle_length,
        connection_status="NOT_CONNECTED",
        control_mode="LOCAL_COORDINATED"
    )
    db.add(ctrl)
    db.flush()

    for p in data.phases:
        phase = SignalPhase(
            controller_id=ctrl.id,
            phase_number=p.phase_number,
            ring=p.ring,
            barrier=p.barrier,
            name=p.name,
            min_green=p.min_green,
            max_green=p.max_green,
            yellow_change=p.yellow_change,
            red_clearance=p.red_clearance,
            ped_walk=p.ped_walk,
            ped_clearance=p.ped_clearance,
            conflicting_phases=p.conflicting_phases
        )
        db.add(phase)

    # Audit
    audit = AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="CONFIG_SIGNAL_CONTROLLER",
        resource_type="SignalController",
        resource_id=ctrl.id,
        result="EXECUTED",
        details={"vendor": ctrl.vendor, "model": ctrl.model, "ip": ctrl.ip_address}
    )
    db.add(audit)

    db.commit()
    db.refresh(ctrl)
    return ctrl


@router.post("/controllers/{id}/test-connection")
def test_controller_connection(
    id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"]))
):
    ctrl = db.query(SignalController).filter(SignalController.id == id).first()
    if not ctrl:
        raise HTTPException(status_code=404, detail="Signal controller not found")

    adapter = get_controller_adapter(ctrl.vendor, ctrl.model, ctrl.protocol, ctrl.ip_address, ctrl.port)
    provenance = apply_controller_reading(ctrl, adapter, db=db)
    db.commit()

    return {
        "controller_id": ctrl.id,
        "name": ctrl.name,
        "protocol": ctrl.protocol,
        "connection_status": ctrl.connection_status,
        "state_readable": provenance["state_readable"],
        "state_unreadable_reason": provenance["state_unreadable_reason"],
        "observed_active_phase": provenance["observed_active_phase"],
        "health_details": provenance,
    }


@router.post("/commands/validate", response_model=SignalCommandPreview)
def validate_signal_command(
    cmd: SignalCommandRequest,
    refresh_state: bool = True,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Dry-run a command through the Safety Engine. Writes nothing.

    This is the preview step of the guided command workflow: the operator sees
    each rule's verdict before committing. It runs the identical validation the
    real command path runs - not a lookalike - so a preview that passes is a
    genuine statement about the command, subject only to state changing between
    preview and confirmation (which the freshness window bounds).

    `refresh_state` re-reads the controller first, so the preview reflects the
    phase the hardware is displaying now rather than the last stored reading.
    """
    controller = db.query(SignalController).filter(SignalController.id == cmd.controller_id).first()
    if not controller:
        raise HTTPException(status_code=404, detail="Signal controller not found")

    state_provenance = None
    if refresh_state:
        adapter = get_controller_adapter(
            controller.vendor, controller.model, controller.protocol,
            controller.ip_address, controller.port
        )
        state_provenance = apply_controller_reading(controller, adapter, db=db)
        db.commit()

    existing_cmd = db.query(SignalCommand).filter(
        SignalCommand.idempotency_key == cmd.idempotency_key
    ).first()

    issued_at = utc_now()
    safety_result = DeterministicSafetyEngine.validate_command(
        controller=controller,
        requested_phase_num=cmd.requested_phase,
        duration_sec=cmd.duration_sec,
        issued_at=issued_at,
        idempotency_key=cmd.idempotency_key,
        existing_command=existing_cmd,
    )

    return SignalCommandPreview(
        controller_id=controller.id,
        controller_name=controller.name,
        requested_phase=cmd.requested_phase,
        duration_sec=cmd.duration_sec,
        would_be_accepted=safety_result.is_safe,
        safety_report=safety_result,
        controller_state=state_provenance,
        evaluated_at=issued_at,
    )


@router.post("/commands", response_model=SignalCommandResponse)
async def issue_signal_command(
    cmd: SignalCommandRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"]))
):
    """Executes a signal command through the mandatory Deterministic Safety Engine.

    The validate / record / dispatch / read-back / audit sequence lives in
    SignalCommandDispatcher, which is the only path to a controller for every
    origin (operator, preemption, transit priority, coordination).
    """
    controller = db.query(SignalController).filter(SignalController.id == cmd.controller_id).first()
    if not controller:
        raise HTTPException(status_code=404, detail="Signal controller not found")

    result = SignalCommandDispatcher.dispatch_phase_hold(
        db,
        controller=controller,
        requested_phase=cmd.requested_phase,
        duration_sec=cmd.duration_sec,
        idempotency_key=cmd.idempotency_key,
        actor_id=current_user.id,
        actor_name=current_user.username,
        command_type=cmd.command_type,
        origin="OPERATOR",
    )

    if result.executed or result.status == "FAILED":
        # Broadcast real-time event to connected consoles
        await ws_manager.broadcast_event("signal.updated", {
            "controller_id": controller.id,
            "active_phase": controller.active_phase,
            "command_status": result.status,
            "effect_verification": result.post_state.get("effect_verification"),
            "state_readable": result.post_state.get("state_readable"),
        })

    return SignalCommandResponse(
        command_id=result.command.id,
        idempotency_key=cmd.idempotency_key,
        controller_id=controller.id,
        requested_phase=cmd.requested_phase,
        status=result.status,
        safety_check_passed=result.safety.is_safe,
        safety_report=result.safety,
        issued_at=result.command.issued_at,
        acknowledged_at=result.command.controller_acknowledged_at,
    )
