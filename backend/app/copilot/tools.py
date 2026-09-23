"""TRAFFICINTEL AI - Copilot Tools

The Copilot answers only from what these tools return. Each one queries real
stored state and returns, alongside its data, the citations that support it:
a record id and timestamp, or a standard and section.

The contract every tool keeps:

* **A citation is a pointer to something checkable.** `{"type": "record",
  "table": "traffic_metrics", "id": "...", "observed_at": "..."}` can be looked
  up. "According to recent telemetry" cannot, and is not a citation.

* **Absence is an answer.** A tool that finds nothing returns
  `status: NO_DATA` with the reason, never an empty result the caller might
  read as zero.

* **No tool computes a new number.** Tools retrieve; the analytics and safety
  modules compute. A Copilot that did its own arithmetic would produce figures
  that disagree with the console showing the same thing.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.performance import SignalPerformance
from app.copilot.knowledge_rag import KnowledgeRAGEngine
from app.health.monitor import provider_monitor
from app.models.entities import (
    Alert, Incident, Intersection, SignalCommand, SignalController,
    TrafficMetric, utc_now,
)
from app.traffic.quality_engine import DataQualityEngine

logger = logging.getLogger("trafficintel.copilot.tools")


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _record_citation(table: str, record_id: str, observed_at: Optional[datetime]) -> Dict[str, Any]:
    return {
        "type": "record",
        "table": table,
        "id": record_id,
        "observed_at": observed_at.isoformat() if observed_at else None,
    }


def _standard_citation(title: str, category: str, section: Optional[str] = None) -> Dict[str, Any]:
    return {
        "type": "standard",
        "title": title,
        "category": category,
        "section": section,
        # The indexed text is a summary, not the standard verbatim. Saying so
        # on every citation stops the Copilot implying it quoted the source.
        "fidelity": "INDEXED_SUMMARY_NOT_VERBATIM_TEXT",
    }


# ===========================================================================
# Tools
# ===========================================================================

def find_intersection(db: Session, query: str) -> Dict[str, Any]:
    """Resolves a name or code to a configured junction."""
    if not query:
        return {"status": "NO_DATA", "reason": "NO_QUERY_SUPPLIED", "citations": []}

    needle = query.lower().strip()

    # Match in both directions. A bare "Main St" should find "Main St & 1st
    # Ave", and a full question ("what is the delay at Main St?") should find
    # the junction named inside it. Checking only `needle in name` meant a
    # natural question could never resolve a junction at all.
    def matches_query(inter: Intersection) -> bool:
        name = inter.name.lower()
        code = (inter.code or "").lower()
        if needle in name or (code and needle in code):
            return True
        if name in needle:
            return True
        # Codes are short and distinctive; require a word-ish boundary so a
        # code like "A1" does not match any question containing "a1".
        return bool(code) and len(code) >= 3 and code in needle

    matches = [inter for inter in db.query(Intersection).all() if matches_query(inter)]

    if not matches:
        total = db.query(Intersection).count()
        return {
            "status": "NO_DATA",
            "reason": "NO_MATCHING_INTERSECTION",
            "detail": (
                "No configured junction matches '{}'. {} junction(s) are configured."
                .format(query, total)
            ),
            "citations": [],
        }

    return {
        "status": "OK",
        "matches": [
            {
                "id": inter.id,
                "name": inter.name,
                "code": inter.code,
                "operational_status": inter.operational_status,
                "latitude": inter.latitude,
                "longitude": inter.longitude,
            }
            for inter in matches[:5]
        ],
        "match_count": len(matches),
        "citations": [
            _record_citation("intersections", inter.id, inter.created_at)
            for inter in matches[:5]
        ],
    }


def get_junction_state(db: Session, intersection_id: str) -> Dict[str, Any]:
    """Current controller state and latest telemetry for one junction."""
    inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
    if not inter:
        return {"status": "NO_DATA", "reason": "INTERSECTION_NOT_FOUND", "citations": []}

    controller = (
        db.query(SignalController)
        .filter(SignalController.intersection_id == intersection_id)
        .first()
    )
    metric = (
        db.query(TrafficMetric)
        .filter(TrafficMetric.intersection_id == intersection_id)
        .order_by(TrafficMetric.timestamp.desc())
        .first()
    )

    citations: List[Dict[str, Any]] = [
        _record_citation("intersections", inter.id, inter.created_at)
    ]

    signal_state: Dict[str, Any]
    if controller is None:
        signal_state = {"status": "SIGNAL_CONTROLLER_NOT_CONNECTED"}
    else:
        citations.append(
            _record_citation("signal_controllers", controller.id, controller.last_heartbeat)
        )
        readable = controller.connection_status == "CONNECTED"
        signal_state = {
            "connection_status": controller.connection_status,
            "protocol": controller.protocol,
            "active_phase": controller.active_phase if readable else None,
            "clearing_phases": controller.clearing_phases if readable else None,
            "state_readable": readable,
            "note": (
                None if readable else
                "The controller's phase state cannot be read, so no phase is reported."
            ),
        }

    traffic: Dict[str, Any]
    if metric is None or metric.data_quality == "NO_DATA":
        traffic = {
            "status": "NO_SENSOR_DATA_AVAILABLE",
            "detail": "No telemetry has been recorded for this junction.",
        }
    else:
        quality, age = DataQualityEngine.evaluate_freshness(metric.timestamp)
        citations.append(_record_citation("traffic_metrics", metric.id, metric.timestamp))
        traffic = {
            "vehicle_count": metric.vehicle_count,
            "avg_speed_kph": metric.avg_speed_kph,
            "occupancy_pct": metric.occupancy_pct,
            "queue_length_meters": metric.queue_length_meters,
            "data_quality": quality,
            "age_sec": round(age, 1) if age >= 0 else None,
            "observed_at": metric.timestamp.isoformat(),
            "calculation_method": metric.calculation_method,
        }

    return {
        "status": "OK",
        "intersection": {"id": inter.id, "name": inter.name, "code": inter.code},
        "signal": signal_state,
        "traffic": traffic,
        "citations": citations,
    }


def list_open_incidents(
    db: Session, intersection_id: Optional[str] = None
) -> Dict[str, Any]:
    """Incidents that are not resolved."""
    query = db.query(Incident).filter(
        Incident.status.in_(["DETECTED", "SUSPECTED", "VERIFIED", "ACTIVE", "MITIGATED"])
    )
    if intersection_id:
        query = query.filter(Incident.intersection_id == intersection_id)

    incidents = query.order_by(Incident.detected_at.desc()).limit(25).all()

    if not incidents:
        return {
            "status": "NO_DATA",
            "reason": "NO_OPEN_INCIDENTS",
            "detail": (
                "No open incidents are recorded{}.".format(
                    " at this junction" if intersection_id else ""
                )
            ),
            "citations": [],
        }

    return {
        "status": "OK",
        "count": len(incidents),
        "incidents": [
            {
                "id": inc.id,
                "title": inc.title,
                "type": inc.type,
                "severity": inc.severity,
                "status": inc.status,
                "detected_at": inc.detected_at.isoformat() if inc.detected_at else None,
                "acknowledged_by": inc.acknowledged_by,
                "assigned_to": inc.assigned_to,
                "source": inc.source,
            }
            for inc in incidents
        ],
        "citations": [
            _record_citation("incidents", inc.id, inc.detected_at) for inc in incidents
        ],
    }


def get_performance_measure(
    db: Session, intersection_id: str, measure: str, hours: int = 24
) -> Dict[str, Any]:
    """One ATSPM measure, with its sample size and method."""
    available: Dict[str, Callable] = {
        "throughput": SignalPerformance.throughput,
        "occupancy": SignalPerformance.occupancy,
        "speed": SignalPerformance.average_speed,
        "delay": SignalPerformance.control_delay,
        "split_failures": SignalPerformance.split_failures,
        "arrival_on_green": SignalPerformance.arrival_on_green,
    }
    if measure not in available:
        return {
            "status": "NO_DATA",
            "reason": "UNKNOWN_MEASURE",
            "detail": "Available measures: {}".format(sorted(available)),
            "citations": [],
        }

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=hours)
    result = available[measure](db, intersection_id, start, end)

    return {
        "status": "OK" if result["status"] == "COMPUTED" else "NO_DATA",
        "measure": measure,
        "result": result,
        "citations": [{
            "type": "computation",
            "measure": measure,
            "method": result["method"],
            "sample_size": result["sample_size"],
            "window": "{} to {}".format(start.isoformat(), end.isoformat()),
        }],
    }


def get_recent_commands(
    db: Session, intersection_id: Optional[str] = None, hours: int = 24
) -> Dict[str, Any]:
    """Signal commands issued recently, with their safety outcomes."""
    since = _naive(datetime.now(timezone.utc) - timedelta(hours=hours))
    query = db.query(SignalCommand).filter(SignalCommand.issued_at >= since)

    if intersection_id:
        controller_ids = [
            c.id for c in db.query(SignalController)
            .filter(SignalController.intersection_id == intersection_id).all()
        ]
        if not controller_ids:
            return {
                "status": "NO_DATA",
                "reason": "NO_CONTROLLER_AT_THIS_JUNCTION",
                "citations": [],
            }
        query = query.filter(SignalCommand.controller_id.in_(controller_ids))

    commands = query.order_by(SignalCommand.issued_at.desc()).limit(25).all()

    if not commands:
        return {
            "status": "NO_DATA",
            "reason": "NO_COMMANDS_IN_WINDOW",
            "detail": "No signal commands were issued in the last {} hours.".format(hours),
            "citations": [],
        }

    return {
        "status": "OK",
        "count": len(commands),
        "commands": [
            {
                "id": cmd.id,
                "requested_phase": cmd.requested_phase,
                "command_type": cmd.command_type,
                "status": cmd.status,
                "safety_check_passed": cmd.safety_check_passed,
                "violations": (cmd.safety_report or {}).get("violations", []),
                "issued_at": cmd.issued_at.isoformat() if cmd.issued_at else None,
            }
            for cmd in commands
        ],
        "citations": [
            _record_citation("signal_commands", cmd.id, cmd.issued_at) for cmd in commands
        ],
    }


def get_provider_health(db: Session) -> Dict[str, Any]:
    """Measured health of every provider the platform has called."""
    providers = provider_monitor.all()
    if not providers:
        return {
            "status": "NO_DATA",
            "reason": "NO_PROVIDER_CONTACTED_YET",
            "detail": (
                "No provider has been probed in this process, so no health has been "
                "measured. This is not the same as every provider being healthy."
            ),
            "citations": [],
        }

    return {
        "status": "OK",
        "summary": provider_monitor.summary(),
        "providers": providers,
        "citations": [{
            "type": "measurement",
            "source": "provider_health_monitor",
            "provider": p["key"],
            "observed_at": p["last_checked_at"],
            "sample_size": p["sample_size"],
        } for p in providers],
    }


def get_open_alerts(db: Session) -> Dict[str, Any]:
    """Unacknowledged alerts raised by the rules engine."""
    alerts = (
        db.query(Alert)
        .filter(Alert.is_acknowledged == False)  # noqa: E712
        .order_by(Alert.timestamp.desc())
        .limit(25)
        .all()
    )
    if not alerts:
        return {
            "status": "NO_DATA",
            "reason": "NO_UNACKNOWLEDGED_ALERTS",
            "citations": [],
        }

    return {
        "status": "OK",
        "count": len(alerts),
        "alerts": [
            {
                "id": alert.id,
                "severity": alert.severity,
                "title": alert.title,
                "message": alert.message,
                "occurrence_count": alert.occurrence_count,
                "escalated": alert.escalated,
                "observed": alert.observed,
                "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
            }
            for alert in alerts
        ],
        "citations": [
            _record_citation("alerts", alert.id, alert.timestamp) for alert in alerts
        ],
    }


def search_standards(db: Session, query: str) -> Dict[str, Any]:
    """Searches the indexed engineering standards and SOPs."""
    matches = KnowledgeRAGEngine.search_operational_documentation(db, query, limit=3)
    if not matches:
        return {
            "status": "NO_DATA",
            "reason": "NO_MATCHING_STANDARD",
            "detail": "No indexed standard or SOP matches '{}'.".format(query),
            "citations": [],
        }

    return {
        "status": "OK",
        "count": len(matches),
        "documents": [
            {
                "title": doc["document_title"],
                "category": doc["category"],
                "content": doc["content"],
                "relevance_score": doc["relevance_score"],
            }
            for doc in matches
        ],
        "citations": [
            _standard_citation(doc["document_title"], doc["category"]) for doc in matches
        ],
        "fidelity_warning": (
            "The indexed text summarises these standards; it is not their verbatim "
            "wording. Check the published standard before relying on an exact clause."
        ),
    }


# ===========================================================================
# Registry
# ===========================================================================

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {
    "find_intersection": {
        "function": find_intersection,
        "description": "Resolve a junction name or code to a configured intersection.",
        "parameters": {"query": "Name or code fragment (required)"},
    },
    "get_junction_state": {
        "function": get_junction_state,
        "description": "Current signal state and latest telemetry for one junction.",
        "parameters": {"intersection_id": "Intersection id (required)"},
    },
    "list_open_incidents": {
        "function": list_open_incidents,
        "description": "Incidents that are not resolved, optionally scoped to a junction.",
        "parameters": {"intersection_id": "Optional intersection id"},
    },
    "get_performance_measure": {
        "function": get_performance_measure,
        "description": "One ATSPM performance measure with its sample size and method.",
        "parameters": {
            "intersection_id": "Intersection id (required)",
            "measure": "throughput | occupancy | speed | delay | split_failures | arrival_on_green",
            "hours": "Look-back window in hours (default 24)",
        },
    },
    "get_recent_commands": {
        "function": get_recent_commands,
        "description": "Signal commands issued recently and their safety outcomes.",
        "parameters": {
            "intersection_id": "Optional intersection id",
            "hours": "Look-back window in hours (default 24)",
        },
    },
    "get_provider_health": {
        "function": get_provider_health,
        "description": "Measured health of every provider the platform has called.",
        "parameters": {},
    },
    "get_open_alerts": {
        "function": get_open_alerts,
        "description": "Unacknowledged alerts raised by the rules engine.",
        "parameters": {},
    },
    "search_standards": {
        "function": search_standards,
        "description": "Search indexed engineering standards and SOPs.",
        "parameters": {"query": "Search terms (required)"},
    },
}


def describe_tools() -> List[Dict[str, Any]]:
    return [
        {"name": name, "description": spec["description"], "parameters": spec["parameters"]}
        for name, spec in sorted(TOOL_REGISTRY.items())
    ]


def call_tool(db: Session, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Invokes a tool by name. Unknown tools and bad arguments are reported."""
    spec = TOOL_REGISTRY.get(name)
    if spec is None:
        return {
            "status": "ERROR",
            "reason": "UNKNOWN_TOOL",
            "detail": "No tool named '{}'. Available: {}".format(
                name, sorted(TOOL_REGISTRY)
            ),
            "citations": [],
        }

    try:
        return spec["function"](db, **arguments)
    except TypeError as exc:
        return {
            "status": "ERROR",
            "reason": "BAD_ARGUMENTS",
            "detail": str(exc),
            "expected_parameters": spec["parameters"],
            "citations": [],
        }
    except Exception as exc:  # noqa: BLE001 - surfaced, never silently swallowed
        logger.exception("Copilot tool '%s' failed", name)
        return {
            "status": "ERROR",
            "reason": "TOOL_EXECUTION_FAILED",
            "detail": str(exc),
            "citations": [],
        }
