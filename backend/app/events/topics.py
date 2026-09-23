"""TRAFFICINTEL AI - Event Topic Vocabulary

One place that defines what the platform can say about itself.

Topics are dotted and hierarchical, so a subscriber can take `signal.command.*`
without enumerating every leaf. The vocabulary is closed: `publish` rejects a
topic that is not declared here, because a typo in a topic name produces an
event nobody receives and no error anybody sees.
"""

from __future__ import annotations

from typing import Dict, Set

# --- Telemetry -------------------------------------------------------------
TELEMETRY_OBSERVATION_INGESTED = "telemetry.observation.ingested"
TELEMETRY_METRIC_COMPUTED = "telemetry.metric.computed"
TELEMETRY_QUALITY_CHANGED = "telemetry.quality.changed"

# --- Incidents -------------------------------------------------------------
INCIDENT_DETECTED = "incident.detected"
INCIDENT_UPDATED = "incident.updated"
INCIDENT_RESOLVED = "incident.resolved"
INCIDENT_SLA_BREACHED = "incident.sla.breached"

# --- Signal control --------------------------------------------------------
SIGNAL_COMMAND_PROPOSED = "signal.command.proposed"
SIGNAL_COMMAND_ACCEPTED = "signal.command.accepted"
SIGNAL_COMMAND_REJECTED = "signal.command.rejected"
SIGNAL_COMMAND_EXECUTED = "signal.command.executed"
SIGNAL_COMMAND_FAILED = "signal.command.failed"
SIGNAL_STATE_CHANGED = "signal.state.changed"

# --- Provider health -------------------------------------------------------
PROVIDER_HEALTH_HEALTHY = "provider.health.healthy"
PROVIDER_HEALTH_DEGRADED = "provider.health.degraded"
PROVIDER_HEALTH_FAILED = "provider.health.failed"
PROVIDER_HEALTH_CIRCUIT_OPENED = "provider.health.circuit_opened"
PROVIDER_HEALTH_CIRCUIT_CLOSED = "provider.health.circuit_closed"

# --- Alerts & rules --------------------------------------------------------
ALERT_RAISED = "alert.raised"
ALERT_ACKNOWLEDGED = "alert.acknowledged"
ALERT_ESCALATED = "alert.escalated"
RULE_EVALUATED = "rule.evaluated"

# --- Optimiser -------------------------------------------------------------
OPTIMIZER_RECOMMENDATION = "optimizer.recommendation.created"

# --- Governance ------------------------------------------------------------
AUDIT_ENTRY_WRITTEN = "audit.entry.written"

ALL_TOPICS: Set[str] = {
    TELEMETRY_OBSERVATION_INGESTED,
    TELEMETRY_METRIC_COMPUTED,
    TELEMETRY_QUALITY_CHANGED,
    INCIDENT_DETECTED,
    INCIDENT_UPDATED,
    INCIDENT_RESOLVED,
    INCIDENT_SLA_BREACHED,
    SIGNAL_COMMAND_PROPOSED,
    SIGNAL_COMMAND_ACCEPTED,
    SIGNAL_COMMAND_REJECTED,
    SIGNAL_COMMAND_EXECUTED,
    SIGNAL_COMMAND_FAILED,
    SIGNAL_STATE_CHANGED,
    PROVIDER_HEALTH_HEALTHY,
    PROVIDER_HEALTH_DEGRADED,
    PROVIDER_HEALTH_FAILED,
    PROVIDER_HEALTH_CIRCUIT_OPENED,
    PROVIDER_HEALTH_CIRCUIT_CLOSED,
    ALERT_RAISED,
    ALERT_ACKNOWLEDGED,
    ALERT_ESCALATED,
    RULE_EVALUATED,
    OPTIMIZER_RECOMMENDATION,
    AUDIT_ENTRY_WRITTEN,
}

# Legacy topic names the console shipped with, mapped to the current
# vocabulary so an older client keeps working during a rolling deployment.
LEGACY_ALIASES: Dict[str, str] = {
    "signal.updated": SIGNAL_STATE_CHANGED,
    "incident.detected": INCIDENT_DETECTED,
    "incident.updated": INCIDENT_UPDATED,
}


def is_valid_topic(topic: str) -> bool:
    return topic in ALL_TOPICS


def matches(pattern: str, topic: str) -> bool:
    """Does a subscription pattern select this topic?

    Supports an exact name, a trailing wildcard segment (`signal.command.*`,
    which also matches `signal.command.executed`), and `*` for everything.
    """
    if pattern == "*":
        return True
    if pattern == topic:
        return True
    if pattern.endswith(".*"):
        prefix = pattern[:-2]
        return topic == prefix or topic.startswith(prefix + ".")
    return False
