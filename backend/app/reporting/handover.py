"""TRAFFICINTEL AI - Operator Shift Handover

Auto-generates the summary an outgoing operator hands to the incoming one:
open incidents, SLA standing, degraded providers, unacknowledged alerts,
recent signal commands, and — the part that matters most — **what the platform
could not see during the shift**.

Design decisions:

1. **Blind spots are a first-class section, not a footnote.** The most
   dangerous thing to hand over is a junction nobody was measuring, because
   the incoming operator will read a quiet console as a quiet network. A
   handover that lists only what happened, and not where the platform was
   blind, is the summary that gets someone hurt.

2. **The generated snapshot and the operator's notes are stored separately.**
   Editing never overwrites what the platform reported, so a reader can see
   both.

3. **Sign-off freezes the record.** A handover that can be revised after the
   shift that read it has acted on it is not a record.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.trust import TrustScore
from app.health.monitor import provider_monitor
from app.incidents.lifecycle import IncidentLifecycle
from app.models.entities import (
    Alert, AuditLog, Incident, Intersection, ShiftHandover, SignalCommand,
    SignalController, SignalStateLog, TrafficObservation, utc_now,
)

logger = logging.getLogger("trafficintel.reporting.handover")

DRAFT = "DRAFT"
SIGNED_OFF = "SIGNED_OFF"


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


class ShiftHandoverService:
    """Builds, stores and signs off shift handovers."""

    @classmethod
    def generate_snapshot(
        cls, db: Session, shift_start: datetime, shift_end: datetime
    ) -> Dict[str, Any]:
        """Everything the platform can say about the shift, from stored records."""
        start, end = _naive(shift_start), _naive(shift_end)

        # --- Incidents ---------------------------------------------------
        open_incidents = (
            db.query(Incident)
            .filter(Incident.status.notin_(["RESOLVED"]))
            .order_by(Incident.detected_at.desc())
            .all()
        )
        raised_this_shift = (
            db.query(Incident)
            .filter(Incident.detected_at >= start, Incident.detected_at <= end)
            .count()
        )
        resolved_this_shift = (
            db.query(Incident)
            .filter(Incident.resolved_at.isnot(None),
                    Incident.resolved_at >= start, Incident.resolved_at <= end)
            .count()
        )

        incident_items = []
        for incident in open_incidents:
            sla = IncidentLifecycle.sla_status(incident)
            incident_items.append({
                "id": incident.id,
                "title": incident.title,
                "severity": incident.severity,
                "status": incident.status,
                "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
                "acknowledged": incident.acknowledged_at is not None,
                "assigned_to": incident.assigned_to,
                "sla_status": sla.get("status"),
                "sla_breached": (
                    incident.sla_acknowledge_breached or incident.sla_resolve_breached
                ),
            })

        # --- Alerts ------------------------------------------------------
        unacknowledged = (
            db.query(Alert)
            .filter(Alert.is_acknowledged == False)  # noqa: E712
            .order_by(Alert.timestamp.desc())
            .all()
        )

        # --- Providers ---------------------------------------------------
        providers = provider_monitor.all()
        degraded = [
            p for p in providers if p["state"] in ("DEGRADED", "FAILED")
        ]
        unprobed = [p for p in providers if p["state"] == "UNKNOWN"]

        # --- Signal activity ---------------------------------------------
        commands = (
            db.query(SignalCommand)
            .filter(SignalCommand.issued_at >= start, SignalCommand.issued_at <= end)
            .all()
        )
        rejected = [c for c in commands if not c.safety_check_passed]

        # --- Blind spots: where the platform could not see ----------------
        blind_spots = cls._blind_spots(db, start, end)

        # --- Trust across the network ------------------------------------
        trust = TrustScore.for_network(db, window_minutes=60)

        return {
            "shift_start": shift_start.isoformat(),
            "shift_end": shift_end.isoformat(),
            "generated_at": utc_now().isoformat(),
            "incidents": {
                "open_count": len(open_incidents),
                "raised_this_shift": raised_this_shift,
                "resolved_this_shift": resolved_this_shift,
                "unacknowledged_count": sum(
                    1 for i in incident_items if not i["acknowledged"]
                ),
                "sla_breached_count": sum(1 for i in incident_items if i["sla_breached"]),
                "items": incident_items,
            },
            "alerts": {
                "unacknowledged_count": len(unacknowledged),
                "escalated_count": sum(1 for a in unacknowledged if a.escalated),
                "items": [
                    {
                        "id": alert.id,
                        "severity": alert.severity,
                        "title": alert.title,
                        "occurrence_count": alert.occurrence_count,
                        "escalated": alert.escalated,
                        "raised_at": alert.timestamp.isoformat() if alert.timestamp else None,
                    }
                    for alert in unacknowledged[:20]
                ],
            },
            "providers": {
                "total_known": len(providers),
                "degraded_count": len(degraded),
                "unprobed_count": len(unprobed),
                "degraded": [
                    {
                        "label": p["label"],
                        "kind": p["kind"],
                        "state": p["state"],
                        "error_rate": p["error_rate"],
                        "last_error": p["last_error"],
                        "circuit_state": p["circuit"]["state"],
                    }
                    for p in degraded
                ],
                "unprobed_note": (
                    "{} provider(s) have never been probed. Unknown is not the same "
                    "as working.".format(len(unprobed)) if unprobed else None
                ),
            },
            "signal_activity": {
                "commands_issued": len(commands),
                "commands_executed": sum(1 for c in commands if c.status == "EXECUTED"),
                "rejected_by_safety_engine": len(rejected),
                "rejection_reasons": [
                    violation
                    for command in rejected
                    for violation in (command.safety_report or {}).get("violations", [])
                ][:10],
            },
            "data_coverage": {
                "network_trust_mean_of_rated": trust["mean_score_of_rated"],
                "rated_junctions": trust["rated_count"],
                "unrated_junctions": trust["unrated_count"],
                "by_band": trust["by_band"],
                "ai_gated_count": len(trust["ai_gated_junctions"]),
            },
            "blind_spots": blind_spots,
        }

    # ------------------------------------------------------------------

    @classmethod
    def _blind_spots(
        cls, db: Session, start: datetime, end: datetime
    ) -> Dict[str, Any]:
        """Junctions the platform could not see during the shift.

        This is the section that earns the handover its keep. An incoming
        operator reading a quiet console needs to know which quiet is "nothing
        happened" and which is "nobody was watching".
        """
        junctions = db.query(Intersection).all()
        items: List[Dict[str, Any]] = []

        for junction in junctions:
            observations = (
                db.query(TrafficObservation)
                .filter(
                    TrafficObservation.intersection_id == junction.id,
                    TrafficObservation.timestamp >= start,
                    TrafficObservation.timestamp <= end,
                )
                .count()
            )
            signal_readings = (
                db.query(SignalStateLog)
                .filter(
                    SignalStateLog.intersection_id == junction.id,
                    SignalStateLog.timestamp >= start,
                    SignalStateLog.timestamp <= end,
                )
                .count()
            )
            controller = (
                db.query(SignalController)
                .filter(SignalController.intersection_id == junction.id)
                .first()
            )

            reasons: List[str] = []
            if observations == 0:
                reasons.append("no traffic observations recorded this shift")
            if signal_readings == 0:
                reasons.append("no signal state observed this shift")
            if controller is None:
                reasons.append("no signal controller configured")
            elif controller.connection_status != "CONNECTED":
                reasons.append(
                    "controller is {}".format(controller.connection_status)
                )

            if reasons:
                # A junction with no detectors but a controller we polled all
                # shift is NOT the same as one we could not see at all, and
                # filing both under one heading makes the section cry wolf: an
                # operator who learns that "blind spot" usually means "no loops
                # fitted" will skim past the junction that actually went dark.
                total_blind = observations == 0 and signal_readings == 0
                items.append({
                    "intersection_id": junction.id,
                    "name": junction.name,
                    "code": junction.code,
                    "observations_this_shift": observations,
                    "signal_readings_this_shift": signal_readings,
                    "severity": "TOTAL" if total_blind else "PARTIAL",
                    "observed_channels": [
                        channel for channel, seen in (
                            ("traffic observations", observations > 0),
                            ("signal state", signal_readings > 0),
                        ) if seen
                    ],
                    "reasons": reasons,
                })

        total_blind_items = [i for i in items if i["severity"] == "TOTAL"]
        partial_items = [i for i in items if i["severity"] == "PARTIAL"]

        return {
            "count": len(items),
            "total_blind_count": len(total_blind_items),
            "partially_blind_count": len(partial_items),
            "total_junctions": len(junctions),
            "items": items,
            "why_this_matters": (
                "{} junction(s) were not observed at all this shift: a quiet console "
                "there means the platform was not watching, not that nothing happened, "
                "so treat their absence from the incident list as unknown rather than "
                "clear. A further {} were observed on some channels but not others - "
                "partial coverage, listed so the next shift knows which readings do "
                "not exist rather than reading nothing as normal."
                .format(len(total_blind_items), len(partial_items))
            ),
            "empty_reason": (
                None if items else
                "EVERY_JUNCTION_WAS_OBSERVED_THIS_SHIFT" if junctions
                else "NO_JUNCTIONS_CONFIGURED"
            ),
        }

    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls,
        db: Session,
        outgoing_operator: str,
        shift_hours: int = 8,
        incoming_operator: Optional[str] = None,
    ) -> ShiftHandover:
        end = utc_now()
        start = end - timedelta(hours=shift_hours)

        snapshot = cls.generate_snapshot(db, start, end)

        # Seed pending actions from what actually needs attention, so the
        # operator edits a real list rather than starting from a blank page.
        pending: List[Dict[str, Any]] = []
        for incident in snapshot["incidents"]["items"]:
            if not incident["acknowledged"]:
                pending.append({
                    "kind": "INCIDENT_UNACKNOWLEDGED",
                    "reference": incident["id"],
                    "summary": "Unacknowledged: {}".format(incident["title"]),
                    "source": "AUTO_GENERATED",
                    "done": False,
                })
            elif incident["sla_breached"]:
                pending.append({
                    "kind": "INCIDENT_SLA_BREACHED",
                    "reference": incident["id"],
                    "summary": "SLA breached: {}".format(incident["title"]),
                    "source": "AUTO_GENERATED",
                    "done": False,
                })
        for provider in snapshot["providers"]["degraded"]:
            pending.append({
                "kind": "PROVIDER_DEGRADED",
                "reference": provider["label"],
                "summary": "{} is {}: {}".format(
                    provider["label"], provider["state"], provider["last_error"] or "no detail"
                ),
                "source": "AUTO_GENERATED",
                "done": False,
            })
        # Raised separately, because the two say different things to the
        # incoming operator and only one of them is urgent.
        if snapshot["blind_spots"]["total_blind_count"]:
            pending.append({
                "kind": "DATA_COVERAGE_TOTAL_BLIND",
                "reference": "network",
                "summary": (
                    "{} junction(s) were not observed at all this shift; their quiet "
                    "is unknown, not clear."
                    .format(snapshot["blind_spots"]["total_blind_count"])
                ),
                "source": "AUTO_GENERATED",
                "done": False,
            })
        if snapshot["blind_spots"]["partially_blind_count"]:
            pending.append({
                "kind": "DATA_COVERAGE_PARTIAL",
                "reference": "network",
                "summary": (
                    "{} junction(s) had partial coverage this shift - some channels "
                    "reported and others never have."
                    .format(snapshot["blind_spots"]["partially_blind_count"])
                ),
                "source": "AUTO_GENERATED",
                "done": False,
            })

        handover = ShiftHandover(
            shift_start=_naive(start),
            shift_end=_naive(end),
            outgoing_operator=outgoing_operator,
            incoming_operator=incoming_operator,
            generated_snapshot=snapshot,
            pending_actions=pending,
            status=DRAFT,
        )
        db.add(handover)
        db.add(AuditLog(
            actor_username=outgoing_operator,
            action="CREATE_SHIFT_HANDOVER",
            resource_type="ShiftHandover",
            resource_id=handover.id,
            result="EXECUTED",
            details={
                "shift_hours": shift_hours,
                "open_incidents": snapshot["incidents"]["open_count"],
                "blind_spots": snapshot["blind_spots"]["count"],
                "total_blind": snapshot["blind_spots"]["total_blind_count"],
            },
        ))
        db.commit()
        db.refresh(handover)
        return handover

    @classmethod
    def update_draft(
        cls,
        db: Session,
        handover: ShiftHandover,
        operator_notes: Optional[str],
        pending_actions: Optional[List[Dict[str, Any]]],
        editor: str,
    ) -> ShiftHandover:
        """Edits a draft. The generated snapshot is never touched."""
        if handover.status == SIGNED_OFF:
            raise ValueError(
                "This handover was signed off at {}. A handover the next shift has "
                "already read cannot be revised; create a new one instead."
                .format(handover.signed_off_at)
            )

        if operator_notes is not None:
            handover.operator_notes = operator_notes
        if pending_actions is not None:
            handover.pending_actions = pending_actions

        db.add(AuditLog(
            actor_username=editor,
            action="UPDATE_SHIFT_HANDOVER",
            resource_type="ShiftHandover",
            resource_id=handover.id,
            result="EXECUTED",
            details={"fields": [
                name for name, value in
                (("operator_notes", operator_notes), ("pending_actions", pending_actions))
                if value is not None
            ]},
        ))
        db.commit()
        db.refresh(handover)
        return handover

    @classmethod
    def sign_off(
        cls, db: Session, handover: ShiftHandover, operator: str
    ) -> ShiftHandover:
        if handover.status == SIGNED_OFF:
            raise ValueError("This handover is already signed off.")

        handover.status = SIGNED_OFF
        handover.signed_off_at = utc_now()
        handover.signed_off_by = operator

        db.add(AuditLog(
            actor_username=operator,
            action="SIGN_OFF_SHIFT_HANDOVER",
            resource_type="ShiftHandover",
            resource_id=handover.id,
            result="EXECUTED",
            details={
                "outgoing_operator": handover.outgoing_operator,
                "pending_actions": len(handover.pending_actions or []),
            },
        ))
        db.commit()
        db.refresh(handover)
        return handover

    @classmethod
    def acknowledge(
        cls, db: Session, handover: ShiftHandover, operator: str
    ) -> ShiftHandover:
        """The incoming operator confirms they have read it."""
        if handover.status != SIGNED_OFF:
            raise ValueError(
                "This handover is still a draft. It cannot be acknowledged until the "
                "outgoing operator signs it off."
            )

        handover.acknowledged_at = utc_now()
        handover.acknowledged_by = operator
        handover.incoming_operator = operator

        db.add(AuditLog(
            actor_username=operator,
            action="ACKNOWLEDGE_SHIFT_HANDOVER",
            resource_type="ShiftHandover",
            resource_id=handover.id,
            result="EXECUTED",
            details={"outgoing_operator": handover.outgoing_operator},
        ))
        db.commit()
        db.refresh(handover)
        return handover

    @classmethod
    def serialize(cls, handover: ShiftHandover) -> Dict[str, Any]:
        return {
            "id": handover.id,
            "shift_start": handover.shift_start.isoformat(),
            "shift_end": handover.shift_end.isoformat(),
            "outgoing_operator": handover.outgoing_operator,
            "incoming_operator": handover.incoming_operator,
            "status": handover.status,
            "generated_at": handover.generated_at.isoformat() if handover.generated_at else None,
            "generated_snapshot": handover.generated_snapshot,
            "operator_notes": handover.operator_notes,
            "pending_actions": handover.pending_actions or [],
            "signed_off_at": handover.signed_off_at.isoformat() if handover.signed_off_at else None,
            "signed_off_by": handover.signed_off_by,
            "acknowledged_at": (
                handover.acknowledged_at.isoformat() if handover.acknowledged_at else None
            ),
            "acknowledged_by": handover.acknowledged_by,
            "editable": handover.status == DRAFT,
            "immutability_note": (
                "Signed off and frozen. The next shift may have acted on this; "
                "create a new handover rather than revising it."
                if handover.status == SIGNED_OFF else
                "Draft. The generated snapshot is fixed; notes and pending actions "
                "are editable until sign-off."
            ),
        }
