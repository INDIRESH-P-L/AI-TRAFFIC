"""TRAFFICINTEL AI - Rate Limiting

Sliding-window rate limiter keyed by caller identity, with a stricter bucket
for signal control.

Why control commands get their own, much tighter, bucket: a runaway client
issuing hundreds of phase holds per minute is not a throughput problem, it is a
safety problem. The Safety Engine would reject most of them, but a cabinet
being hammered with SNMP SETs is still being hammered. The limit here is well
below anything a human operator could produce.

This is a process-local limiter. It protects a single API process; a
multi-process deployment needs a shared store (Redis) to enforce a global
limit, and the response header says which kind of limit answered so an operator
is not misled about the guarantee.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple


@dataclass(frozen=True)
class LimitPolicy:
    name: str
    max_requests: int
    window_sec: float
    description: str


# Generous for reads; the console polls and subscribes.
DEFAULT_POLICY = LimitPolicy(
    "default", max_requests=600, window_sec=60.0,
    description="General API traffic.",
)

# Writes are deliberate operator actions.
WRITE_POLICY = LimitPolicy(
    "write", max_requests=120, window_sec=60.0,
    description="Configuration and lifecycle changes.",
)

# Signal control: far below human operating speed on purpose.
SIGNAL_COMMAND_POLICY = LimitPolicy(
    "signal_command", max_requests=12, window_sec=60.0,
    description=(
        "Signal commands and preemption calls. Set below any plausible human rate: "
        "a client exceeding this is malfunctioning, and a cabinet being flooded with "
        "SNMP SETs is a safety concern even when the Safety Engine rejects them."
    ),
)

# Authentication: slows credential stuffing.
AUTH_POLICY = LimitPolicy(
    "auth", max_requests=10, window_sec=300.0,
    description="Login attempts, to slow credential stuffing.",
)

POLICIES = {
    policy.name: policy
    for policy in (DEFAULT_POLICY, WRITE_POLICY, SIGNAL_COMMAND_POLICY, AUTH_POLICY)
}


class RateLimiter:
    """Sliding-window counters per (identity, policy)."""

    def __init__(self) -> None:
        self._windows: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, identity: str, policy: LimitPolicy) -> Tuple[bool, Dict[str, object]]:
        """Returns (allowed, headers). Records the request when allowed."""
        now = time.monotonic()
        key = (identity, policy.name)

        with self._lock:
            window = self._windows[key]
            cutoff = now - policy.window_sec
            while window and window[0] < cutoff:
                window.popleft()

            allowed = len(window) < policy.max_requests
            if allowed:
                window.append(now)

            remaining = max(0, policy.max_requests - len(window))
            retry_after = (
                max(0.0, window[0] + policy.window_sec - now) if window and not allowed else 0.0
            )

        headers = {
            "X-RateLimit-Policy": policy.name,
            "X-RateLimit-Limit": str(policy.max_requests),
            "X-RateLimit-Remaining": str(remaining),
            "X-RateLimit-Window-Seconds": str(int(policy.window_sec)),
            # Stated so nobody mistakes a per-process limit for a global one.
            "X-RateLimit-Scope": "per-process",
        }
        if not allowed:
            headers["Retry-After"] = str(int(retry_after) + 1)

        return allowed, headers

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._windows.clear()


rate_limiter = RateLimiter()


def policy_for_request(method: str, path: str) -> LimitPolicy:
    """Chooses the bucket a request falls into."""
    if "/auth/login" in path:
        return AUTH_POLICY
    if "/signals/commands" in path and method == "POST" and not path.endswith("/validate"):
        return SIGNAL_COMMAND_POLICY
    if "/emergency" in path and method == "POST":
        return SIGNAL_COMMAND_POLICY
    if method in ("POST", "PATCH", "PUT", "DELETE"):
        return WRITE_POLICY
    return DEFAULT_POLICY
