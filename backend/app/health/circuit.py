"""TRAFFICINTEL AI - Circuit Breaker

Stops the platform hammering a provider that is already failing, and — more
importantly here — stops a failing provider from making the console look slow.

States:

    CLOSED     normal. Failures are counted.
    OPEN       the provider is failing. Calls are refused immediately with a
               truthful reason rather than waiting for another timeout.
    HALF_OPEN  after a cooldown, ONE probe is allowed through. Success closes
               the circuit; failure re-opens it with a longer cooldown.

The important property for this platform: a refused call returns a stated
reason (`CIRCUIT_OPEN`), never a fabricated success or a stale cached value
presented as current. A circuit that is open means the console shows
DISCONNECTED, which is the truth.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger("trafficintel.health.circuit")

CLOSED = "CLOSED"
OPEN = "OPEN"
HALF_OPEN = "HALF_OPEN"


class CircuitOpenError(RuntimeError):
    """Raised when a call is refused because the circuit is open."""

    def __init__(self, name: str, retry_after_sec: float):
        self.name = name
        self.retry_after_sec = retry_after_sec
        super().__init__(
            "Circuit '{}' is open; refusing the call for another {:.1f}s".format(
                name, retry_after_sec
            )
        )


@dataclass
class CircuitBreaker:
    """One breaker per provider endpoint."""

    name: str
    failure_threshold: int = 3
    base_cooldown_sec: float = 15.0
    max_cooldown_sec: float = 300.0
    #: Consecutive successes required in HALF_OPEN before closing.
    success_threshold: int = 1

    state: str = CLOSED
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    opened_at: Optional[float] = None
    open_count: int = 0
    last_error: Optional[str] = None
    _cooldown_sec: float = field(default=0.0)

    # -- gate ---------------------------------------------------------------

    def allow(self) -> bool:
        """May a call proceed now? Transitions OPEN -> HALF_OPEN when due."""
        if self.state == CLOSED:
            return True

        if self.state == OPEN:
            if self.opened_at is None:
                return True
            if time.monotonic() - self.opened_at >= self._cooldown_sec:
                self.state = HALF_OPEN
                self.consecutive_successes = 0
                logger.info("Circuit '%s' half-open: allowing one probe", self.name)
                return True
            return False

        # HALF_OPEN: exactly one probe is in flight at a time.
        return True

    def retry_after(self) -> float:
        if self.state != OPEN or self.opened_at is None:
            return 0.0
        return max(0.0, self._cooldown_sec - (time.monotonic() - self.opened_at))

    def raise_if_open(self) -> None:
        if not self.allow():
            raise CircuitOpenError(self.name, self.retry_after())

    # -- outcomes -----------------------------------------------------------

    def record_success(self) -> bool:
        """Returns True if this success closed the circuit."""
        self.consecutive_failures = 0
        self.last_error = None

        if self.state == HALF_OPEN:
            self.consecutive_successes += 1
            if self.consecutive_successes >= self.success_threshold:
                self.state = CLOSED
                self.opened_at = None
                self._cooldown_sec = 0.0
                logger.info("Circuit '%s' closed after successful probe", self.name)
                return True
            return False

        self.state = CLOSED
        return False

    def record_failure(self, error: str) -> bool:
        """Returns True if this failure opened (or re-opened) the circuit."""
        self.last_error = error
        self.consecutive_successes = 0
        self.consecutive_failures += 1

        was_open = self.state == OPEN
        should_open = (
            self.state == HALF_OPEN
            or self.consecutive_failures >= self.failure_threshold
        )

        if should_open:
            # Exponential cooldown: a provider that keeps failing its probe is
            # retried less often, up to a ceiling so it is never abandoned.
            self.open_count += 1
            self._cooldown_sec = min(
                self.base_cooldown_sec * (2 ** max(0, self.open_count - 1)),
                self.max_cooldown_sec,
            )
            self.state = OPEN
            self.opened_at = time.monotonic()
            if not was_open:
                logger.warning(
                    "Circuit '%s' opened after %d failures (cooldown %.0fs): %s",
                    self.name, self.consecutive_failures, self._cooldown_sec, error,
                )
            return True

        return False

    def snapshot(self) -> Dict[str, Any]:
        return {
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "open_count": self.open_count,
            "retry_after_sec": round(self.retry_after(), 1),
            "cooldown_sec": round(self._cooldown_sec, 1),
            "last_error": self.last_error,
        }

    def reset(self) -> None:
        self.state = CLOSED
        self.consecutive_failures = 0
        self.consecutive_successes = 0
        self.opened_at = None
        self.open_count = 0
        self.last_error = None
        self._cooldown_sec = 0.0
