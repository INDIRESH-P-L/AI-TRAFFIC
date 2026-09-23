"""TRAFFICINTEL AI - Fine-Grained Scopes & RBAC

Roles are a convenience; scopes are the authority. Every protected operation
declares the scope it needs, and a caller — whether a logged-in operator or an
API key — is checked against the scopes they actually hold.

The role-to-scope map below is the whole access model in one readable table,
which matters more here than elsewhere: an agency's safety case depends on
being able to answer "who can change a signal?" by reading one file.

Design decisions:

* **VIEWER cannot write anything**, including acknowledging an alert. Read-only
  means read-only.
* **OPERATOR can command signals but not reconfigure them.** Changing a phase's
  minimum green is an engineering change with a different review path from
  holding a phase for ten seconds.
* **Nobody gets a scope that bypasses the Safety Engine**, because no such
  scope exists. The engine is not an authorisation check that a sufficiently
  privileged caller can skip; it is in the code path.
"""

from __future__ import annotations

from typing import Dict, List, Set

# --- Scope vocabulary ------------------------------------------------------
READ_TELEMETRY = "telemetry:read"
READ_ANALYTICS = "analytics:read"
READ_AUDIT = "audit:read"
EXPORT_AUDIT = "audit:export"

WRITE_INCIDENT = "incident:write"
WRITE_ALERT = "alert:write"

COMMAND_SIGNAL = "signal:command"
CONFIGURE_SIGNAL = "signal:configure"
CONFIGURE_INFRASTRUCTURE = "infrastructure:configure"

RUN_OPTIMIZER = "optimizer:run"
RUN_SCENARIO = "scenario:run"

MANAGE_RULES = "rules:manage"
MANAGE_USERS = "users:manage"
MANAGE_API_KEYS = "apikeys:manage"
IMPORT_DATA = "data:import"

ALL_SCOPES: Set[str] = {
    READ_TELEMETRY, READ_ANALYTICS, READ_AUDIT, EXPORT_AUDIT,
    WRITE_INCIDENT, WRITE_ALERT,
    COMMAND_SIGNAL, CONFIGURE_SIGNAL, CONFIGURE_INFRASTRUCTURE,
    RUN_OPTIMIZER, RUN_SCENARIO,
    MANAGE_RULES, MANAGE_USERS, MANAGE_API_KEYS, IMPORT_DATA,
}

SCOPE_DESCRIPTIONS: Dict[str, str] = {
    READ_TELEMETRY: "Read junctions, telemetry, map layers and live state.",
    READ_ANALYTICS: "Read performance measures and reports.",
    READ_AUDIT: "Read the audit ledger.",
    EXPORT_AUDIT: "Export the audit ledger for external anchoring.",
    WRITE_INCIDENT: "Create incidents and move them through their lifecycle.",
    WRITE_ALERT: "Acknowledge and resolve alerts.",
    COMMAND_SIGNAL: "Issue signal commands and preemption calls (always via the Safety Engine).",
    CONFIGURE_SIGNAL: "Change controller and phase configuration, including green envelopes.",
    CONFIGURE_INFRASTRUCTURE: "Add or change junctions, cameras, detectors and corridors.",
    RUN_OPTIMIZER: "Produce timing recommendations from real or entered demand.",
    RUN_SCENARIO: "Run hypothetical scenarios in the sandbox.",
    MANAGE_RULES: "Create, edit and delete alert rules.",
    MANAGE_USERS: "Create and manage operator accounts.",
    MANAGE_API_KEYS: "Issue and revoke API keys.",
    IMPORT_DATA: "Import CSV, GeoJSON and GTFS data.",
}

# --- Roles -----------------------------------------------------------------
VIEWER = "VIEWER"
OPERATOR = "OPERATOR"
ENGINEER = "ENGINEER"
ADMIN = "ADMIN"
AUDITOR = "AUDITOR"

ROLE_SCOPES: Dict[str, Set[str]] = {
    # Read-only means read-only: no acknowledge, no notes, nothing.
    VIEWER: {READ_TELEMETRY, READ_ANALYTICS},

    # Day-to-day control room work.
    OPERATOR: {
        READ_TELEMETRY, READ_ANALYTICS, READ_AUDIT,
        WRITE_INCIDENT, WRITE_ALERT,
        COMMAND_SIGNAL, RUN_SCENARIO,
    },

    # Signal engineering: reconfiguration and optimisation.
    ENGINEER: {
        READ_TELEMETRY, READ_ANALYTICS, READ_AUDIT, EXPORT_AUDIT,
        WRITE_INCIDENT, WRITE_ALERT,
        COMMAND_SIGNAL, CONFIGURE_SIGNAL, CONFIGURE_INFRASTRUCTURE,
        RUN_OPTIMIZER, RUN_SCENARIO,
        MANAGE_RULES, IMPORT_DATA,
    },

    # An auditor reads everything and changes nothing - deliberately not a
    # superset of OPERATOR, because independence is the point of the role.
    AUDITOR: {READ_TELEMETRY, READ_ANALYTICS, READ_AUDIT, EXPORT_AUDIT},

    ADMIN: set(ALL_SCOPES),
}


def scopes_for_role(role: str) -> Set[str]:
    return set(ROLE_SCOPES.get((role or "").upper(), set()))


def role_has_scope(role: str, scope: str) -> bool:
    return scope in scopes_for_role(role)


def describe_role(role: str) -> Dict[str, object]:
    granted = sorted(scopes_for_role(role))
    return {
        "role": role,
        "scopes": granted,
        "scope_count": len(granted),
        "denied": sorted(ALL_SCOPES - set(granted)),
    }


def validate_scopes(requested: List[str]) -> List[str]:
    """Returns the requested scopes that are not part of the vocabulary."""
    return [scope for scope in requested if scope not in ALL_SCOPES]
