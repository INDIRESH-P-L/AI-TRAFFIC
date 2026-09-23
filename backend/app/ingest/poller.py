"""TRAFFICINTEL AI - NTCIP Controller Polling Service

Polls every NTCIP 1202 controller on an interval, records the observed phase
state, and feeds the provider health monitor.

This is what turns the platform from request-driven into continuously
observing: arrival-on-green, split failures, progression and the corridor
time-space diagram all need phase state sampled over time, and nobody is going
to click "test connection" every two seconds.

Honest behaviours:

* **A poll that fails records a failure**, feeding the health monitor and
  eventually the circuit breaker. It does not retry silently until something
  works and then report success.
* **A controller whose circuit is open is skipped**, not hammered, and the
  skip is reported in the cycle summary.
* **Nothing is written for an unreadable poll.** A gap in `signal_state_logs`
  is an honest record of a period nobody observed, and the analytics treat it
  as one.
* **Only the lease holder polls.** The poller runs in-process, so two replicas
  would otherwise write two rows per observation and double every measure
  derived from the log. A non-holding instance reports NOT_LEADER rather than
  appearing idle - "another instance is doing this" and "polling is broken"
  must not look the same on a status page. See `app/ingest/lease.py`.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.database import SessionLocal
from app.events import topics
from app.events.bus import event_bus
from app.health.monitor import provider_monitor
from app.ingest import lease
from app.models.entities import SignalController, utc_now
from app.observability.metrics import metrics_registry
from app.providers.controller_provider import get_controller_adapter
from app.providers.controller_sync import apply_controller_reading

logger = logging.getLogger("trafficintel.ingest.poller")

DEFAULT_INTERVAL_SEC = 2.0
#: Protocols with a session layer that can actually be polled for state.
POLLABLE_PROTOCOLS = {"NTCIP_1202"}


class ControllerPoller:
    """Background task polling controllers for observed phase state."""

    def __init__(self, interval_sec: float = DEFAULT_INTERVAL_SEC):
        self.interval_sec = interval_sec
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self.cycles = 0
        self.last_cycle: Optional[Dict[str, Any]] = None
        self.started_at: Optional[str] = None
        #: Why this instance did or did not poll on its last attempt.
        self.lease_state: Optional[Dict[str, Any]] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self.started_at = utc_now().isoformat()
        self._task = asyncio.create_task(self._loop(), name="ntcip-poller")
        logger.info("Controller poller started at %.1fs interval", self.interval_sec)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Controller poller stopped after %d cycles", self.cycles)

    async def _loop(self) -> None:
        while self._running:
            try:
                # The poll is blocking socket work; keep it off the event loop
                # so a slow cabinet cannot stall the WebSocket gateway.
                await asyncio.to_thread(self.poll_once)
                self.cycles += 1
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - a bad cycle must not kill the poller
                logger.exception("Controller poll cycle failed")

            await asyncio.sleep(self.interval_sec)

    # -- one cycle ---------------------------------------------------------

    def poll_once(self) -> Dict[str, Any]:
        """Polls every pollable controller once. Safe to call directly in tests.

        Records the cycle on `last_cycle` whoever triggered it, so the status
        endpoint reflects the most recent poll rather than only the ones the
        background loop ran.
        """
        started = datetime.now(timezone.utc)
        db = SessionLocal()

        polled: List[Dict[str, Any]] = []
        skipped: List[Dict[str, Any]] = []

        try:
            # Single-writer gate. Checked inside the cycle rather than once at
            # startup so that an instance which loses or gains the lease mid-run
            # follows it within one interval instead of until the next restart.
            holds_lease, lease_reason = lease.try_acquire(db)
            self.lease_state = {
                "holds_lease": holds_lease,
                "instance_id": lease.INSTANCE_ID,
                "reason": lease_reason,
            }

            if not holds_lease:
                cycle = {
                    "cycle_started_at": started.isoformat(),
                    "duration_sec": round(
                        (datetime.now(timezone.utc) - started).total_seconds(), 3
                    ),
                    "status": "NOT_LEADER",
                    "controllers_polled": 0,
                    "controllers_skipped": 0,
                    "polled": [],
                    "skipped": [],
                    "detail": lease_reason,
                }
                self.last_cycle = cycle
                return cycle

            controllers = db.query(SignalController).all()

            for controller in controllers:
                if (controller.protocol or "").upper() not in POLLABLE_PROTOCOLS:
                    skipped.append({
                        "controller_id": controller.id,
                        "name": controller.name,
                        "reason": "PROTOCOL_HAS_NO_SESSION_LAYER",
                        "protocol": controller.protocol,
                    })
                    continue

                health_key = "controller:ntcip:{}:{}".format(
                    controller.ip_address, controller.port
                )
                provider = provider_monitor.get(health_key)
                if provider and provider.circuit.state == "OPEN":
                    skipped.append({
                        "controller_id": controller.id,
                        "name": controller.name,
                        "reason": "CIRCUIT_OPEN",
                        "retry_after_sec": round(provider.circuit.retry_after(), 1),
                    })
                    continue

                adapter = get_controller_adapter(
                    controller.vendor, controller.model, controller.protocol,
                    controller.ip_address, controller.port,
                )

                previous_phase = controller.active_phase
                provenance = apply_controller_reading(controller, adapter, db=db)

                polled.append({
                    "controller_id": controller.id,
                    "name": controller.name,
                    "connection_status": provenance["connection_status"],
                    "state_readable": provenance["state_readable"],
                    "green_phases": provenance.get("green_phases"),
                })

                metrics_registry.increment("controller_polls_total", {
                    "result": "readable" if provenance["state_readable"] else "unreadable",
                })

                # Only a real change is published; a steady phase is not news.
                if provenance["state_readable"] and provenance["observed_active_phase"] != previous_phase:
                    event_bus.publish(topics.SIGNAL_STATE_CHANGED, {
                        "controller_id": controller.id,
                        "intersection_id": controller.intersection_id,
                        "previous_phase": previous_phase,
                        "active_phase": provenance["observed_active_phase"],
                        "green_phases": provenance.get("green_phases"),
                        "clearing_phases": provenance.get("clearing_phases"),
                        "observed": True,
                    })

            db.commit()

        finally:
            db.close()

        duration = (datetime.now(timezone.utc) - started).total_seconds()
        cycle = {
            "cycle_started_at": started.isoformat(),
            "duration_sec": round(duration, 3),
            # Always present, so a status page never has to infer whether a
            # cycle with zero polls was idle, refused, or simply had nothing
            # to poll.
            "status": "POLLED",
            "controllers_polled": len(polled),
            "controllers_skipped": len(skipped),
            "polled": polled,
            "skipped": skipped,
        }
        self.last_cycle = cycle
        return cycle

    # -- introspection -----------------------------------------------------

    def status(self) -> Dict[str, Any]:
        # Read live rather than from cached state: an operator checking why
        # nothing is being polled needs the lease as it stands now, not as it
        # stood when this instance last ran a cycle.
        db = SessionLocal()
        try:
            holder = lease.current_holder(db)
        except Exception:  # noqa: BLE001 - status must not fail on a DB blip
            holder = None
        finally:
            db.close()

        return {
            "running": self._running,
            "interval_sec": self.interval_sec,
            "cycles_completed": self.cycles,
            "started_at": self.started_at,
            "last_cycle": self.last_cycle,
            "instance_id": lease.INSTANCE_ID,
            "lease": holder,
            "is_polling_instance": bool(holder and holder["is_this_instance"]),
            "lease_note": (
                "Exactly one instance polls at a time. If this instance is not the "
                "holder it is deliberately idle, and observations are still being "
                "recorded once by the holder - not missing."
            ),
            "pollable_protocols": sorted(POLLABLE_PROTOCOLS),
            "note": (
                "Only protocols with an implemented session layer can be polled for "
                "state. Controllers on other protocols are listed as skipped rather "
                "than silently ignored."
            ),
        }


controller_poller = ControllerPoller()
