"""TRAFFICINTEL AI - Controller State Synchronisation

Translates an adapter reading into persisted `SignalController` state.

This module exists to keep one rule in one place: **the database records the
phase the controller reported, never the phase we asked for.** The safety
engine's minimum-green check reads `active_phase` and `current_phase_start`, so
writing an unverified value there would let a later command be validated
against a fiction.

Connection status vocabulary:

* `CONNECTED`     - a protocol session exists and phase state was read back.
* `REACHABLE`     - the cabinet answers on its port but no phase state can be
                    read. Commands are refused by the safety engine.
* `DISCONNECTED`  - configured and previously reachable, currently not.
* `NOT_CONNECTED` - never successfully contacted.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from app.models.entities import SignalController, SignalStateLog, utc_now
from app.providers.base import SignalControllerProvider

logger = logging.getLogger("trafficintel.providers.sync")

STATUS_CONNECTED = "CONNECTED"
STATUS_REACHABLE = "REACHABLE"
STATUS_DISCONNECTED = "DISCONNECTED"
STATUS_NOT_CONNECTED = "NOT_CONNECTED"


def _observed_phase(status: Dict[str, Any]) -> Optional[int]:
    """Lowest green phase the controller reported, or None if it reported none."""
    greens = status.get("green_phases")
    if not greens:
        return None
    return min(greens)


def apply_controller_reading(
    controller: SignalController,
    adapter: SignalControllerProvider,
    db=None,
) -> Dict[str, Any]:
    """Polls the adapter and writes the observed state onto the controller row.

    When a session is supplied, each readable poll also appends a row to
    `signal_state_logs`. That history is the raw material for every signal
    performance measure: arrival-on-green, split failures, progression and the
    corridor time-space diagram cannot be computed from a current-state
    snapshot. Unreadable polls append nothing, so a gap in the log is an
    honest record of a period nobody observed.

    Returns the raw status dict so callers can surface provenance to the
    operator. The caller is responsible for committing the session.
    """
    health = adapter.health_check()
    status = adapter.get_controller_status()

    now = utc_now()
    reachable = bool(health.get("online"))
    state_readable = bool(status.get("state_readable"))

    if reachable and state_readable:
        controller.connection_status = STATUS_CONNECTED
        controller.last_heartbeat = now
    elif reachable:
        controller.connection_status = STATUS_REACHABLE
        controller.last_heartbeat = now
    elif controller.connection_status in (STATUS_CONNECTED, STATUS_REACHABLE):
        controller.connection_status = STATUS_DISCONNECTED
    else:
        controller.connection_status = STATUS_NOT_CONNECTED

    if state_readable:
        observed = _observed_phase(status)
        # Only restart the phase clock when the displayed phase actually
        # changed; otherwise the minimum-green check would never mature.
        if observed != controller.active_phase:
            controller.active_phase = observed
            controller.current_phase_start = now if observed is not None else None
        # Phases still clearing the intersection. The safety engine treats
        # these as occupied: during a yellow interval nothing reads green, and
        # a conflict check that looked only at greens would wave a conflicting
        # movement through while traffic is still in the box.
        controller.clearing_phases = status.get("yellow_phases") or []
    else:
        # Unreadable state must not leave a stale phase looking live.
        controller.active_phase = None
        controller.current_phase_start = None
        controller.clearing_phases = None

    if state_readable and db is not None:
        db.add(SignalStateLog(
            controller_id=controller.id,
            intersection_id=controller.intersection_id,
            timestamp=now,
            green_phases=status.get("green_phases"),
            yellow_phases=status.get("yellow_phases"),
            red_phases=status.get("red_phases"),
            source="{}_POLL".format(status.get("protocol") or "UNKNOWN"),
            read_latency_ms=health.get("latency_ms"),
        ))

    return {
        "connection_status": controller.connection_status,
        "state_readable": state_readable,
        "state_unreadable_reason": status.get("state_unreadable_reason"),
        "observed_active_phase": controller.active_phase,
        "green_phases": status.get("green_phases"),
        "clearing_phases": controller.clearing_phases,
        "yellow_phases": status.get("yellow_phases"),
        "red_phases": status.get("red_phases"),
        "protocol": status.get("protocol"),
        "latency_ms": health.get("latency_ms"),
        "message": health.get("message"),
        "read_at": now.isoformat(),
    }


def apply_post_command_reading(
    controller: SignalController,
    adapter: SignalControllerProvider,
    requested_phase: int,
    db=None,
) -> Tuple[Dict[str, Any], bool]:
    """Re-reads the controller after a command and reports whether it took effect.

    Returns (provenance, effect_observed). `effect_observed` is False whenever
    the controller could not be read back, or was read back still displaying a
    different phase - which is a legitimate outcome, not a failure: a hold on a
    phase that is not currently green only takes effect when that phase is next
    served.
    """
    provenance = apply_controller_reading(controller, adapter, db=db)
    greens = provenance.get("green_phases") or []
    effect_observed = bool(provenance.get("state_readable")) and requested_phase in greens

    provenance["requested_phase"] = requested_phase
    provenance["effect_observed"] = effect_observed
    if not provenance.get("state_readable"):
        provenance["effect_verification"] = "UNVERIFIED_CONTROLLER_STATE_UNREADABLE"
    elif effect_observed:
        provenance["effect_verification"] = "OBSERVED_PHASE_DISPLAYING_GREEN"
    else:
        provenance["effect_verification"] = "ACCEPTED_BY_CONTROLLER_NOT_YET_DISPLAYING"

    return provenance, effect_observed
