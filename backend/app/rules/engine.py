"""TRAFFICINTEL AI - Alert & Rules Engine

Evaluates operator-defined rules against real stored state and raises alerts
with dedupe, cooldown and escalation.

The governing rule, and the reason this file is careful:

    **A condition that cannot be evaluated is INSUFFICIENT_DATA, never false.**

"The detector has been silent for 90 seconds" and "no detector has ever
reported here" look identical to a naive `last_seen < now - 90s` test, but they
mean completely different things. The first is an alarm. The second is a
configuration gap, and firing an alarm for it teaches operators to ignore the
alarm that matters. Every condition below distinguishes them explicitly, and
every evaluation records the values it actually saw so a firing can be
explained afterwards.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.events import topics
from app.events.bus import event_bus
from app.health.monitor import provider_monitor
from app.models.entities import (
    Alert, AlertRule, Intersection, RuleEvaluation, Sensor, SignalCommand,
    SignalController, TrafficMetric, utc_now,
)

logger = logging.getLogger("trafficintel.rules")

# Evaluation outcomes
MATCHED = "MATCHED"
NOT_MATCHED = "NOT_MATCHED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
SUPPRESSED_COOLDOWN = "SUPPRESSED_COOLDOWN"
SUPPRESSED_DUPLICATE = "SUPPRESSED_DUPLICATE"

# Condition types
DETECTOR_SILENT = "DETECTOR_SILENT"
OCCUPANCY_SUSTAINED = "OCCUPANCY_SUSTAINED"
CONTROLLER_STATE = "CONTROLLER_STATE"
PROVIDER_DEGRADED = "PROVIDER_DEGRADED"
COMMAND_REJECTED = "COMMAND_REJECTED"

CONDITION_TYPES = {
    DETECTOR_SILENT: {
        "label": "Detector silent",
        "description": "A detector that has reported before has stopped reporting.",
        "parameters": {
            "silent_for_sec": "Seconds without an observation before the rule matches (required)",
        },
    },
    OCCUPANCY_SUSTAINED: {
        "label": "Sustained occupancy",
        "description": "Measured occupancy stays above a threshold for a duration.",
        "parameters": {
            "occupancy_pct": "Occupancy threshold, 0-100 (required)",
            "sustained_for_sec": "How long it must stay above the threshold (required)",
        },
    },
    CONTROLLER_STATE: {
        "label": "Controller state",
        "description": "A signal controller enters one of the listed connection states.",
        "parameters": {
            "states": "List of states that match, e.g. ['DISCONNECTED', 'REACHABLE'] (required)",
        },
    },
    PROVIDER_DEGRADED: {
        "label": "Provider degraded",
        "description": "A provider's measured health enters DEGRADED or FAILED.",
        "parameters": {
            "states": "List of health states that match (default ['DEGRADED', 'FAILED'])",
            "provider_kind": "Optional filter: CONTROLLER, CAMERA, SENSOR, WEATHER",
        },
    },
    COMMAND_REJECTED: {
        "label": "Signal command rejected",
        "description": "Signal commands were rejected by the Safety Engine.",
        "parameters": {
            "count": "Number of rejections within the window (default 1)",
            "window_sec": "Look-back window in seconds (default 300)",
        },
    },
}


def _naive(dt: datetime) -> datetime:
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


class RuleMatch:
    """One subject that matched (or could not be evaluated)."""

    def __init__(
        self,
        outcome: str,
        subject_type: str,
        subject_id: Optional[str],
        subject_label: str,
        observed: Dict[str, Any],
        explanation: str,
    ):
        self.outcome = outcome
        self.subject_type = subject_type
        self.subject_id = subject_id
        self.subject_label = subject_label
        self.observed = observed
        self.explanation = explanation


class RulesEngine:
    """Evaluates rules and raises deduplicated, cooled-down alerts."""

    # ------------------------------------------------------------------
    # Conditions
    # ------------------------------------------------------------------

    @classmethod
    def _eval_detector_silent(
        cls, db: Session, rule: AlertRule
    ) -> List[RuleMatch]:
        threshold = rule.parameters.get("silent_for_sec")
        if not threshold:
            return [RuleMatch(
                INSUFFICIENT_DATA, "Rule", rule.id, rule.name,
                {"missing_parameter": "silent_for_sec"},
                "Rule is misconfigured: silent_for_sec was not set.",
            )]

        query = db.query(Sensor)
        if rule.intersection_id:
            query = query.filter(Sensor.intersection_id == rule.intersection_id)

        now = datetime.now(timezone.utc)
        matches: List[RuleMatch] = []

        for sensor in query.all():
            last_seen = _as_utc(sensor.last_observation_timestamp)

            if last_seen is None:
                # Never reported. This is a configuration gap, not a detector
                # that went quiet, and conflating them would bury real alarms.
                matches.append(RuleMatch(
                    INSUFFICIENT_DATA, "Sensor", sensor.id, sensor.name,
                    {"last_observation_at": None, "threshold_sec": threshold},
                    (
                        "Detector '{}' has never reported an observation, so it cannot "
                        "be said to have fallen silent. Connect it, or remove it from "
                        "the configuration.".format(sensor.name)
                    ),
                ))
                continue

            silent_for = (now - last_seen).total_seconds()
            observed = {
                "last_observation_at": last_seen.isoformat(),
                "silent_for_sec": round(silent_for, 1),
                "threshold_sec": threshold,
            }

            if silent_for > threshold:
                matches.append(RuleMatch(
                    MATCHED, "Sensor", sensor.id, sensor.name, observed,
                    "Detector '{}' last reported {:.0f}s ago, exceeding the {}s "
                    "silence threshold.".format(sensor.name, silent_for, threshold),
                ))
            else:
                matches.append(RuleMatch(
                    NOT_MATCHED, "Sensor", sensor.id, sensor.name, observed,
                    "Detector '{}' reported {:.0f}s ago, within the {}s threshold.".format(
                        sensor.name, silent_for, threshold
                    ),
                ))

        return matches

    @classmethod
    def _eval_occupancy_sustained(
        cls, db: Session, rule: AlertRule
    ) -> List[RuleMatch]:
        threshold = rule.parameters.get("occupancy_pct")
        window = rule.parameters.get("sustained_for_sec")
        if threshold is None or window is None:
            return [RuleMatch(
                INSUFFICIENT_DATA, "Rule", rule.id, rule.name,
                {"missing_parameters": ["occupancy_pct", "sustained_for_sec"]},
                "Rule is misconfigured: occupancy_pct and sustained_for_sec are required.",
            )]

        query = db.query(Intersection)
        if rule.intersection_id:
            query = query.filter(Intersection.id == rule.intersection_id)

        since = _naive(datetime.now(timezone.utc) - timedelta(seconds=window))
        matches: List[RuleMatch] = []

        for inter in query.all():
            samples = (
                db.query(TrafficMetric)
                .filter(
                    TrafficMetric.intersection_id == inter.id,
                    TrafficMetric.timestamp >= since,
                    TrafficMetric.occupancy_pct.isnot(None),
                )
                .order_by(TrafficMetric.timestamp.asc())
                .all()
            )

            if not samples:
                matches.append(RuleMatch(
                    INSUFFICIENT_DATA, "Intersection", inter.id, inter.name,
                    {"samples_in_window": 0, "window_sec": window},
                    (
                        "No occupancy was measured at '{}' in the last {}s, so it cannot "
                        "be said to be above or below {}%.".format(inter.name, window, threshold)
                    ),
                ))
                continue

            values = [s.occupancy_pct for s in samples]
            above = [v for v in values if v > threshold]
            observed = {
                "samples_in_window": len(samples),
                "window_sec": window,
                "threshold_pct": threshold,
                "min_pct": round(min(values), 1),
                "max_pct": round(max(values), 1),
                "samples_above_threshold": len(above),
                "oldest_sample_at": samples[0].timestamp.isoformat(),
                "newest_sample_at": samples[-1].timestamp.isoformat(),
            }

            # Sustained means EVERY sample in the window was above threshold.
            # "Some samples were high" is a different, weaker claim.
            if len(above) == len(values):
                matches.append(RuleMatch(
                    MATCHED, "Intersection", inter.id, inter.name, observed,
                    "Occupancy at '{}' stayed above {}% across all {} samples in the "
                    "last {}s (min {}%).".format(
                        inter.name, threshold, len(values), window, observed["min_pct"]
                    ),
                ))
            else:
                matches.append(RuleMatch(
                    NOT_MATCHED, "Intersection", inter.id, inter.name, observed,
                    "Occupancy at '{}' dropped below {}% during the window ({} of {} "
                    "samples above).".format(
                        inter.name, threshold, len(above), len(values)
                    ),
                ))

        return matches

    @classmethod
    def _eval_controller_state(
        cls, db: Session, rule: AlertRule
    ) -> List[RuleMatch]:
        states = rule.parameters.get("states")
        if not states:
            return [RuleMatch(
                INSUFFICIENT_DATA, "Rule", rule.id, rule.name,
                {"missing_parameter": "states"},
                "Rule is misconfigured: states was not set.",
            )]

        query = db.query(SignalController)
        if rule.intersection_id:
            query = query.filter(SignalController.intersection_id == rule.intersection_id)

        matches: List[RuleMatch] = []
        for controller in query.all():
            observed = {
                "connection_status": controller.connection_status,
                "watched_states": states,
                "last_heartbeat_at": (
                    controller.last_heartbeat.isoformat() if controller.last_heartbeat else None
                ),
                "active_phase": controller.active_phase,
            }
            if controller.connection_status in states:
                matches.append(RuleMatch(
                    MATCHED, "SignalController", controller.id, controller.name, observed,
                    "Controller '{}' is {}.".format(
                        controller.name, controller.connection_status
                    ),
                ))
            else:
                matches.append(RuleMatch(
                    NOT_MATCHED, "SignalController", controller.id, controller.name, observed,
                    "Controller '{}' is {}, which is not a watched state.".format(
                        controller.name, controller.connection_status
                    ),
                ))
        return matches

    @classmethod
    def _eval_provider_degraded(
        cls, db: Session, rule: AlertRule
    ) -> List[RuleMatch]:
        watched = rule.parameters.get("states") or ["DEGRADED", "FAILED"]
        kind_filter = rule.parameters.get("provider_kind")

        providers = provider_monitor.all()
        if not providers:
            return [RuleMatch(
                INSUFFICIENT_DATA, "Provider", None, "providers",
                {"providers_known": 0},
                "No provider has been contacted yet, so none can be reported degraded.",
            )]

        matches: List[RuleMatch] = []
        for snapshot in providers:
            if kind_filter and snapshot["kind"] != kind_filter:
                continue

            observed = {
                "state": snapshot["state"],
                "watched_states": watched,
                "error_rate": snapshot["error_rate"],
                "latency_p95_ms": snapshot["latency_p95_ms"],
                "circuit_state": snapshot["circuit"]["state"],
                "last_error": snapshot["last_error"],
            }

            if snapshot["state"] == "UNKNOWN":
                matches.append(RuleMatch(
                    INSUFFICIENT_DATA, "Provider", snapshot["key"], snapshot["label"],
                    observed,
                    "Provider '{}' has not been probed, so its health is unknown "
                    "rather than degraded.".format(snapshot["label"]),
                ))
            elif snapshot["state"] in watched:
                matches.append(RuleMatch(
                    MATCHED, "Provider", snapshot["key"], snapshot["label"], observed,
                    "Provider '{}' is {} (error rate {}, p95 {}ms).".format(
                        snapshot["label"], snapshot["state"],
                        snapshot["error_rate"], snapshot["latency_p95_ms"],
                    ),
                ))
            else:
                matches.append(RuleMatch(
                    NOT_MATCHED, "Provider", snapshot["key"], snapshot["label"], observed,
                    "Provider '{}' is {}.".format(snapshot["label"], snapshot["state"]),
                ))
        return matches

    @classmethod
    def _eval_command_rejected(
        cls, db: Session, rule: AlertRule
    ) -> List[RuleMatch]:
        count_threshold = rule.parameters.get("count", 1)
        window = rule.parameters.get("window_sec", 300)
        since = _naive(datetime.now(timezone.utc) - timedelta(seconds=window))

        query = db.query(SignalCommand).filter(
            SignalCommand.issued_at >= since,
            SignalCommand.status == "REJECTED",
        )
        if rule.intersection_id:
            controller_ids = [
                c.id for c in db.query(SignalController)
                .filter(SignalController.intersection_id == rule.intersection_id).all()
            ]
            if not controller_ids:
                return [RuleMatch(
                    INSUFFICIENT_DATA, "Intersection", rule.intersection_id, "intersection",
                    {"controllers": 0},
                    "No controller is configured at the scoped intersection.",
                )]
            query = query.filter(SignalCommand.controller_id.in_(controller_ids))

        rejected = query.all()
        observed = {
            "rejections_in_window": len(rejected),
            "window_sec": window,
            "threshold": count_threshold,
            "reasons": [
                v for cmd in rejected
                for v in (cmd.safety_report or {}).get("violations", [])
            ][:5],
        }

        subject_id = rule.intersection_id or "network"
        if len(rejected) >= count_threshold:
            return [RuleMatch(
                MATCHED, "SignalCommand", subject_id, "safety rejections", observed,
                "{} signal command(s) were rejected by the Safety Engine in the last "
                "{}s.".format(len(rejected), window),
            )]
        return [RuleMatch(
            NOT_MATCHED, "SignalCommand", subject_id, "safety rejections", observed,
            "{} rejection(s) in the last {}s, below the threshold of {}.".format(
                len(rejected), window, count_threshold
            ),
        )]

    #: Condition type -> evaluator method NAME. Storing the name rather than
    #: the function avoids binding a classmethod object at class-definition
    #: time, which would swallow `cls` and silently shift every argument.
    _EVALUATORS = {
        DETECTOR_SILENT: "_eval_detector_silent",
        OCCUPANCY_SUSTAINED: "_eval_occupancy_sustained",
        CONTROLLER_STATE: "_eval_controller_state",
        PROVIDER_DEGRADED: "_eval_provider_degraded",
        COMMAND_REJECTED: "_eval_command_rejected",
    }

    # ------------------------------------------------------------------
    # Evaluation & alert raising
    # ------------------------------------------------------------------

    @classmethod
    def evaluate_rule(
        cls, db: Session, rule: AlertRule, dry_run: bool = False
    ) -> Dict[str, Any]:
        """Evaluates one rule. With dry_run, records and raises nothing."""
        evaluator_name = cls._EVALUATORS.get(rule.condition_type)
        if evaluator_name is None:
            return {
                "rule_id": rule.id,
                "rule_name": rule.name,
                "error": "UNKNOWN_CONDITION_TYPE",
                "detail": "Condition type '{}' is not implemented.".format(rule.condition_type),
                "results": [],
            }

        matches = getattr(cls, evaluator_name)(db, rule)
        now = utc_now()
        results: List[Dict[str, Any]] = []

        for match in matches:
            outcome = match.outcome
            alert_id: Optional[str] = None

            if outcome == MATCHED and not dry_run:
                alert_id, outcome = cls._raise_alert(db, rule, match, now)

            if not dry_run:
                db.add(RuleEvaluation(
                    rule_id=rule.id,
                    subject_type=match.subject_type,
                    subject_id=match.subject_id,
                    outcome=outcome,
                    observed=match.observed,
                    explanation=match.explanation,
                    alert_id=alert_id,
                    evaluated_at=now,
                ))

            results.append({
                "outcome": outcome,
                "subject_type": match.subject_type,
                "subject_id": match.subject_id,
                "subject_label": match.subject_label,
                "observed": match.observed,
                "explanation": match.explanation,
                "alert_id": alert_id,
            })

        if not dry_run:
            rule.last_evaluated_at = now
            db.commit()

        event_bus.publish(topics.RULE_EVALUATED, {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "dry_run": dry_run,
            "matched": sum(1 for r in results if r["outcome"] == MATCHED),
            "insufficient_data": sum(1 for r in results if r["outcome"] == INSUFFICIENT_DATA),
            "evaluated": len(results),
        })

        return {
            "rule_id": rule.id,
            "rule_name": rule.name,
            "condition_type": rule.condition_type,
            "dry_run": dry_run,
            "evaluated_at": now.isoformat(),
            "subjects_evaluated": len(results),
            "matched": sum(1 for r in results if r["outcome"] == MATCHED),
            "insufficient_data": sum(1 for r in results if r["outcome"] == INSUFFICIENT_DATA),
            "results": results,
        }

    @classmethod
    def _raise_alert(
        cls, db: Session, rule: AlertRule, match: RuleMatch, now: datetime
    ) -> Tuple[Optional[str], str]:
        """Creates or folds into an alert. Returns (alert_id, final_outcome)."""
        dedupe_key = "{}:{}:{}".format(rule.id, match.subject_type, match.subject_id or "-")

        existing = (
            db.query(Alert)
            .filter(Alert.dedupe_key == dedupe_key, Alert.is_acknowledged == False)  # noqa: E712
            .order_by(Alert.timestamp.desc())
            .first()
        )

        if existing:
            last_at = _as_utc(existing.last_occurrence_at or existing.timestamp)
            within_cooldown = (
                last_at is not None
                and (_as_utc(now) - last_at).total_seconds() < rule.cooldown_sec
            )

            # An unacknowledged alert for the same subject is the same alert.
            # Counting occurrences keeps the operator informed that it is still
            # happening without producing a wall of identical rows.
            existing.occurrence_count += 1
            existing.last_occurrence_at = now
            existing.observed = match.observed
            existing.message = match.explanation
            db.flush()

            return existing.id, SUPPRESSED_COOLDOWN if within_cooldown else SUPPRESSED_DUPLICATE

        alert = Alert(
            severity=rule.severity,
            original_severity=rule.severity,
            category=rule.condition_type,
            title="{}: {}".format(rule.name, match.subject_label),
            message=match.explanation,
            resource_type=match.subject_type,
            resource_id=match.subject_id,
            rule_id=rule.id,
            dedupe_key=dedupe_key,
            observed=match.observed,
            occurrence_count=1,
            last_occurrence_at=now,
            timestamp=now,
        )
        db.add(alert)
        db.flush()

        rule.last_fired_at = now
        rule.fire_count += 1

        event_bus.publish(topics.ALERT_RAISED, {
            "alert_id": alert.id,
            "rule_id": rule.id,
            "rule_name": rule.name,
            "severity": alert.severity,
            "title": alert.title,
            "message": alert.message,
            "subject_type": match.subject_type,
            "subject_id": match.subject_id,
            "observed": match.observed,
        })

        # Delivery is attempted after the alert exists, so a webhook failure
        # never loses the alert itself.
        from app.rules.delivery import deliver_alert
        deliver_alert(db, rule, alert)

        return alert.id, MATCHED

    @classmethod
    def evaluate_all(cls, db: Session) -> Dict[str, Any]:
        """Evaluates every enabled rule, then applies escalation."""
        rules = db.query(AlertRule).filter(AlertRule.enabled == True).all()  # noqa: E712
        evaluations = [cls.evaluate_rule(db, rule) for rule in rules]
        escalated = cls.apply_escalations(db)

        return {
            "evaluated_at": utc_now().isoformat(),
            "rules_evaluated": len(evaluations),
            "alerts_raised": sum(e.get("matched", 0) for e in evaluations),
            "escalated": escalated,
            "evaluations": evaluations,
            "empty_reason": None if rules else "NO_ENABLED_RULES_CONFIGURED",
        }

    @classmethod
    def apply_escalations(cls, db: Session) -> List[Dict[str, Any]]:
        """Raises the severity of alerts left unacknowledged past their window."""
        now = utc_now()
        escalated: List[Dict[str, Any]] = []

        candidates = (
            db.query(Alert)
            .filter(
                Alert.is_acknowledged == False,  # noqa: E712
                Alert.escalated == False,        # noqa: E712
                Alert.rule_id.isnot(None),
            )
            .all()
        )

        for alert in candidates:
            rule = db.query(AlertRule).filter(AlertRule.id == alert.rule_id).first()
            if not rule or not rule.escalate_after_sec or not rule.escalate_to_severity:
                continue

            raised_at = _as_utc(alert.timestamp)
            if raised_at is None:
                continue

            waiting_for = (_as_utc(now) - raised_at).total_seconds()
            if waiting_for < rule.escalate_after_sec:
                continue

            previous = alert.severity
            alert.severity = rule.escalate_to_severity
            alert.escalated = True
            alert.escalated_at = now

            event_bus.publish(topics.ALERT_ESCALATED, {
                "alert_id": alert.id,
                "rule_id": rule.id,
                "from_severity": previous,
                "to_severity": alert.severity,
                "unacknowledged_for_sec": round(waiting_for, 1),
            })

            escalated.append({
                "alert_id": alert.id,
                "from_severity": previous,
                "to_severity": alert.severity,
                "unacknowledged_for_sec": round(waiting_for, 1),
            })

        if escalated:
            db.commit()
        return escalated
