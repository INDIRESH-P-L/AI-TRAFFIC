"""TRAFFICINTEL AI - Provider Health Monitor

Tracks, per provider, what the platform has actually observed: heartbeat,
latency distribution, error rate, last success and last failure — and derives a
health state from those measurements with hysteresis.

**Why hysteresis.** A provider hovering at the edge of a threshold would
otherwise flap between HEALTHY and DEGRADED every poll, filling the operator's
notification centre with noise and training them to ignore it. A provider must
be bad for `degrade_after` consecutive observations to degrade, and good for
`recover_after` consecutive observations to recover. The two thresholds are
deliberately asymmetric: degrade quickly, recover slowly.

States: `HEALTHY` -> `DEGRADED` -> `FAILED`, plus `UNKNOWN` before the first
observation. `UNKNOWN` is a real state, not a synonym for healthy: a provider
nobody has probed has not been shown to work.
"""

from __future__ import annotations

import logging
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional

from app.events import topics
from app.events.bus import event_bus
from app.health.circuit import CircuitBreaker

logger = logging.getLogger("trafficintel.health.monitor")

UNKNOWN = "UNKNOWN"
HEALTHY = "HEALTHY"
DEGRADED = "DEGRADED"
FAILED = "FAILED"

SAMPLE_WINDOW = 50


@dataclass
class ProviderHealth:
    """Observed health of one provider endpoint."""

    key: str
    kind: str                       # CONTROLLER, CAMERA, SENSOR, WEATHER, TRANSIT
    label: str

    state: str = UNKNOWN
    #: Consecutive observations pushing toward the opposite state.
    bad_streak: int = 0
    good_streak: int = 0

    degrade_after: int = 2
    recover_after: int = 3
    #: Error rate above which an observation counts as "bad".
    error_rate_threshold: float = 0.34
    #: Latency above which an observation counts as "bad", in milliseconds.
    latency_threshold_ms: float = 2000.0

    total_checks: int = 0
    total_failures: int = 0
    last_success_at: Optional[str] = None
    last_failure_at: Optional[str] = None
    last_error: Optional[str] = None
    last_checked_at: Optional[str] = None
    state_changed_at: Optional[str] = None

    latencies_ms: Deque[float] = field(default_factory=lambda: deque(maxlen=SAMPLE_WINDOW))
    outcomes: Deque[bool] = field(default_factory=lambda: deque(maxlen=SAMPLE_WINDOW))
    circuit: CircuitBreaker = field(default=None)  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.circuit is None:
            self.circuit = CircuitBreaker(name=self.key)

    # -- derived measurements ---------------------------------------------

    @property
    def error_rate(self) -> Optional[float]:
        if not self.outcomes:
            return None
        failures = sum(1 for ok in self.outcomes if not ok)
        return round(failures / len(self.outcomes), 4)

    @property
    def latency_p50_ms(self) -> Optional[float]:
        if not self.latencies_ms:
            return None
        return round(statistics.median(self.latencies_ms), 1)

    @property
    def latency_p95_ms(self) -> Optional[float]:
        if len(self.latencies_ms) < 2:
            return round(self.latencies_ms[0], 1) if self.latencies_ms else None
        ordered = sorted(self.latencies_ms)
        index = min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))
        return round(ordered[index], 1)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "label": self.label,
            "state": self.state,
            "state_changed_at": self.state_changed_at,
            "total_checks": self.total_checks,
            "total_failures": self.total_failures,
            "error_rate": self.error_rate,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "last_checked_at": self.last_checked_at,
            "last_error": self.last_error,
            "sample_size": len(self.outcomes),
            "circuit": self.circuit.snapshot(),
            "thresholds": {
                "degrade_after_consecutive": self.degrade_after,
                "recover_after_consecutive": self.recover_after,
                "error_rate": self.error_rate_threshold,
                "latency_ms": self.latency_threshold_ms,
            },
            # Said explicitly so an unprobed provider is never read as working.
            "measurement_basis": (
                "NO_OBSERVATIONS_YET" if self.total_checks == 0
                else "OBSERVED_OVER_LAST_{}_CHECKS".format(len(self.outcomes))
            ),
        }


class ProviderHealthMonitor:
    """Registry of provider health, updated by whoever performs the calls."""

    def __init__(self) -> None:
        self._providers: Dict[str, ProviderHealth] = {}
        self._lock = threading.Lock()

    def register(self, key: str, kind: str, label: str) -> ProviderHealth:
        with self._lock:
            existing = self._providers.get(key)
            if existing:
                existing.label = label
                return existing
            provider = ProviderHealth(key=key, kind=kind, label=label)
            self._providers[key] = provider
            return provider

    def get(self, key: str) -> Optional[ProviderHealth]:
        return self._providers.get(key)

    def circuit_for(self, key: str) -> Optional[CircuitBreaker]:
        provider = self._providers.get(key)
        return provider.circuit if provider else None

    # -- recording ---------------------------------------------------------

    def record(
        self,
        key: str,
        success: bool,
        latency_ms: Optional[float] = None,
        error: Optional[str] = None,
        kind: str = "UNKNOWN",
        label: Optional[str] = None,
    ) -> ProviderHealth:
        """Records one observation and re-evaluates the provider's state."""
        provider = self.register(key, kind, label or key)
        now = datetime.now(timezone.utc).isoformat()

        with self._lock:
            provider.total_checks += 1
            provider.last_checked_at = now
            provider.outcomes.append(success)

            if success:
                provider.last_success_at = now
                provider.last_error = None
                if latency_ms is not None:
                    provider.latencies_ms.append(latency_ms)
                if provider.circuit.record_success():
                    event_bus.publish(topics.PROVIDER_HEALTH_CIRCUIT_CLOSED, {
                        "provider": key, "label": provider.label,
                    })
            else:
                provider.total_failures += 1
                provider.last_failure_at = now
                provider.last_error = error
                if provider.circuit.record_failure(error or "unspecified failure"):
                    event_bus.publish(topics.PROVIDER_HEALTH_CIRCUIT_OPENED, {
                        "provider": key,
                        "label": provider.label,
                        "retry_after_sec": provider.circuit.retry_after(),
                        "last_error": error,
                    })

            self._reevaluate(provider, success, latency_ms, now)

        return provider

    def _reevaluate(
        self,
        provider: ProviderHealth,
        success: bool,
        latency_ms: Optional[float],
        now: str,
    ) -> None:
        """Applies hysteresis and emits a state-change event on transition."""
        # An observation is "bad" if it failed, or succeeded too slowly, or the
        # windowed error rate is above threshold.
        error_rate = provider.error_rate
        slow = latency_ms is not None and latency_ms > provider.latency_threshold_ms
        rate_bad = error_rate is not None and error_rate > provider.error_rate_threshold
        bad = (not success) or slow or rate_bad

        if bad:
            provider.bad_streak += 1
            provider.good_streak = 0
        else:
            provider.good_streak += 1
            provider.bad_streak = 0

        previous = provider.state
        target = previous

        if provider.circuit.state == "OPEN":
            # A tripped breaker is a failed provider by definition: the
            # platform is not even attempting calls.
            target = FAILED
        elif provider.bad_streak >= provider.degrade_after:
            # Sustained total failure is FAILED; intermittent is DEGRADED.
            recent = list(provider.outcomes)[-provider.degrade_after:]
            target = FAILED if recent and not any(recent) else DEGRADED
        elif provider.good_streak >= provider.recover_after:
            target = HEALTHY
        elif previous == UNKNOWN and not bad:
            # Hysteresis guards against flapping between two known states.
            # There is nothing to flap from on the first observation, so one
            # clean success is enough to leave UNKNOWN. A first FAILURE does
            # not leave UNKNOWN: it takes `degrade_after` to say DEGRADED,
            # and "we have not established this works" stays true meanwhile.
            target = HEALTHY

        if target == previous:
            return

        provider.state = target
        provider.state_changed_at = now

        topic = {
            HEALTHY: topics.PROVIDER_HEALTH_HEALTHY,
            DEGRADED: topics.PROVIDER_HEALTH_DEGRADED,
            FAILED: topics.PROVIDER_HEALTH_FAILED,
        }.get(target)

        if topic:
            event_bus.publish(topic, {
                "provider": provider.key,
                "label": provider.label,
                "kind": provider.kind,
                "previous_state": previous,
                "state": target,
                "error_rate": provider.error_rate,
                "latency_p95_ms": provider.latency_p95_ms,
                "last_error": provider.last_error,
            })
            logger.info(
                "Provider %s: %s -> %s (errors %s, p95 %sms)",
                provider.key, previous, target, provider.error_rate, provider.latency_p95_ms,
            )

    # -- helpers -----------------------------------------------------------

    def observe(self, key: str, kind: str, label: str):
        """Context manager timing a provider call and recording the outcome.

        Usage:
            with monitor.observe(key, "WEATHER", "Open-Meteo") as obs:
                result = do_the_call()
                obs.failed("HTTP 503")   # optional, on a soft failure
        """
        return _Observation(self, key, kind, label)

    def all(self) -> List[Dict[str, Any]]:
        return [p.snapshot() for p in self._providers.values()]

    def summary(self) -> Dict[str, Any]:
        counts: Dict[str, int] = {}
        for provider in self._providers.values():
            counts[provider.state] = counts.get(provider.state, 0) + 1
        return {
            "total_providers": len(self._providers),
            "by_state": counts,
            "open_circuits": [
                p.key for p in self._providers.values() if p.circuit.state == "OPEN"
            ],
        }

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._providers.clear()


class _Observation:
    """Times one provider call; records success unless marked failed."""

    def __init__(self, monitor: ProviderHealthMonitor, key: str, kind: str, label: str):
        self._monitor = monitor
        self._key = key
        self._kind = kind
        self._label = label
        self._started = 0.0
        self._error: Optional[str] = None

    def __enter__(self) -> "_Observation":
        self._started = time.monotonic()
        return self

    def failed(self, error: str) -> None:
        self._error = error

    def __exit__(self, exc_type, exc, _tb) -> bool:
        latency_ms = (time.monotonic() - self._started) * 1000.0
        error = self._error
        if exc is not None:
            error = "{}: {}".format(exc_type.__name__, exc)

        self._monitor.record(
            key=self._key,
            success=error is None,
            latency_ms=latency_ms if error is None else None,
            error=error,
            kind=self._kind,
            label=self._label,
        )
        return False  # never swallow the exception


provider_monitor = ProviderHealthMonitor()
