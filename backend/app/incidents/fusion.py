"""TRAFFICINTEL AI - Fusion-Based Probable Incident Detection

Flags a *probable* incident on a road segment only when the classic incident
signature - occupancy rising while speed falls - is corroborated by at least
two independent sensors on that segment. Every response names which sources
corroborated it and which, having been evaluated, did not.

Why corroboration is the rule
-----------------------------
A single detector produces the incident signature for many reasons that are
not incidents: a stuck loop reads high occupancy, a radar with a bird's nest
reads slow, a vehicle parked over one loop does both. An operator dispatched
to a phantom incident learns to ignore the detector, and then misses the real
one. So one source is never enough, however strong its readings - that case is
reported as UNCORROBORATED_SINGLE_SOURCE, not as an incident.

Definitions, stated exactly
---------------------------
* **Segment** = an Approach (a direction of travel into a junction). It is the
  only segment unit the schema has: observations carry a lane, lanes belong to
  an approach. An observation with no lane cannot be placed on a segment and
  is reported as unattributed, never guessed onto one.
* **Independent source** = a distinct reporting identity (`source_id`, or
  `source` where no id was recorded). Two identities fed by one physical device
  would be counted twice - the platform cannot see that, and says so.
* **Occupancy spike** (per source): recent occupancy exceeds its own baseline
  with a 95% Welch interval excluding zero AND by at least
  MIN_OCCUPANCY_RISE_PCT_POINTS. The practical threshold stops a statistically
  real but operationally trivial rise from counting.
* **Speed drop** (per source): recent speed below its own baseline with a 95%
  interval excluding zero AND by at least MIN_SPEED_DROP_FRACTION.
* **Probable incident**: at least one source shows an occupancy spike, at least
  one shows a speed drop, and the sources showing symptoms number at least
  MIN_INDEPENDENT_SOURCES.

Each source is compared with *its own* baseline, so a loop that always reads
high is not mistaken for congestion, and sensors of different types never have
their raw readings pooled.

What this never does
--------------------
It never verifies an incident. Recording creates an incident in DETECTED - the
lifecycle's entry state - and a human moves it on. "Prevents automatic
unverified escalations" (incident_engine.py) applies to machines too.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.analytics.verification import MIN_SAMPLES_PER_SIDE, welch_compare
from app.incidents.lifecycle import IncidentLifecycle, STATUS_CHANGE
from app.models.entities import (
    Approach, Incident, Intersection, Lane, Sensor, TrafficObservation,
)

METHOD_VERSION = "fusion-v1"
DETECTOR_SOURCE = "FUSION_DETECTOR"
INCIDENT_TYPE = "PROBABLE_INCIDENT"

MIN_INDEPENDENT_SOURCES = 2
MIN_OCCUPANCY_RISE_PCT_POINTS = 15.0
MIN_SPEED_DROP_FRACTION = 0.30

DEFAULT_RECENT_MINUTES = 10
DEFAULT_BASELINE_MINUTES = 60

EXCLUDED_QUALITY = {"INVALID"}

PROBABLE_INCIDENT = "PROBABLE_INCIDENT"
UNCORROBORATED_SINGLE_SOURCE = "UNCORROBORATED_SINGLE_SOURCE"
PARTIAL_SYMPTOMS = "PARTIAL_SYMPTOMS"
NO_INCIDENT_INDICATED = "NO_INCIDENT_INDICATED"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_COMPUTABLE = "NOT_COMPUTABLE"

EVALUATED_STATES = {PROBABLE_INCIDENT, UNCORROBORATED_SINGLE_SOURCE, PARTIAL_SYMPTOMS, NO_INCIDENT_INDICATED}


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _identity(obs: TrafficObservation) -> str:
    return obs.source_id or obs.source


class IncidentFusionDetector:
    """Corroborated occupancy-spike + speed-drop detection per approach."""

    @classmethod
    def evaluate(
        cls,
        db: Session,
        intersection_id: str,
        as_of: Optional[datetime] = None,
        recent_minutes: int = DEFAULT_RECENT_MINUTES,
        baseline_minutes: int = DEFAULT_BASELINE_MINUTES,
    ) -> Dict[str, Any]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        if inter is None:
            return {"status": "NOT_FOUND", "detail": "No such junction."}

        as_of = _naive(as_of or datetime.now(timezone.utc))
        recent_start = as_of - timedelta(minutes=recent_minutes)
        baseline_start = recent_start - timedelta(minutes=baseline_minutes)

        approaches = db.query(Approach).filter(Approach.intersection_id == intersection_id).all()
        envelope = {
            "intersection_id": inter.id,
            "intersection_name": inter.name,
            "as_of": as_of.isoformat(),
            "recent_window": [recent_start.isoformat(), as_of.isoformat()],
            "baseline_window": [baseline_start.isoformat(), recent_start.isoformat()],
            "thresholds": {
                "min_independent_sources": MIN_INDEPENDENT_SOURCES,
                "min_occupancy_rise_pct_points": MIN_OCCUPANCY_RISE_PCT_POINTS,
                "min_speed_drop_fraction": MIN_SPEED_DROP_FRACTION,
                "min_samples_per_side": MIN_SAMPLES_PER_SIDE,
                "confidence_level": 0.95,
            },
            "method_version": METHOD_VERSION,
            "independence_basis": (
                "Sources are independent when their reporting identities differ "
                "(source_id, or source where no id was recorded). Two identities fed "
                "by one physical device would be counted twice; the platform cannot "
                "detect that."
            ),
        }

        if not approaches:
            return {
                **envelope,
                "status": NOT_COMPUTABLE,
                "detail": (
                    "No approaches are configured for this junction, so no observation "
                    "can be placed on a segment and nothing can be corroborated. "
                    "Configure approaches and lanes."
                ),
                "segments": [],
                "probable_incidents": [],
                "unattributed_sources": [],
            }

        lane_to_approach: Dict[str, str] = {}
        for approach in approaches:
            for lane in approach.lanes:
                lane_to_approach[lane.id] = approach.id

        configured_by_approach: Dict[str, int] = {a.id: 0 for a in approaches}
        for sensor in db.query(Sensor).filter(Sensor.intersection_id == intersection_id).all():
            if sensor.lane_id in lane_to_approach:
                configured_by_approach[lane_to_approach[sensor.lane_id]] += 1

        observations = (
            db.query(TrafficObservation)
            .filter(
                TrafficObservation.intersection_id == intersection_id,
                TrafficObservation.timestamp > baseline_start,
                TrafficObservation.timestamp <= as_of,
            )
            .order_by(TrafficObservation.timestamp.asc())
            .all()
        )

        per_segment: Dict[str, Dict[str, List[TrafficObservation]]] = {a.id: {} for a in approaches}
        unattributed: Dict[str, Dict[str, Any]] = {}
        excluded_invalid = 0
        for obs in observations:
            if (obs.quality or "").upper() in EXCLUDED_QUALITY:
                excluded_invalid += 1
                continue
            approach_id = lane_to_approach.get(obs.lane_id) if obs.lane_id else None
            if approach_id is None:
                entry = unattributed.setdefault(_identity(obs), {
                    "source": _identity(obs),
                    "observations": 0,
                    "reason": (
                        "NO_LANE_ASSIGNMENT" if not obs.lane_id else "LANE_NOT_ON_A_CONFIGURED_APPROACH"
                    ),
                })
                entry["observations"] += 1
                continue
            per_segment[approach_id].setdefault(_identity(obs), []).append(obs)

        segments = [
            cls._assess_segment(
                approach, per_segment[approach.id], configured_by_approach[approach.id],
                recent_start,
            )
            for approach in approaches
        ]

        probable = [s for s in segments if s["status"] == PROBABLE_INCIDENT]
        statuses = {s["status"] for s in segments}
        if probable:
            overall = PROBABLE_INCIDENT
            detail = "{} segment(s) show a corroborated incident signature.".format(len(probable))
        elif statuses & EVALUATED_STATES:
            overall = "NO_CORROBORATED_INCIDENT"
            detail = (
                "No segment shows an incident signature corroborated by {} or more "
                "independent sources.".format(MIN_INDEPENDENT_SOURCES)
            )
        elif INSUFFICIENT_DATA in statuses:
            overall = INSUFFICIENT_DATA
            detail = "No segment had enough samples from enough sources to evaluate."
        else:
            overall = NOT_COMPUTABLE
            detail = (
                "No segment has {} or more independent sources, so corroboration is "
                "structurally impossible.".format(MIN_INDEPENDENT_SOURCES)
            )

        not_evaluated = [
            "{} ({})".format(s["approach"], s["reason"])
            for s in segments if s["status"] not in EVALUATED_STATES
        ]
        if not_evaluated and overall in (PROBABLE_INCIDENT, "NO_CORROBORATED_INCIDENT"):
            detail += (
                " Not evaluated: {}. No incident can be detected on those segments, "
                "which is not the same as none occurring.".format("; ".join(not_evaluated))
            )

        return {
            **envelope,
            "status": overall,
            "detail": detail,
            "segments": segments,
            "probable_incidents": probable,
            "unattributed_sources": list(unattributed.values()),
            "observations_excluded_invalid": excluded_invalid,
        }

    # ------------------------------------------------------------------

    @classmethod
    def _assess_segment(
        cls,
        approach: Approach,
        sources: Dict[str, List[TrafficObservation]],
        configured_sensors: int,
        recent_start: datetime,
    ) -> Dict[str, Any]:
        base = {
            "approach_id": approach.id,
            "approach": "{} {}".format(approach.road_name, approach.direction.title()),
            "lane_ids": [lane.id for lane in approach.lanes],
            "sources_reporting": len(sources),
            "configured_sensors": configured_sensors,
        }

        if len(sources) < MIN_INDEPENDENT_SOURCES:
            if configured_sensors >= MIN_INDEPENDENT_SOURCES:
                return {
                    **base,
                    "status": INSUFFICIENT_DATA,
                    "reason": "CONFIGURED_SOURCES_SILENT",
                    "explanation": (
                        "{} sensors are configured on this segment but only {} reported "
                        "in the window. Corroboration needs {} reporting sources; "
                        "restore the silent sensor(s).".format(
                            configured_sensors, len(sources), MIN_INDEPENDENT_SOURCES
                        )
                    ),
                    "source_assessments": [],
                }
            return {
                **base,
                "status": NOT_COMPUTABLE,
                "reason": "FEWER_THAN_TWO_INDEPENDENT_SOURCES",
                "explanation": (
                    "Only {} source(s) report on this segment. A single detector cannot "
                    "corroborate itself, so no incident can be detected here however "
                    "strong its readings. Install a second, independent sensor."
                    .format(len(sources))
                ),
                "source_assessments": [],
            }

        assessments = [
            cls._assess_source(identity, observations, recent_start)
            for identity, observations in sorted(sources.items())
        ]

        occupancy_sources = [a["source"] for a in assessments if a["occupancy_spike"] is True]
        speed_sources = [a["source"] for a in assessments if a["speed_drop"] is True]
        evaluable = [a["source"] for a in assessments if a["evaluable"]]
        symptomatic = sorted(set(occupancy_sources) | set(speed_sources))
        dissenting = sorted(set(evaluable) - set(symptomatic))

        corroboration = {
            "occupancy_spike_sources": occupancy_sources,
            "speed_drop_sources": speed_sources,
            "corroborating_sources": symptomatic,
            "evaluated_but_not_corroborating": dissenting,
            "corroboration_ratio": (
                round(len(symptomatic) / len(evaluable), 3) if evaluable else None
            ),
            "corroboration_ratio_basis": (
                "Share of evaluable sources on this segment showing a symptom. A "
                "measure of agreement between sensors, not a probability that an "
                "incident is occurring."
            ),
        }

        if not evaluable:
            return {
                **base,
                "status": INSUFFICIENT_DATA,
                "reason": "TOO_FEW_SAMPLES_PER_SOURCE",
                "explanation": (
                    "Sources reported, but none had {} samples on both sides of the "
                    "window for any channel.".format(MIN_SAMPLES_PER_SIDE)
                ),
                "source_assessments": assessments,
                **corroboration,
            }

        if occupancy_sources and speed_sources and len(symptomatic) >= MIN_INDEPENDENT_SOURCES:
            status, reason = PROBABLE_INCIDENT, None
            explanation = (
                "Occupancy spike ({}) and speed drop ({}) corroborated by {} independent "
                "sources.".format(
                    ", ".join(occupancy_sources), ", ".join(speed_sources), len(symptomatic)
                )
            )
        elif occupancy_sources and speed_sources:
            status, reason = UNCORROBORATED_SINGLE_SOURCE, "ONLY_ONE_SOURCE_SHOWS_SYMPTOMS"
            explanation = (
                "Both symptoms appear, but only from {}. One detector cannot corroborate "
                "itself; not reported as an incident.".format(symptomatic[0])
            )
        elif occupancy_sources or speed_sources:
            status, reason = PARTIAL_SYMPTOMS, "ONE_SYMPTOM_ONLY"
            explanation = (
                "Only {} is present ({}). The incident signature needs both a rise in "
                "occupancy and a fall in speed; one alone is consistent with ordinary "
                "congestion or a sensor fault.".format(
                    "an occupancy spike" if occupancy_sources else "a speed drop",
                    ", ".join(occupancy_sources or speed_sources),
                )
            )
        else:
            status, reason = NO_INCIDENT_INDICATED, None
            explanation = "No evaluated source shows either symptom."

        return {
            **base,
            "status": status,
            "reason": reason,
            "explanation": explanation,
            "source_assessments": assessments,
            **corroboration,
        }

    @classmethod
    def _assess_source(
        cls,
        identity: str,
        observations: List[TrafficObservation],
        recent_start: datetime,
    ) -> Dict[str, Any]:
        baseline = [o for o in observations if o.timestamp <= recent_start]
        recent = [o for o in observations if o.timestamp > recent_start]

        occupancy = cls._channel(
            [o.occupancy_pct for o in baseline], [o.occupancy_pct for o in recent],
            "occupancy_pct",
        )
        speed = cls._channel(
            [o.avg_speed_kph for o in baseline], [o.avg_speed_kph for o in recent],
            "avg_speed_kph",
        )

        occupancy_spike = None
        if occupancy["status"] == "EVALUATED":
            occupancy_spike = (
                occupancy["ci_low"] > 0
                and occupancy["difference"] >= MIN_OCCUPANCY_RISE_PCT_POINTS
            )
        speed_drop = None
        if speed["status"] == "EVALUATED":
            before = speed["before_mean"] or 0.0
            drop_fraction = (-speed["difference"] / before) if before > 0 else 0.0
            speed["drop_fraction"] = round(drop_fraction, 4)
            speed_drop = speed["ci_high"] < 0 and drop_fraction >= MIN_SPEED_DROP_FRACTION

        latest = observations[-1]
        return {
            "source": identity,
            "sensor_kind": latest.source,
            "evaluable": occupancy_spike is not None or speed_drop is not None,
            "occupancy_spike": occupancy_spike,
            "speed_drop": speed_drop,
            "occupancy": occupancy,
            "speed": speed,
            "baseline_samples": len(baseline),
            "recent_samples": len(recent),
            # Kept for evidence: the most recent row this source actually wrote.
            "latest_observation_id": latest.id,
            "latest_observation_at": latest.timestamp.isoformat(),
        }

    @classmethod
    def _channel(
        cls, before: List[Optional[float]], after: List[Optional[float]], metric: str,
    ) -> Dict[str, Any]:
        before_values = [v for v in before if v is not None]
        after_values = [v for v in after if v is not None]
        if not before_values and not after_values:
            return {"status": "NOT_MEASURED", "detail": "This source does not report this channel."}
        result = welch_compare(before_values, after_values, metric)
        if result.ci_low is None:
            return {
                "status": "INSUFFICIENT_DATA",
                "before_samples": len(before_values),
                "after_samples": len(after_values),
                "detail": result.explanation,
            }
        return {
            "status": "EVALUATED",
            "before_mean": result.before_mean,
            "after_mean": result.after_mean,
            "difference": result.difference,
            "ci_low": result.ci_low,
            "ci_high": result.ci_high,
            "before_samples": result.before_n,
            "after_samples": result.after_n,
        }

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        db: Session,
        intersection_id: str,
        actor: str,
        as_of: Optional[datetime] = None,
        recent_minutes: int = DEFAULT_RECENT_MINUTES,
        baseline_minutes: int = DEFAULT_BASELINE_MINUTES,
    ) -> Dict[str, Any]:
        """Records each probable incident as DETECTED, with traceable evidence.

        Never records a status beyond DETECTED, and never records a second open
        incident for a segment that already has one from this detector.
        """
        assessment = cls.evaluate(
            db, intersection_id, as_of=as_of,
            recent_minutes=recent_minutes, baseline_minutes=baseline_minutes,
        )
        if assessment.get("status") == "NOT_FOUND":
            return assessment

        open_fusion = (
            db.query(Incident)
            .filter(
                Incident.intersection_id == intersection_id,
                Incident.source == DETECTOR_SOURCE,
                Incident.status != "RESOLVED",
            )
            .all()
        )
        open_by_approach = {
            (inc.evidence or {}).get("approach_id"): inc.id for inc in open_fusion
        }

        recorded, skipped = [], []
        for segment in assessment["probable_incidents"]:
            if segment["approach_id"] in open_by_approach:
                skipped.append({
                    "approach": segment["approach"],
                    "reason": "OPEN_INCIDENT_ALREADY_EXISTS",
                    "incident_id": open_by_approach[segment["approach_id"]],
                })
                continue

            incident = Incident(
                intersection_id=intersection_id,
                title="Probable incident: {} (corroborated by {} sources)".format(
                    segment["approach"], len(segment["corroborating_sources"])
                ),
                type=INCIDENT_TYPE,
                severity="MEDIUM",
                status="DETECTED",
                source=DETECTOR_SOURCE,
                affected_lanes=segment["lane_ids"],
                confidence=segment["corroboration_ratio"],
                evidence={
                    "approach_id": segment["approach_id"],
                    "detector": METHOD_VERSION,
                    "corroborating_sources": segment["corroborating_sources"],
                    "occupancy_spike_sources": segment["occupancy_spike_sources"],
                    "speed_drop_sources": segment["speed_drop_sources"],
                    "evaluated_but_not_corroborating": segment["evaluated_but_not_corroborating"],
                    "confidence_field_meaning": (
                        "corroboration_ratio - agreement between sensors, not a probability"
                    ),
                },
            )
            IncidentLifecycle.apply_sla_policy(incident)
            db.add(incident)
            db.flush()

            IncidentLifecycle.append_timeline(
                db, incident.id, STATUS_CHANGE, actor,
                "Probable incident detected by sensor fusion",
                detail=segment["explanation"],
                context={
                    "to": "DETECTED",
                    "detector": METHOD_VERSION,
                    "corroborating_sources": segment["corroborating_sources"],
                    "requires_human_verification": True,
                },
            )
            db.commit()

            evidence_ids = []
            for source in segment["source_assessments"]:
                if source["source"] not in segment["corroborating_sources"]:
                    continue
                attached = IncidentLifecycle.attach_evidence(
                    db, incident, "SENSOR_OBSERVATION", source["latest_observation_id"],
                    actor=actor,
                    note="Corroborating source {} ({}).".format(
                        source["source"], source["sensor_kind"]
                    ),
                )
                evidence_ids.append(attached["evidence_id"])

            recorded.append({
                "incident_id": incident.id,
                "approach": segment["approach"],
                "status": incident.status,
                "corroborating_sources": segment["corroborating_sources"],
                "evidence_ids": evidence_ids,
            })

        return {
            "status": assessment["status"],
            "recorded": recorded,
            "skipped": skipped,
            "note": (
                "Recorded incidents enter the lifecycle as DETECTED. The detector never "
                "verifies; an operator does."
            ),
            "assessment": assessment,
        }
