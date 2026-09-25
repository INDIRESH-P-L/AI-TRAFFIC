"""TRAFFICINTEL AI - Conditional Transit Signal Priority (GTFS-Realtime)

Grants a bus a green extension only when every condition holds, and records the
decision - granted or not, with the reason - for every bus it evaluates near a
junction:

1. The position is fresh and carries a heading.
2. The bus is approaching a junction: within DETECTION_RADIUS_M and within
   APPROACH_CONE_DEG of its heading.
3. **It is late.** Schedule adherence comes from the TripUpdates feed. Without
   it lateness is unknown, and conditional TSP is not granted on an unknown -
   that is what "conditional" means. An on-time bus is not given priority.
4. No priority was granted at that junction within LOCKOUT_SEC, so the
   controller can recover its coordination between grants.
5. A lane on the bus's approach is mapped to a phase - never a guessed phase.
6. That phase is **currently displaying green**, read from polled signal state
   no older than STATE_FRESHNESS_SEC.
7. The Deterministic Safety Engine passes it, via the single dispatcher.

Only green extension is requested. Early green (truncating the conflicting
phase) needs NTCIP force-off, which this platform's adapter does not implement;
a bus arriving on red is recorded as EARLY_GREEN_NOT_SUPPORTED rather than
pretended into a hold that would do nothing.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.analytics.stringline import haversine_m
from app.emergency.preemption import _angle_between, approach_for_heading, bearing_deg
from app.models.entities import (
    Approach, Intersection, SignalController, SignalStateLog, TransitEvent,
)
from app.signals.dispatch import SignalCommandDispatcher

MIN_LATENESS_SEC = 60
MAX_POSITION_AGE_SEC = 30
DETECTION_RADIUS_M = 300.0
APPROACH_CONE_DEG = 45.0
LOCKOUT_SEC = 180
EXTENSION_SEC = 10
STATE_FRESHNESS_SEC = 10

GRANTED = "GRANTED_GREEN_EXTENSION"
WOULD_REQUEST = "WOULD_REQUEST_GREEN_EXTENSION"


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _lateness_index(trip_updates: List[Dict[str, Any]]) -> Dict[str, int]:
    """trip_id (and vehicle id) -> delay in seconds, from TripUpdates.

    Prefers the trip-level delay; otherwise the next stop's arrival delay.
    """
    lateness: Dict[str, int] = {}
    for update in trip_updates:
        delay = update.get("delay_sec")
        if delay is None:
            for stop in update.get("stop_time_updates", []):
                delay = (stop.get("arrival") or {}).get("delay_sec")
                if delay is None:
                    delay = (stop.get("departure") or {}).get("delay_sec")
                if delay is not None:
                    break
        if delay is None:
            continue
        trip_id = (update.get("trip") or {}).get("trip_id")
        vehicle_id = (update.get("vehicle") or {}).get("id")
        if trip_id:
            lateness["trip:" + trip_id] = delay
        if vehicle_id:
            lateness["vehicle:" + vehicle_id] = delay
    return lateness


class TransitSignalPriority:
    """Evaluates a decoded feed; optionally dispatches green extensions."""

    @classmethod
    def evaluate(
        cls,
        db: Session,
        feed: Dict[str, Any],
        trip_updates: List[Dict[str, Any]],
        dry_run: bool,
        actor_id: Optional[str],
        actor_name: str,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        lateness = _lateness_index(trip_updates)
        junctions = db.query(Intersection).all()
        decisions = []

        for vehicle in feed.get("vehicles", []):
            decisions.append(cls._decide(db, vehicle, lateness, junctions, dry_run,
                                         actor_id, actor_name, now))

        counts: Dict[str, int] = {}
        for d in decisions:
            counts[d["decision"]] = counts.get(d["decision"], 0) + 1
        return {
            "status": "EVALUATED",
            "dry_run": dry_run,
            "feed_timestamp": (feed.get("header") or {}).get("timestamp"),
            "vehicles_in_feed": len(feed.get("vehicles", [])),
            "trip_updates_in_feed": len(trip_updates),
            "schedule_adherence_available": bool(lateness),
            "decision_counts": counts,
            "decisions": decisions,
            "conditions": {
                "min_lateness_sec": MIN_LATENESS_SEC,
                "max_position_age_sec": MAX_POSITION_AGE_SEC,
                "detection_radius_m": DETECTION_RADIUS_M,
                "approach_cone_deg": APPROACH_CONE_DEG,
                "lockout_sec": LOCKOUT_SEC,
                "extension_sec": EXTENSION_SEC,
                "state_freshness_sec": STATE_FRESHNESS_SEC,
            },
            "note": (
                "Dry run: nothing was sent and nothing was recorded."
                if dry_run else
                "Every bus evaluated near a junction is recorded with its decision, "
                "granted or not."
            ),
        }

    @classmethod
    def _decide(cls, db, vehicle, lateness, junctions, dry_run, actor_id, actor_name, now):
        vehicle_id = (vehicle.get("vehicle") or {}).get("id") or vehicle.get("entity_id")
        trip = vehicle.get("trip") or {}
        base = {"vehicle_id": vehicle_id, "trip_id": trip.get("trip_id"),
                "route_id": trip.get("route_id")}

        def outcome(decision, detail, **extra):
            return {**base, "decision": decision, "detail": detail, **extra}

        if vehicle.get("latitude") is None or vehicle.get("longitude") is None:
            return outcome("NO_POSITION", "The feed entity carries no position.")
        reported = vehicle.get("timestamp")
        if reported is None:
            return outcome("NO_TIMESTAMP", "The position has no timestamp, so its age is unknown.")
        reported_at = datetime.fromtimestamp(reported, tz=timezone.utc)
        age = (now - reported_at).total_seconds()
        if age > MAX_POSITION_AGE_SEC:
            return outcome("POSITION_TOO_OLD", "Position is {:.0f}s old (max {}s).".format(
                age, MAX_POSITION_AGE_SEC), position_age_sec=round(age, 1))
        heading = vehicle.get("bearing_deg")
        if heading is None:
            return outcome("NO_HEADING", "The feed gives no bearing, so the approach "
                                         "(and the phase that serves it) cannot be determined.")

        lat, lon = vehicle["latitude"], vehicle["longitude"]
        candidates = []
        for inter in junctions:
            distance = haversine_m(lat, lon, inter.latitude, inter.longitude)
            if distance > DETECTION_RADIUS_M:
                continue
            off_axis = _angle_between(heading, bearing_deg(lat, lon, inter.latitude, inter.longitude))
            if off_axis <= APPROACH_CONE_DEG:
                candidates.append((distance, off_axis, inter))
        if not candidates:
            return outcome("NO_JUNCTION_APPROACHED", "No junction within {:.0f} m ahead of the bus.".format(
                DETECTION_RADIUS_M))

        distance, _off_axis, junction = min(candidates, key=lambda c: c[0])
        approach_name = approach_for_heading(heading)
        target = {"intersection_id": junction.id, "name": junction.name,
                  "distance_m": round(distance, 1), "approach": approach_name}

        delay = lateness.get("trip:" + (trip.get("trip_id") or "")) \
            if trip.get("trip_id") else None
        if delay is None:
            delay = lateness.get("vehicle:" + (vehicle_id or ""))

        def record(decision, detail, requested=False, granted=False, command_id=None, extra=None):
            if not dry_run:
                db.add(TransitEvent(
                    route_id=trip.get("route_id") or "UNKNOWN", vehicle_id=vehicle_id or "UNKNOWN",
                    intersection_id=junction.id, trip_id=trip.get("trip_id"),
                    delay_seconds=delay if delay is not None else 0,
                    priority_requested=requested, priority_granted=granted,
                    decision=decision, decision_reason=detail, command_id=command_id,
                    distance_m=round(distance, 1), bearing_deg=heading,
                    vehicle_reported_at=_naive(reported_at), source="GTFS-RT",
                    details={"target": target, "delay_known": delay is not None, **(extra or {})},
                ))
                db.commit()
            return outcome(decision, detail, target=target, delay_sec=delay, **(extra or {}))

        if delay is None:
            return record("NO_SCHEDULE_ADHERENCE_DATA",
                          "No TripUpdate gives this bus's delay. Conditional TSP grants priority "
                          "only to late buses, and lateness is unknown - so none is granted.")
        if delay < MIN_LATENESS_SEC:
            return record("NOT_LATE_ENOUGH",
                          "The bus is {}s {} schedule; priority requires at least {}s late.".format(
                              abs(delay), "behind" if delay >= 0 else "ahead of", MIN_LATENESS_SEC))

        recent = (
            db.query(TransitEvent)
            .filter(
                TransitEvent.intersection_id == junction.id,
                TransitEvent.priority_granted.is_(True),
                TransitEvent.timestamp >= _naive(now) - timedelta(seconds=LOCKOUT_SEC),
            )
            .first()
        )
        if recent is not None:
            return record("LOCKOUT_ACTIVE",
                          "Priority was granted at {} within the last {}s; the controller is "
                          "left to recover coordination.".format(junction.name, LOCKOUT_SEC))

        approach = db.query(Approach).filter(
            Approach.intersection_id == junction.id, Approach.direction == approach_name
        ).first()
        mapped = [lane for lane in (approach.lanes if approach else []) if lane.assigned_phase is not None]
        through = [lane for lane in mapped if (lane.movement_type or "").startswith("THRU")]
        phases = sorted({lane.assigned_phase for lane in (through or mapped)})
        if not phases:
            return record("NO_PHASE_SERVES_APPROACH",
                          "No lane on the {} approach has an assigned phase; priority is not "
                          "requested for a guessed phase.".format(approach_name.lower()))
        phase = phases[0]

        controller = db.query(SignalController).filter(SignalController.intersection_id == junction.id).first()
        if controller is None:
            return record("NO_CONTROLLER", "No signal controller is configured at this junction.")

        latest = (
            db.query(SignalStateLog)
            .filter(SignalStateLog.controller_id == controller.id)
            .order_by(SignalStateLog.timestamp.desc())
            .first()
        )
        state_age = (_naive(now) - latest.timestamp).total_seconds() if latest else None
        if latest is None or state_age > STATE_FRESHNESS_SEC:
            return record("SIGNAL_STATE_UNKNOWN",
                          "No polled signal state newer than {}s, so whether phase {} is green "
                          "is unknown. Priority is not requested blind.".format(STATE_FRESHNESS_SEC, phase))
        if phase not in (latest.green_phases or []):
            return record("EARLY_GREEN_NOT_SUPPORTED",
                          "Phase {} is not green (greens: {}). Early green needs NTCIP force-off, "
                          "which this adapter does not implement; only green extension is "
                          "requested.".format(phase, latest.green_phases or "none"),
                          extra={"requested_phase": phase})

        serving = next((p for p in controller.phases if p.phase_number == phase), None)
        hold = max(EXTENSION_SEC, serving.min_green if serving else EXTENSION_SEC)
        if dry_run:
            return record(WOULD_REQUEST,
                          "Bus is {}s late approaching {} on phase {}, which is green: a {}s "
                          "extension would be requested.".format(delay, junction.name, phase, hold),
                          extra={"requested_phase": phase, "hold_sec": hold})

        result = SignalCommandDispatcher.dispatch_phase_hold(
            db, controller=controller, requested_phase=phase, duration_sec=hold,
            idempotency_key="tsp-{}".format(uuid.uuid4().hex),
            actor_id=actor_id, actor_name=actor_name,
            command_type="TSP_GREEN_EXTENSION", origin="TSP",
            context={"vehicle_id": vehicle_id, "route_id": trip.get("route_id"), "delay_sec": delay},
        )
        decision = {"EXECUTED": GRANTED, "REJECTED": "REJECTED_BY_SAFETY_ENGINE"}.get(
            result.status, "DISPATCH_FAILED")
        detail = ("; ".join(result.safety.violations) if result.safety.violations
                  else "Controller acknowledged a {}s extension of phase {}.".format(hold, phase))
        return record(decision, detail, requested=True, granted=result.executed,
                      command_id=result.command.id,
                      extra={"requested_phase": phase, "hold_sec": hold,
                             "effect_verification": result.post_state.get("effect_verification")})
