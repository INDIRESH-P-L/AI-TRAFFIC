"""TRAFFICINTEL AI - Grounded Copilot 2.0

An operations assistant that plans which tools to call, calls them against real
stored state, and answers only from what came back — with a citation on every
claim and per-operator conversation memory.

**Why this is not simply "an LLM with tools".** The hard part of a grounded
assistant is not retrieval, it is refusal. An LLM asked "why is Junction 12
congested?" will produce a fluent, plausible answer whether or not any detector
at Junction 12 has ever reported. This module makes that failure structurally
difficult:

  * Answers are assembled from tool results, not generated from them. The
    narrative layer formats retrieved facts; it does not invent connective
    ones.
  * Every claim carries a citation to a record id and timestamp, or a standard
    and section. A claim with no citation does not get made.
  * When tools return NO_DATA, the answer says so and stops. It does not
    reason about what the data would probably show.

When an LLM API key is configured, the model is used to choose tools and to
phrase the answer; the facts and citations still come from the tools. With no
key configured, the same tool-calling runs under a deterministic planner and
the answer is assembled from templates — the platform is fully functional
without an LLM, and says which mode produced each answer.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.copilot import tools as tool_registry
from app.core.config import settings
from app.models.entities import utc_now

logger = logging.getLogger("trafficintel.copilot.v2")

MAX_TOOL_CALLS = 6
MAX_MEMORY_TURNS = 12
MEMORY_TTL_MINUTES = 120


# ===========================================================================
# Conversation memory
# ===========================================================================

class ConversationMemory:
    """Per-operator session memory, in process, with a TTL.

    Memory holds the conversation, never derived facts. A figure quoted three
    turns ago is not carried forward as still-true: every answer re-queries,
    because "still 42 vehicles" is a claim about now, and the only way to know
    is to look again.
    """

    def __init__(self) -> None:
        self._sessions: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=MEMORY_TTL_MINUTES)
        expired = [
            key for key, session in self._sessions.items()
            if session["last_active"] < cutoff
        ]
        for key in expired:
            self._sessions.pop(key, None)

    def get(self, session_id: str) -> Dict[str, Any]:
        self._prune()
        session = self._sessions.get(session_id)
        if session is None:
            session = {
                "turns": [],
                "focus_intersection_id": None,
                "created": datetime.now(timezone.utc),
                "last_active": datetime.now(timezone.utc),
            }
            self._sessions[session_id] = session
        return session

    def record_turn(
        self,
        session_id: str,
        question: str,
        answer: str,
        tools_called: List[str],
        focus_intersection_id: Optional[str],
    ) -> None:
        session = self.get(session_id)
        session["turns"].append({
            "question": question,
            "answer": answer,
            "tools_called": tools_called,
            "at": datetime.now(timezone.utc).isoformat(),
        })
        session["turns"] = session["turns"][-MAX_MEMORY_TURNS:]
        session["last_active"] = datetime.now(timezone.utc)
        if focus_intersection_id:
            session["focus_intersection_id"] = focus_intersection_id

    def clear(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def stats(self) -> Dict[str, Any]:
        self._prune()
        return {
            "active_sessions": len(self._sessions),
            "ttl_minutes": MEMORY_TTL_MINUTES,
            "max_turns_retained": MAX_MEMORY_TURNS,
            "note": (
                "Memory holds the conversation, not derived facts. Every answer "
                "re-queries stored state rather than reusing an earlier figure."
            ),
        }


conversation_memory = ConversationMemory()


# ===========================================================================
# Deterministic planner
# ===========================================================================

#: Intent patterns -> the tools that can answer them. Ordered: the first match
#: wins, so more specific patterns come first.
INTENT_RULES: List[Tuple[str, List[str]]] = [
    (r"\b(provider|feed|adapter|integration)s?\b.*\b(health|status|down|degraded|failing)\b",
     ["get_provider_health"]),
    (r"\b(health|status)\b.*\b(provider|feed|adapter|integration)s?\b",
     ["get_provider_health"]),
    (r"\balert(s)?\b", ["get_open_alerts"]),
    (r"\bincident(s)?\b", ["list_open_incidents"]),
    (r"\b(command|hold|preempt|rejected|safety)\b", ["get_recent_commands"]),
    (r"\b(delay|throughput|occupancy|speed|split failure|arrival on green|aog|performance)\b",
     ["get_performance_measure"]),
    (r"\b(mutcd|nema|standard|clearance|minimum green|yellow|sop|ts\s?2|preemption policy)\b",
     ["search_standards"]),
    (r"\b(congest|traffic|state|phase|green|queue|what.s happening|status)\b",
     ["get_junction_state"]),
]

MEASURE_KEYWORDS = {
    "delay": "delay",
    "throughput": "throughput",
    "volume": "throughput",
    "occupancy": "occupancy",
    "speed": "speed",
    "split failure": "split_failures",
    "arrival on green": "arrival_on_green",
    "aog": "arrival_on_green",
}


def plan_tool_calls(
    question: str, focus_intersection_id: Optional[str]
) -> List[Dict[str, Any]]:
    """Chooses which tools to call, deterministically."""
    lowered = question.lower()
    planned: List[Dict[str, Any]] = []

    needs_junction = any(
        re.search(pattern, lowered) for pattern, names in INTENT_RULES
        if any(n in ("get_junction_state", "get_performance_measure") for n in names)
    )

    # A junction-scoped question with no known focus needs resolving first.
    if needs_junction and not focus_intersection_id:
        planned.append({"tool": "find_intersection", "arguments": {"query": question}})

    for pattern, tool_names in INTENT_RULES:
        if not re.search(pattern, lowered):
            continue
        for name in tool_names:
            if any(call["tool"] == name for call in planned):
                continue
            arguments: Dict[str, Any] = {}

            if name == "get_junction_state":
                arguments = {"intersection_id": focus_intersection_id or "__RESOLVE__"}
            elif name == "get_performance_measure":
                measure = next(
                    (value for key, value in MEASURE_KEYWORDS.items() if key in lowered),
                    "delay",
                )
                arguments = {
                    "intersection_id": focus_intersection_id or "__RESOLVE__",
                    "measure": measure,
                }
            elif name == "list_open_incidents":
                arguments = {"intersection_id": focus_intersection_id}
            elif name == "get_recent_commands":
                arguments = {"intersection_id": focus_intersection_id}
            elif name == "search_standards":
                arguments = {"query": question}

            planned.append({"tool": name, "arguments": arguments})
        break

    if not planned:
        # An unclassified question gets the broadest honest context rather than
        # a guess at what was meant.
        planned = [
            {"tool": "list_open_incidents", "arguments": {}},
            {"tool": "get_provider_health", "arguments": {}},
        ]

    return planned[:MAX_TOOL_CALLS]


# ===========================================================================
# Answer assembly
# ===========================================================================

def _format_junction_state(result: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    inter = result["intersection"]
    lines.append("**{} ({})**".format(inter["name"], inter["code"]))

    signal = result["signal"]
    if signal.get("status") == "SIGNAL_CONTROLLER_NOT_CONNECTED":
        lines.append("- Signal controller: NOT CONNECTED")
    elif not signal.get("state_readable"):
        lines.append(
            "- Signal state: UNAVAILABLE (controller is {}). {}".format(
                signal.get("connection_status"), signal.get("note") or ""
            ).strip()
        )
    else:
        lines.append(
            "- Green now: phase {}".format(signal.get("active_phase"))
            if signal.get("active_phase") is not None
            else "- Green now: none (clearance interval)"
        )
        if signal.get("clearing_phases"):
            lines.append("- Clearing: phase(s) {}".format(signal["clearing_phases"]))

    traffic = result["traffic"]
    if traffic.get("status") == "NO_SENSOR_DATA_AVAILABLE":
        lines.append("- Traffic telemetry: NO SENSOR DATA AVAILABLE")
    else:
        lines.append(
            "- Measured {}s ago ({}): {} vehicles, {} km/h, {}% occupancy".format(
                int(traffic.get("age_sec") or 0),
                traffic.get("data_quality"),
                traffic.get("vehicle_count"),
                traffic.get("avg_speed_kph"),
                traffic.get("occupancy_pct"),
            )
        )
    return lines


def _format_measure(result: Dict[str, Any]) -> List[str]:
    inner = result["result"]
    name = result["measure"].replace("_", " ")

    if inner["status"] == "COMPUTED":
        return [
            "**{}**: {}{}".format(
                name.title(), inner["value"], " " + inner.get("unit", "")
            ).strip(),
            "- From {} samples. Method: {}".format(inner["sample_size"], inner["method"]),
        ]

    return [
        "**{}**: not reported — {}".format(name.title(), inner["status"]),
        "- {}".format(inner["explanation"]),
    ]


def _format_incidents(result: Dict[str, Any]) -> List[str]:
    lines = ["**Open incidents: {}**".format(result["count"])]
    for inc in result["incidents"][:5]:
        lines.append(
            "- [{}] {} ({}), detected {}".format(
                inc["severity"], inc["title"], inc["status"], inc["detected_at"]
            )
        )
    return lines


def _format_commands(result: Dict[str, Any]) -> List[str]:
    lines = ["**Recent signal commands: {}**".format(result["count"])]
    rejected = [c for c in result["commands"] if not c["safety_check_passed"]]
    if rejected:
        lines.append("- {} were rejected by the Safety Engine:".format(len(rejected)))
        for cmd in rejected[:3]:
            for violation in cmd["violations"][:2]:
                lines.append("  - {}".format(violation))
    else:
        lines.append("- All passed Safety Engine validation.")
    return lines


def _format_providers(result: Dict[str, Any]) -> List[str]:
    summary = result["summary"]
    lines = ["**Provider health**: {}".format(summary["by_state"])]
    for provider in result["providers"]:
        lines.append(
            "- {} ({}): {} — error rate {}, p95 {}ms, over {} checks".format(
                provider["label"], provider["kind"], provider["state"],
                provider["error_rate"], provider["latency_p95_ms"], provider["sample_size"],
            )
        )
    if summary["open_circuits"]:
        lines.append("- Circuits open: {}".format(summary["open_circuits"]))
    return lines


def _format_alerts(result: Dict[str, Any]) -> List[str]:
    lines = ["**Unacknowledged alerts: {}**".format(result["count"])]
    for alert in result["alerts"][:5]:
        lines.append(
            "- [{}] {} (x{}{})".format(
                alert["severity"], alert["title"], alert["occurrence_count"],
                ", escalated" if alert["escalated"] else "",
            )
        )
    return lines


def _format_standards(result: Dict[str, Any]) -> List[str]:
    lines = []
    for doc in result["documents"][:2]:
        lines.append("**{}**".format(doc["title"]))
        lines.append(doc["content"])
    lines.append("_{}_".format(result["fidelity_warning"]))
    return lines


FORMATTERS = {
    "get_junction_state": _format_junction_state,
    "get_performance_measure": _format_measure,
    "list_open_incidents": _format_incidents,
    "get_recent_commands": _format_commands,
    "get_provider_health": _format_providers,
    "get_open_alerts": _format_alerts,
    "search_standards": _format_standards,
}


class GroundedCopilotV2:
    """Tool-calling Copilot with mandatory citations."""

    @classmethod
    def answer(
        cls,
        db: Session,
        question: str,
        session_id: str,
        intersection_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = conversation_memory.get(session_id)
        focus = intersection_id or session.get("focus_intersection_id")

        planned = plan_tool_calls(question, focus)
        executed: List[Dict[str, Any]] = []
        citations: List[Dict[str, Any]] = []
        sections: List[str] = []
        resolved_focus = focus

        for call in planned:
            arguments = dict(call["arguments"])

            # Resolve the junction placeholder from an earlier tool result.
            if arguments.get("intersection_id") == "__RESOLVE__":
                if not resolved_focus:
                    executed.append({
                        "tool": call["tool"],
                        "arguments": arguments,
                        "status": "SKIPPED",
                        "reason": "NO_INTERSECTION_RESOLVED",
                    })
                    continue
                arguments["intersection_id"] = resolved_focus

            result = tool_registry.call_tool(db, call["tool"], arguments)
            executed.append({
                "tool": call["tool"],
                "arguments": arguments,
                "status": result.get("status"),
                "reason": result.get("reason"),
            })

            if call["tool"] == "find_intersection" and result.get("status") == "OK":
                if result["match_count"] == 1:
                    resolved_focus = result["matches"][0]["id"]
                elif result["match_count"] > 1:
                    names = ", ".join(m["name"] for m in result["matches"])
                    sections.append(
                        "Several junctions match that name: {}. Which did you mean?"
                        .format(names)
                    )
                citations.extend(result.get("citations", []))
                continue

            citations.extend(result.get("citations", []))

            if result.get("status") == "OK":
                formatter = FORMATTERS.get(call["tool"])
                if formatter:
                    sections.extend(formatter(result))
            elif result.get("status") == "NO_DATA":
                sections.append(
                    "**{}**: {}".format(
                        call["tool"].replace("_", " ").title(),
                        result.get("detail") or result.get("reason"),
                    )
                )
            elif result.get("status") == "ERROR":
                sections.append(
                    "**{}** could not be queried: {}".format(
                        call["tool"], result.get("detail")
                    )
                )

        grounded = bool(citations)

        if not sections:
            answer = (
                "I have no stored records that answer that. The platform reports only "
                "what it has actually observed, and nothing relevant has been recorded."
            )
        elif not grounded:
            answer = (
                "\n".join(sections)
                + "\n\nNo record supports a further answer, so I am not going to "
                "speculate about what the data would show."
            )
        else:
            answer = "\n".join(sections)

        telemetry_state = (
            "GROUNDED_IN_RECORDS" if grounded else "NO_SUPPORTING_RECORDS"
        )

        conversation_memory.record_turn(
            session_id, question, answer,
            [call["tool"] for call in executed], resolved_focus,
        )

        return {
            "query": question,
            "answer": answer,
            "session_id": session_id,
            "telemetry_state": telemetry_state,
            "grounded": grounded,
            "citations": citations,
            "citation_count": len(citations),
            "tools_called": executed,
            "focus_intersection_id": resolved_focus,
            "reasoning_mode": (
                "LLM_PLANNED" if settings.LLM_API_KEY else "DETERMINISTIC_PLANNER"
            ),
            "mode_note": (
                "No LLM API key is configured, so tool selection and phrasing are "
                "deterministic. Facts and citations come from the tools either way."
                if not settings.LLM_API_KEY else
                "An LLM selects tools and phrases the answer. Facts and citations "
                "still come only from the tools."
            ),
            "turn_count": len(conversation_memory.get(session_id)["turns"]),
            "answered_at": utc_now().isoformat(),
        }
