"""TRAFFICINTEL AI - Prometheus Metrics

A dependency-free registry exposing counters, gauges and histograms in the
Prometheus text exposition format.

**What is deliberately absent.** No traffic measurement is exported here. Not
vehicle counts, not occupancy, not speeds. Those belong to the provenance
system, where every value carries its source, timestamp and quality state, and
a scrape interval would strip all three — a Prometheus gauge reading
`occupancy_pct 42` says nothing about whether that detector reported four
seconds or forty minutes ago, and a dashboard built on it would show stale
readings as current. Operational metrics about the *platform* are exported;
measurements of the *road* are served by the API that can carry their
provenance.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

LabelSet = Tuple[Tuple[str, str], ...]

DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _labels_key(labels: Optional[Dict[str, str]]) -> LabelSet:
    if not labels:
        return ()
    return tuple(sorted((str(k), str(v)) for k, v in labels.items()))


def _render_labels(labels: LabelSet) -> str:
    if not labels:
        return ""
    inner = ",".join(
        '{}="{}"'.format(key, str(value).replace("\\", "\\\\").replace('"', '\\"'))
        for key, value in labels
    )
    return "{" + inner + "}"


class MetricsRegistry:
    """Process-local metric store."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, Dict[LabelSet, float]] = defaultdict(dict)
        self._gauges: Dict[str, Dict[LabelSet, float]] = defaultdict(dict)
        self._histograms: Dict[str, Dict[LabelSet, List[float]]] = defaultdict(dict)
        self._help: Dict[str, str] = {
            "http_requests_total": "Total HTTP requests handled, by method, status and rate-limit policy.",
            "http_request_duration_seconds": "HTTP request duration in seconds.",
            "signal_commands_total": "Signal commands processed, by outcome.",
            "safety_rejections_total": "Commands rejected by the Deterministic Safety Engine, by rule.",
            "provider_health_state": "Provider health as a number: 0 unknown, 1 healthy, 2 degraded, 3 failed.",
            "event_bus_published_total": "Events published, by topic.",
            "event_bus_dropped_total": "Events dropped because a subscriber fell behind.",
            "alerts_raised_total": "Alerts raised, by severity.",
            "websocket_connections": "Currently connected operator consoles.",
        }

    # -- writes ----------------------------------------------------------

    def increment(
        self, name: str, labels: Optional[Dict[str, str]] = None, value: float = 1.0
    ) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._counters[name][key] = self._counters[name].get(key, 0.0) + value

    def set_gauge(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._gauges[name][key] = value

    def observe(
        self, name: str, value: float, labels: Optional[Dict[str, str]] = None
    ) -> None:
        key = _labels_key(labels)
        with self._lock:
            self._histograms[name].setdefault(key, []).append(value)

    # -- reads -----------------------------------------------------------

    def snapshot(self) -> Dict[str, object]:
        with self._lock:
            return {
                "counters": {
                    name: {_render_labels(k) or "{}": v for k, v in series.items()}
                    for name, series in self._counters.items()
                },
                "gauges": {
                    name: {_render_labels(k) or "{}": v for k, v in series.items()}
                    for name, series in self._gauges.items()
                },
                "histograms": {
                    name: {
                        _render_labels(k) or "{}": {
                            "count": len(values),
                            "sum": round(sum(values), 6),
                        }
                        for k, values in series.items()
                    }
                    for name, series in self._histograms.items()
                },
            }

    def render(self) -> str:
        """Prometheus text exposition format."""
        lines: List[str] = []

        with self._lock:
            counters = {n: dict(s) for n, s in self._counters.items()}
            gauges = {n: dict(s) for n, s in self._gauges.items()}
            histograms = {n: {k: list(v) for k, v in s.items()} for n, s in self._histograms.items()}

        for name, series in sorted(counters.items()):
            lines.append("# HELP {} {}".format(name, self._help.get(name, name)))
            lines.append("# TYPE {} counter".format(name))
            for labels, value in sorted(series.items()):
                lines.append("{}{} {}".format(name, _render_labels(labels), value))

        for name, series in sorted(gauges.items()):
            lines.append("# HELP {} {}".format(name, self._help.get(name, name)))
            lines.append("# TYPE {} gauge".format(name))
            for labels, value in sorted(series.items()):
                lines.append("{}{} {}".format(name, _render_labels(labels), value))

        for name, series in sorted(histograms.items()):
            lines.append("# HELP {} {}".format(name, self._help.get(name, name)))
            lines.append("# TYPE {} histogram".format(name))
            for labels, values in sorted(series.items()):
                cumulative = 0
                ordered = sorted(values)
                for bucket in DEFAULT_BUCKETS:
                    cumulative = sum(1 for v in ordered if v <= bucket)
                    bucket_labels = labels + (("le", str(bucket)),)
                    lines.append(
                        "{}_bucket{} {}".format(name, _render_labels(bucket_labels), cumulative)
                    )
                inf_labels = labels + (("le", "+Inf"),)
                lines.append(
                    "{}_bucket{} {}".format(name, _render_labels(inf_labels), len(ordered))
                )
                lines.append("{}_sum{} {}".format(name, _render_labels(labels), round(sum(ordered), 6)))
                lines.append("{}_count{} {}".format(name, _render_labels(labels), len(ordered)))

        lines.append(
            "# NOTE No traffic measurement is exported here. Vehicle counts, "
            "occupancy and speeds are served by the API, which carries their "
            "source, timestamp and data-quality state; a scrape would strip all three."
        )
        return "\n".join(lines) + "\n"

    def reset(self) -> None:
        """Test helper."""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


metrics_registry = MetricsRegistry()


def render_prometheus() -> str:
    """Refreshes derived gauges, then renders."""
    from app.api.v1.websocket import ws_manager
    from app.events.bus import event_bus
    from app.health.monitor import provider_monitor

    state_values = {"UNKNOWN": 0, "HEALTHY": 1, "DEGRADED": 2, "FAILED": 3}
    for provider in provider_monitor.all():
        metrics_registry.set_gauge(
            "provider_health_state",
            state_values.get(provider["state"], 0),
            {"provider": provider["key"], "kind": provider["kind"]},
        )

    bus_stats = event_bus.stats()
    for topic, count in bus_stats["published_by_topic"].items():
        metrics_registry.set_gauge("event_bus_published_total", count, {"topic": topic})
    metrics_registry.set_gauge("event_bus_dropped_total", bus_stats["total_dropped_events"])
    metrics_registry.set_gauge("websocket_connections", ws_manager.stats()["connections"])

    return metrics_registry.render()
