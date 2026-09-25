"""TRAFFICINTEL AI - Emergency Vehicle Preemption

One service behind both ways a preemption can be asked for:

* **MANUAL** - an operator requests a phase for a named vehicle.
* **AVL** - a vehicle's own position report (NMEA RMC or decoded fields)
  selects the junction it is approaching and the phase serving its approach.

Both reach the controller only through SignalCommandDispatcher, so both get
identical Safety Engine validation and the same audit trail. Preemption raises
a movement's priority, never its permission: a call that would create a
conflicting green or truncate a minimum green is REJECTED however urgent.

The defect this replaced: the manual endpoint validated a call, then recorded
it ACTIVE and audited it EXECUTED without sending anything to the controller.
Here the event's status is the dispatcher's real outcome:

    ACTIVE     the controller acknowledged the hold
    REJECTED   the Safety Engine refused it; nothing was sent
    FAILED     it passed validation but the controller did not acknowledge

AVL targeting is conservative. It never guesses a junction or a phase:
a stale or invalid fix is refused, a vehicle not heading toward a junction does
not trigger one, and a junction whose approach has no phase-mapped lane is
recorded as REJECTED with that configuration gap named.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.stringline import haversine_m
from app.models.entities import (
    Approach, AuditLog, EmergencyEvent, Intersection, SignalController, utc_now,
)
from app.signals.dispatch import SignalCommandDispatcher

AUTHORIZED_VEHICLE_TYPES = {"AMBULANCE", "FIRE_TRUCK", "POLICE"}

#: A fix older than this is not where the vehicle is.
MAX_POSITION_AGE_SEC = 10.0
#: Junctions further than this are not candidates.
DETECTION_RADIUS_M = 600.0
#: Preempt only when the vehicle will arrive within this time; earlier and the
#: hold would expire, later and cross traffic is stopped for nothing.
MAX_ETA_SEC = 40.0
#: The junction must lie within this angle of the vehicle's heading.
APPROACH_CONE_DEG = 45.0
#: Below this speed a heading is unreliable and an ETA meaningless.
MIN_SPEED_KPH = 5.0
#: No second call for the same vehicle and junction within this window.
REARM_SEC = 90.0
#: Seconds added to the ETA so the hold covers the vehicle's passage.
HOLD_MARGIN_SEC = 5

_DIRECTIONS = [("NORTHBOUND", 0.0), ("EASTBOUND", 90.0), ("SOUTHBOUND", 180.0), ("WESTBOUND", 270.0)]


@dataclass
class AvlPosition:
    vehicle_id: str
    vehicle_type: str
    latitude: float
    longitude: float
    speed_kph: float
    heading_deg: Optional[float]
    reported_at: datetime
    source: str


def _angle_between(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lambda = math.radians(lon2 - lon1)
    y = math.sin(d_lambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lambda)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def approach_for_heading(heading: float) -> str:
    """A vehicle heading north arrives on the junction's northbound approach."""
    return min(_DIRECTIONS, key=lambda d: _angle_between(heading, d[1]))[0]


def _as_naive_utc(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class PreemptionService:
    """Validated, dispatched and audited preemption from any trigger."""

    @classmethod
    def preempt(
        cls,
        db: Session,
        intersection: Intersection,
        requested_phase: int,
        vehicle_id: str,
        vehicle_type: str,
        actor_id: Optional[str],
        actor_name: str,
        trigger: str = "MANUAL",
        source: str = "OPERATOR_CONSOLE",
        priority_level: int = 1,
        dwell_sec: Optional[int] = None,
        position: Optional[AvlPosition] = None,
        eta_sec: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        controller = db.query(SignalController).filter(
            SignalController.intersection_id == intersection.id
        ).first()

        event = EmergencyEvent(
            intersection_id=intersection.id,
            vehicle_id=vehicle_id,
            vehicle_type=vehicle_type,
            priority_level=priority_level,
            requested_phase=requested_phase,
            source=source,
            trigger=trigger,
            eta_sec=round(eta_sec, 1) if eta_sec is not None else None,
            details=details,
        )
        if position is not None:
            event.latitude, event.longitude = position.latitude, position.longitude
            event.heading_deg = position.heading_deg
            event.position_reported_at = _as_naive_utc(position.reported_at)

        if controller is None:
            safety = {
                "is_safe": False,
                "violations": [
                    "No signal controller is configured at {}. Preemption cannot be granted "
                    "for an intersection with no controllable hardware.".format(intersection.name)
                ],
                "checks_performed": ["CONTROLLER_PRESENCE_VALIDATION"],
                "checks": [],
                "details": {"intersection_id": intersection.id},
            }
            event.status, event.safety_clearance_passed = "REJECTED", False
            event.safety_report = safety
            db.add(event)
            db.flush()
            cls._audit(db, event, actor_id, actor_name, "REJECTED", safety["violations"])
            db.commit()
            return {"event": event, "controller": None, "safety": safety, "dispatch": None}

        if dwell_sec is None:
            # Defaults to the phase's own minimum green, so the call is judged
            # against the controller's configured envelope, not a number chosen here.
            target = next((p for p in controller.phases if p.phase_number == requested_phase), None)
            dwell_sec = target.min_green if target else 0

        result = SignalCommandDispatcher.dispatch_phase_hold(
            db, controller=controller, requested_phase=requested_phase,
            duration_sec=int(dwell_sec),
            # Bounded and collision-free: a vehicle id (up to 64 chars) placed
            # before the random part could truncate that part away entirely.
            idempotency_key="evp-{}-{}".format(trigger.lower(), uuid.uuid4().hex),
            actor_id=actor_id, actor_name=actor_name,
            command_type="PREEMPTION", origin="EVP_" + trigger,
            context={"vehicle_id": vehicle_id, "vehicle_type": vehicle_type, "trigger": trigger},
        )

        event.status = {"EXECUTED": "ACTIVE", "REJECTED": "REJECTED"}.get(result.status, "FAILED")
        event.safety_clearance_passed = result.safety.is_safe
        event.safety_report = result.safety.model_dump()
        event.command_id = result.command.id
        event.command_status = result.status
        db.add(event)
        db.flush()
        cls._audit(db, event, actor_id, actor_name, result.status, result.safety.violations)
        db.commit()
        return {"event": event, "controller": controller, "safety": result.safety.model_dump(),
                "dispatch": result}

    @classmethod
    def _audit(cls, db, event, actor_id, actor_name, outcome, violations):
        db.add(AuditLog(
            actor_id=actor_id,
            actor_username=actor_name,
            action="EMERGENCY_PREEMPTION_REQUESTED",
            resource_type="EmergencyEvent",
            resource_id=event.id,
            # The real outcome - the replaced code wrote EXECUTED here for a
            # call that was never sent.
            result=outcome,
            details={
                "vehicle_id": event.vehicle_id,
                "type": event.vehicle_type,
                "phase": event.requested_phase,
                "trigger": event.trigger,
                "command_id": event.command_id,
                "safety_violations": violations,
            },
        ))

    # ------------------------------------------------------------------
    # AVL
    # ------------------------------------------------------------------

    @classmethod
    def handle_avl(
        cls,
        db: Session,
        position: AvlPosition,
        actor_id: Optional[str],
        actor_name: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Turns one position report into a preemption call, or says why not."""
        now = now or datetime.now(timezone.utc)
        reported = position.reported_at
        if reported.tzinfo is None:
            reported = reported.replace(tzinfo=timezone.utc)
        age = (now - reported).total_seconds()
        base = {
            "vehicle_id": position.vehicle_id,
            "position": {
                "latitude": position.latitude, "longitude": position.longitude,
                "speed_kph": round(position.speed_kph, 1), "heading_deg": position.heading_deg,
                "reported_at": reported.isoformat(), "age_sec": round(age, 1),
            },
            "thresholds": {
                "max_position_age_sec": MAX_POSITION_AGE_SEC,
                "detection_radius_m": DETECTION_RADIUS_M,
                "max_eta_sec": MAX_ETA_SEC,
                "approach_cone_deg": APPROACH_CONE_DEG,
                "min_speed_kph": MIN_SPEED_KPH,
                "rearm_sec": REARM_SEC,
            },
        }

        def refuse(decision: str, detail: str, audit: bool = True) -> Dict[str, Any]:
            if audit:
                db.add(AuditLog(
                    actor_id=actor_id, actor_username=actor_name,
                    action="AVL_REPORT_NOT_ACTED_ON", resource_type="AvlReport",
                    resource_id=position.vehicle_id, result=decision,
                    details={"detail": detail, **base},
                ))
                db.commit()
            return {**base, "decision": decision, "detail": detail, "event": None}

        if (position.vehicle_type or "").upper() not in AUTHORIZED_VEHICLE_TYPES:
            return refuse("UNAUTHORIZED_VEHICLE_TYPE",
                          "Vehicle type '{}' is not authorised for preemption ({}).".format(
                              position.vehicle_type, sorted(AUTHORIZED_VEHICLE_TYPES)))
        if age > MAX_POSITION_AGE_SEC:
            return refuse("POSITION_TOO_OLD",
                          "The fix is {:.1f}s old; at most {:.0f}s is accepted. A stale position "
                          "could preempt a junction the vehicle has already passed.".format(
                              age, MAX_POSITION_AGE_SEC))
        if age < -MAX_POSITION_AGE_SEC:
            return refuse("POSITION_IN_THE_FUTURE",
                          "The fix is timestamped {:.1f}s in the future; the unit's clock is "
                          "wrong, so its position cannot be trusted.".format(-age))
        if position.speed_kph < MIN_SPEED_KPH or position.heading_deg is None:
            # Routine (a parked vehicle reports constantly); not audited.
            return refuse("VEHICLE_NOT_MOVING",
                          "Speed {:.1f} km/h is below {:.0f} km/h, so heading and arrival time "
                          "are not reliable.".format(position.speed_kph, MIN_SPEED_KPH), audit=False)

        speed_mps = position.speed_kph / 3.6
        candidates = []
        for inter in db.query(Intersection).all():
            distance = haversine_m(position.latitude, position.longitude, inter.latitude, inter.longitude)
            if distance > DETECTION_RADIUS_M:
                continue
            toward = bearing_deg(position.latitude, position.longitude, inter.latitude, inter.longitude)
            off_axis = _angle_between(position.heading_deg, toward)
            eta = distance / speed_mps
            if off_axis <= APPROACH_CONE_DEG and eta <= MAX_ETA_SEC:
                candidates.append((eta, distance, off_axis, inter))

        if not candidates:
            return refuse("NO_JUNCTION_APPROACHED",
                          "No junction lies within {:.0f} m, within {:.0f} degrees of the vehicle's "
                          "heading, and within {:.0f}s of arrival.".format(
                              DETECTION_RADIUS_M, APPROACH_CONE_DEG, MAX_ETA_SEC), audit=False)

        eta, distance, off_axis, target = min(candidates, key=lambda c: c[0])
        approach_name = approach_for_heading(position.heading_deg)
        target_block = {
            "intersection_id": target.id, "name": target.name,
            "distance_m": round(distance, 1), "eta_sec": round(eta, 1),
            "off_axis_deg": round(off_axis, 1), "approach": approach_name,
        }

        recent = (
            db.query(EmergencyEvent)
            .filter(
                EmergencyEvent.vehicle_id == position.vehicle_id,
                EmergencyEvent.intersection_id == target.id,
                EmergencyEvent.status == "ACTIVE",
                EmergencyEvent.timestamp >= _as_naive_utc(now) - timedelta(seconds=REARM_SEC),
            )
            .first()
        )
        if recent is not None:
            return {**base, "decision": "ALREADY_PREEMPTED", "target": target_block,
                    "detail": "An active preemption for this vehicle at {} was granted within the "
                              "last {:.0f}s.".format(target.name, REARM_SEC),
                    "event": {"event_id": recent.id, "status": recent.status}}

        approach = db.query(Approach).filter(
            Approach.intersection_id == target.id, Approach.direction == approach_name,
        ).first()
        phases = []
        if approach is not None:
            mapped = [lane for lane in approach.lanes if lane.assigned_phase is not None]
            through = [lane for lane in mapped if (lane.movement_type or "").startswith("THRU")]
            phases = sorted({lane.assigned_phase for lane in (through or mapped)})

        if not phases:
            reason = (
                "No lane on the {} approach of {} has an assigned phase, so the phase that "
                "would serve this vehicle is unknown. Preemption is not requested for a guessed "
                "phase; configure lane assignments.".format(approach_name.lower(), target.name)
            )
            event = EmergencyEvent(
                intersection_id=target.id, vehicle_id=position.vehicle_id,
                vehicle_type=position.vehicle_type, requested_phase=None,
                status="REJECTED", safety_clearance_passed=False, trigger="AVL",
                source=position.source, eta_sec=round(eta, 1),
                latitude=position.latitude, longitude=position.longitude,
                heading_deg=position.heading_deg,
                position_reported_at=_as_naive_utc(reported),
                safety_report={"is_safe": False, "violations": [reason],
                               "checks_performed": ["APPROACH_PHASE_MAPPING"], "checks": [],
                               "details": {"approach": approach_name}},
                details={"target": target_block},
            )
            db.add(event)
            db.flush()
            cls._audit(db, event, actor_id, actor_name, "REJECTED", [reason])
            db.commit()
            return {**base, "decision": "NO_PHASE_SERVES_APPROACH", "target": target_block,
                    "detail": reason, "event": cls.serialize(event)}

        controller = db.query(SignalController).filter(SignalController.intersection_id == target.id).first()
        requested = phases[0]
        dwell = None
        if controller is not None:
            phase = next((p for p in controller.phases if p.phase_number == requested), None)
            if phase is not None:
                # Long enough for the vehicle to arrive and pass, never beyond
                # the phase's own envelope - the Safety Engine checks that too.
                dwell = int(min(max(math.ceil(eta) + HOLD_MARGIN_SEC, phase.min_green), phase.max_green))

        outcome = cls.preempt(
            db, target, requested, position.vehicle_id, position.vehicle_type,
            actor_id=actor_id, actor_name=actor_name, trigger="AVL", source=position.source,
            dwell_sec=dwell, position=position, eta_sec=eta, details={"target": target_block},
        )
        event = outcome["event"]
        decision = {"ACTIVE": "PREEMPTION_ACTIVE", "REJECTED": "REJECTED_BY_SAFETY_ENGINE"}.get(
            event.status, "DISPATCH_FAILED")
        return {**base, "decision": decision, "target": target_block,
                "requested_phase": requested, "hold_sec": dwell,
                "detail": "; ".join(outcome["safety"]["violations"]) or "Preemption dispatched.",
                "event": cls.serialize(event)}

    @classmethod
    def serialize(cls, event: EmergencyEvent) -> Dict[str, Any]:
        return {
            "event_id": event.id, "intersection_id": event.intersection_id,
            "vehicle_id": event.vehicle_id, "vehicle_type": event.vehicle_type,
            "requested_phase": event.requested_phase, "status": event.status,
            "trigger": event.trigger, "command_id": event.command_id,
            "command_status": event.command_status,
            "safety_clearance_passed": event.safety_clearance_passed,
            "violations": (event.safety_report or {}).get("violations", []),
            "eta_sec": event.eta_sec,
            "timestamp": event.timestamp.isoformat() if event.timestamp else None,
        }
