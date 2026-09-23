"""TRAFFICINTEL AI - Incident Lifecycle Service

Detection -> triage -> assignment -> resolution, with SLA timers, an
append-only timeline, and evidence that traces back to recorded observations.

Three decisions worth stating:

1. **SLA targets are copied onto the incident when it is created**, not read
   from policy at report time. Otherwise tightening a policy next month would
   retroactively turn last month's met targets into breaches, and an
   operations report that changes its own history is not a report.

2. **The timeline is append-only.** There is no update or delete path. A
   correction is a new entry that references the one it corrects, so a post
   -incident review can see both what was believed at the time and what was
   later established.

3. **Evidence must reference something the platform recorded.** A camera frame
   it ingested, a sensor observation it stored, a command it issued. There is
   no free-form attachment path: an "evidence" item nobody can trace back to a
   recorded observation is an assertion wearing evidence's clothes.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.events import topics
from app.events.bus import event_bus
from app.incidents.incident_engine import IncidentLifecycleEngine
from app.models.entities import (
    Camera, Incident, IncidentEvidence, IncidentTimelineEntry, SignalCommand,
    SignalStateLog, TrafficMetric, TrafficObservation, VehicleDetection, utc_now,
)

logger = logging.getLogger("trafficintel.incidents.lifecycle")

# Entry types
STATUS_CHANGE = "STATUS_CHANGE"
NOTE = "NOTE"
ASSIGNMENT = "ASSIGNMENT"
EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED"
SLA_BREACH = "SLA_BREACH"
CORRECTION = "CORRECTION"

#: Default SLA targets by severity, in seconds. Copied onto the incident at
#: creation; an agency overrides these per deployment.
DEFAULT_SLA = {
    "CRITICAL": {"acknowledge_sec": 300, "resolve_sec": 3600},
    "HIGH": {"acknowledge_sec": 600, "resolve_sec": 7200},
    "MEDIUM": {"acknowledge_sec": 1800, "resolve_sec": 21600},
    "LOW": {"acknowledge_sec": 3600, "resolve_sec": 86400},
}

#: Evidence sources the platform can vouch for, mapped to their tables.
EVIDENCE_SOURCES = {
    "CAMERA_FRAME": ("vehicle_detections", VehicleDetection),
    "SENSOR_OBSERVATION": ("traffic_observations", TrafficObservation),
    "TRAFFIC_METRIC": ("traffic_metrics", TrafficMetric),
    "SIGNAL_COMMAND": ("signal_commands", SignalCommand),
    "SIGNAL_STATE": ("signal_state_logs", SignalStateLog),
}


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class IncidentLifecycle:
    """Incident operations with SLA tracking and an auditable timeline."""

    # ------------------------------------------------------------------
    # Timeline
    # ------------------------------------------------------------------

    @classmethod
    def append_timeline(
        cls,
        db: Session,
        incident_id: str,
        entry_type: str,
        actor: str,
        summary: str,
        detail: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        corrects_entry_id: Optional[str] = None,
    ) -> IncidentTimelineEntry:
        entry = IncidentTimelineEntry(
            incident_id=incident_id,
            entry_type=entry_type,
            actor=actor,
            summary=summary,
            detail=detail,
            context=context,
            corrects_entry_id=corrects_entry_id,
            timestamp=utc_now(),
        )
        db.add(entry)
        db.flush()
        return entry

    # ------------------------------------------------------------------
    # SLA
    # ------------------------------------------------------------------

    @classmethod
    def apply_sla_policy(cls, incident: Incident) -> None:
        """Stamps SLA targets onto a new incident from its severity."""
        policy = DEFAULT_SLA.get((incident.severity or "MEDIUM").upper(), DEFAULT_SLA["MEDIUM"])
        incident.sla_acknowledge_sec = policy["acknowledge_sec"]
        incident.sla_resolve_sec = policy["resolve_sec"]

    @classmethod
    def sla_status(cls, incident: Incident) -> Dict[str, Any]:
        """Current SLA standing, computed from real timestamps."""
        now = datetime.now(timezone.utc)
        detected_at = _as_utc(incident.detected_at)

        if detected_at is None:
            return {
                "status": "NOT_TRACKED",
                "explanation": "This incident has no detection timestamp, so no SLA clock started.",
            }

        acknowledge: Dict[str, Any] = {"target_sec": incident.sla_acknowledge_sec}
        if incident.sla_acknowledge_sec is None:
            acknowledge["status"] = "NO_TARGET_SET"
        elif incident.acknowledged_at:
            elapsed = (_as_utc(incident.acknowledged_at) - detected_at).total_seconds()
            acknowledge.update({
                "status": "MET" if elapsed <= incident.sla_acknowledge_sec else "BREACHED",
                "elapsed_sec": round(elapsed, 1),
                "acknowledged_at": incident.acknowledged_at.isoformat(),
            })
        else:
            elapsed = (now - detected_at).total_seconds()
            remaining = incident.sla_acknowledge_sec - elapsed
            acknowledge.update({
                "status": "BREACHED" if remaining < 0 else "RUNNING",
                "elapsed_sec": round(elapsed, 1),
                "remaining_sec": round(remaining, 1),
            })

        resolve: Dict[str, Any] = {"target_sec": incident.sla_resolve_sec}
        if incident.sla_resolve_sec is None:
            resolve["status"] = "NO_TARGET_SET"
        elif incident.resolved_at:
            elapsed = (_as_utc(incident.resolved_at) - detected_at).total_seconds()
            resolve.update({
                "status": "MET" if elapsed <= incident.sla_resolve_sec else "BREACHED",
                "elapsed_sec": round(elapsed, 1),
                "resolved_at": incident.resolved_at.isoformat(),
            })
        else:
            elapsed = (now - detected_at).total_seconds()
            remaining = incident.sla_resolve_sec - elapsed
            resolve.update({
                "status": "BREACHED" if remaining < 0 else "RUNNING",
                "elapsed_sec": round(elapsed, 1),
                "remaining_sec": round(remaining, 1),
            })

        return {
            "status": (
                "BREACHED"
                if acknowledge.get("status") == "BREACHED" or resolve.get("status") == "BREACHED"
                else "ON_TRACK"
            ),
            "acknowledge": acknowledge,
            "resolve": resolve,
            "policy_note": (
                "Targets were copied onto this incident when it was created. Changing "
                "the policy now does not rewrite whether this incident met its target."
            ),
        }

    @classmethod
    def check_sla_breaches(cls, db: Session) -> List[Dict[str, Any]]:
        """Marks newly breached SLAs and records them on the timeline."""
        open_incidents = (
            db.query(Incident)
            .filter(Incident.status.notin_(["RESOLVED"]))
            .all()
        )

        breached: List[Dict[str, Any]] = []
        for incident in open_incidents:
            status = cls.sla_status(incident)

            if (
                status.get("acknowledge", {}).get("status") == "BREACHED"
                and not incident.sla_acknowledge_breached
            ):
                incident.sla_acknowledge_breached = True
                cls.append_timeline(
                    db, incident.id, SLA_BREACH, "system",
                    "Acknowledgement SLA breached",
                    "Not acknowledged within {}s of detection.".format(
                        incident.sla_acknowledge_sec
                    ),
                    context={"sla": "acknowledge", **status["acknowledge"]},
                )
                event_bus.publish(topics.INCIDENT_SLA_BREACHED, {
                    "incident_id": incident.id,
                    "title": incident.title,
                    "sla": "acknowledge",
                    "target_sec": incident.sla_acknowledge_sec,
                })
                breached.append({"incident_id": incident.id, "sla": "acknowledge"})

            if (
                status.get("resolve", {}).get("status") == "BREACHED"
                and not incident.sla_resolve_breached
            ):
                incident.sla_resolve_breached = True
                cls.append_timeline(
                    db, incident.id, SLA_BREACH, "system",
                    "Resolution SLA breached",
                    "Not resolved within {}s of detection.".format(incident.sla_resolve_sec),
                    context={"sla": "resolve", **status["resolve"]},
                )
                event_bus.publish(topics.INCIDENT_SLA_BREACHED, {
                    "incident_id": incident.id,
                    "title": incident.title,
                    "sla": "resolve",
                    "target_sec": incident.sla_resolve_sec,
                })
                breached.append({"incident_id": incident.id, "sla": "resolve"})

        if breached:
            db.commit()
        return breached

    # ------------------------------------------------------------------
    # Triage actions
    # ------------------------------------------------------------------

    @classmethod
    def acknowledge(cls, db: Session, incident: Incident, actor: str) -> Dict[str, Any]:
        if incident.acknowledged_at:
            return {
                "changed": False,
                "reason": "ALREADY_ACKNOWLEDGED",
                "acknowledged_by": incident.acknowledged_by,
                "acknowledged_at": incident.acknowledged_at.isoformat(),
            }

        incident.acknowledged_at = utc_now()
        incident.acknowledged_by = actor

        status = cls.sla_status(incident)
        cls.append_timeline(
            db, incident.id, STATUS_CHANGE, actor,
            "Acknowledged",
            context={"sla_acknowledge": status["acknowledge"]},
        )
        db.commit()

        return {
            "changed": True,
            "acknowledged_by": actor,
            "acknowledged_at": incident.acknowledged_at.isoformat(),
            "sla": status["acknowledge"],
        }

    @classmethod
    def assign(cls, db: Session, incident: Incident, assignee: str, actor: str) -> Dict[str, Any]:
        previous = incident.assigned_to
        incident.assigned_to = assignee
        incident.assigned_at = utc_now()

        cls.append_timeline(
            db, incident.id, ASSIGNMENT, actor,
            "Assigned to {}".format(assignee),
            context={"from": previous, "to": assignee},
        )
        db.commit()

        return {
            "incident_id": incident.id,
            "assigned_to": assignee,
            "previously_assigned_to": previous,
            "assigned_at": incident.assigned_at.isoformat(),
        }

    @classmethod
    def transition(
        cls, db: Session, incident: Incident, new_status: str, actor: str,
        notes: Optional[str] = None,
    ) -> Tuple[bool, str]:
        previous = incident.status
        ok, message = IncidentLifecycleEngine.transition_incident(
            incident=incident, new_status=new_status, operator_username=actor, notes=notes,
        )
        if not ok:
            return False, message

        cls.append_timeline(
            db, incident.id, STATUS_CHANGE, actor,
            "{} -> {}".format(previous, new_status),
            detail=notes,
            context={"from": previous, "to": new_status},
        )

        topic = (
            topics.INCIDENT_RESOLVED if new_status == "RESOLVED" else topics.INCIDENT_UPDATED
        )
        event_bus.publish(topic, {
            "incident_id": incident.id,
            "title": incident.title,
            "from_status": previous,
            "status": new_status,
            "operator": actor,
        })

        db.commit()
        return True, message

    # ------------------------------------------------------------------
    # Evidence
    # ------------------------------------------------------------------

    @classmethod
    def attach_evidence(
        cls,
        db: Session,
        incident: Incident,
        evidence_type: str,
        source_id: str,
        actor: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Attaches a reference to something the platform actually recorded."""
        if evidence_type not in EVIDENCE_SOURCES:
            raise ValueError(
                "Unknown evidence type '{}'. Evidence must reference a recorded "
                "observation: {}.".format(evidence_type, sorted(EVIDENCE_SOURCES))
            )

        table_name, model = EVIDENCE_SOURCES[evidence_type]
        record = db.query(model).filter(model.id == source_id).first()
        if record is None:
            raise ValueError(
                "No {} row with id '{}' exists. Evidence must point at a record the "
                "platform stored; nothing is attached on trust.".format(table_name, source_id)
            )

        # Snapshot the record so the evidence survives retention pruning.
        snapshot = {
            column.name: getattr(record, column.name)
            for column in model.__table__.columns
        }
        observed_at = (
            snapshot.get("timestamp") or snapshot.get("issued_at") or snapshot.get("attached_at")
        )
        for key, value in list(snapshot.items()):
            if isinstance(value, datetime):
                snapshot[key] = value.isoformat()

        evidence = IncidentEvidence(
            incident_id=incident.id,
            evidence_type=evidence_type,
            source_table=table_name,
            source_id=source_id,
            snapshot=snapshot,
            observed_at=observed_at if isinstance(observed_at, datetime) else None,
            attached_by=actor,
            note=note,
        )
        db.add(evidence)
        db.flush()

        cls.append_timeline(
            db, incident.id, EVIDENCE_ATTACHED, actor,
            "Attached {} evidence".format(evidence_type.replace("_", " ").lower()),
            detail=note,
            context={
                "evidence_id": evidence.id,
                "source_table": table_name,
                "source_id": source_id,
            },
        )
        db.commit()

        return {
            "evidence_id": evidence.id,
            "evidence_type": evidence_type,
            "source_table": table_name,
            "source_id": source_id,
            "observed_at": evidence.observed_at.isoformat() if evidence.observed_at else None,
            "attached_by": actor,
            "attached_at": evidence.attached_at.isoformat(),
        }

    # ------------------------------------------------------------------
    # Post-incident report
    # ------------------------------------------------------------------

    @classmethod
    def post_incident_report(cls, db: Session, incident: Incident) -> Dict[str, Any]:
        """Assembles a report from recorded facts only.

        Every figure comes from a stored timestamp or a stored record. Where
        something was not recorded, the report says so rather than leaving the
        gap for a reader to fill with an assumption.
        """
        timeline = (
            db.query(IncidentTimelineEntry)
            .filter(IncidentTimelineEntry.incident_id == incident.id)
            .order_by(IncidentTimelineEntry.timestamp.asc())
            .all()
        )
        evidence = (
            db.query(IncidentEvidence)
            .filter(IncidentEvidence.incident_id == incident.id)
            .order_by(IncidentEvidence.attached_at.asc())
            .all()
        )

        detected_at = _as_utc(incident.detected_at)
        acknowledged_at = _as_utc(incident.acknowledged_at)
        resolved_at = _as_utc(incident.resolved_at)

        durations: Dict[str, Any] = {}
        if detected_at and acknowledged_at:
            durations["detection_to_acknowledgement_sec"] = round(
                (acknowledged_at - detected_at).total_seconds(), 1
            )
        else:
            durations["detection_to_acknowledgement_sec"] = None

        if detected_at and resolved_at:
            durations["detection_to_resolution_sec"] = round(
                (resolved_at - detected_at).total_seconds(), 1
            )
        else:
            durations["detection_to_resolution_sec"] = None

        if acknowledged_at and resolved_at:
            durations["acknowledgement_to_resolution_sec"] = round(
                (resolved_at - acknowledged_at).total_seconds(), 1
            )
        else:
            durations["acknowledgement_to_resolution_sec"] = None

        gaps: List[str] = []
        if not acknowledged_at:
            gaps.append("This incident was never acknowledged, so response time is unknown.")
        if not resolved_at:
            gaps.append("This incident is not resolved, so total duration is still running.")
        if not evidence:
            gaps.append("No evidence was attached, so the report rests on operator notes alone.")

        return {
            "incident": {
                "id": incident.id,
                "title": incident.title,
                "type": incident.type,
                "severity": incident.severity,
                "status": incident.status,
                "source": incident.source,
                "intersection_id": incident.intersection_id,
                "detected_at": detected_at.isoformat() if detected_at else None,
                "acknowledged_at": acknowledged_at.isoformat() if acknowledged_at else None,
                "acknowledged_by": incident.acknowledged_by,
                "assigned_to": incident.assigned_to,
                "resolved_at": resolved_at.isoformat() if resolved_at else None,
            },
            "durations": durations,
            "sla": cls.sla_status(incident),
            "timeline": [
                {
                    "id": entry.id,
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    "entry_type": entry.entry_type,
                    "actor": entry.actor,
                    "summary": entry.summary,
                    "detail": entry.detail,
                    "context": entry.context,
                    "corrects_entry_id": entry.corrects_entry_id,
                }
                for entry in timeline
            ],
            "evidence": [
                {
                    "id": item.id,
                    "evidence_type": item.evidence_type,
                    "source_table": item.source_table,
                    "source_id": item.source_id,
                    "observed_at": item.observed_at.isoformat() if item.observed_at else None,
                    "attached_by": item.attached_by,
                    "attached_at": item.attached_at.isoformat() if item.attached_at else None,
                    "note": item.note,
                    "snapshot": item.snapshot,
                }
                for item in evidence
            ],
            "operator_notes": incident.operator_notes,
            "evidence_count": len(evidence),
            "timeline_entry_count": len(timeline),
            "gaps": gaps,
            "report_basis": (
                "Every figure in this report is derived from a stored timestamp or a "
                "stored record. Nothing is inferred, and gaps are listed rather than "
                "filled."
            ),
            "generated_at": utc_now().isoformat(),
        }
