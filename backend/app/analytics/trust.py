"""TRAFFICINTEL AI - Junction Data-Quality Trust Score

A composite score answering one question: **how much of what this console
shows about this junction rests on something recently measured?**

Design decisions that keep this from becoming the thing it is meant to
prevent:

1. **An unmonitored junction is UNRATED, not zero.** Zero means "measured and
   bad". A junction with no detectors configured has not scored badly; there
   is nothing to score. Collapsing the two would put a red 0 next to a
   perfectly healthy junction nobody instrumented, and operators would learn
   to ignore red.

2. **Every component is visible, with its own score and reason.** A single
   opaque number is exactly the kind of figure this platform exists to refuse.
   The composite is a weighted mean of components that each state what they
   measured and why they scored what they did.

3. **Components with nothing to measure are excluded from the mean, not
   scored zero.** A junction with no camera is not penalised for the camera it
   does not have; the weight is redistributed across what it does have, and
   the coverage is reported separately.

4. **The score gates AI features.** Below the threshold, the optimiser and the
   Copilot's inferential answers are withheld with a stated reason. A
   recommendation computed from stale detectors is a confident guess, and the
   confidence is the dangerous part.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.entities import (
    Camera, Intersection, Sensor, SignalController, SignalStateLog,
    TrafficMetric, TrafficObservation,
)
from app.traffic.quality_engine import DataQualityEngine

logger = logging.getLogger("trafficintel.analytics.trust")

# Bands
TRUSTED = "TRUSTED"
PARTIAL = "PARTIAL"
UNTRUSTED = "UNTRUSTED"
UNRATED = "UNRATED"

#: Below this composite score, AI features are withheld.
AI_GATE_THRESHOLD = 60.0

#: A junction needs at least this many scorable components before a composite
#: is reported. One component is a data point, not an assessment.
MIN_COMPONENTS_FOR_SCORE = 2


@dataclass
class TrustComponent:
    """One scored dimension of trust, or an explicit non-assessment."""

    name: str
    label: str
    weight: float
    score: Optional[float]          # 0-100, or None when nothing to measure
    status: str                     # SCORED | NOT_APPLICABLE | NOT_CONFIGURED
    explanation: str
    observed: Dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "weight": self.weight,
            "score": round(self.score, 1) if self.score is not None else None,
            "status": self.status,
            "explanation": self.explanation,
            "observed": self.observed,
        }


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _freshness_score(age_sec: Optional[float]) -> float:
    """Maps observation age onto 0-100 using the platform's own thresholds.

    Deliberately piecewise rather than a smooth decay: the bands are the same
    ones the console colours by, so a junction scoring 70 is visibly the same
    'AGING' the operator sees on the map. A smooth curve would produce numbers
    that disagree with the colours beside them.
    """
    if age_sec is None or age_sec < 0:
        return 0.0

    fresh = DataQualityEngine.fresh_threshold_sec()
    aging = DataQualityEngine.aging_threshold_sec()
    stale = DataQualityEngine.stale_threshold_sec()

    if age_sec <= fresh:
        return 100.0
    if age_sec <= aging:
        # 100 -> 70 across the AGING band.
        span = max(1.0, aging - fresh)
        return 100.0 - 30.0 * ((age_sec - fresh) / span)
    if age_sec <= stale:
        # 70 -> 30 across the STALE band.
        span = max(1.0, stale - aging)
        return 70.0 - 40.0 * ((age_sec - aging) / span)
    return 0.0


class TrustScore:
    """Computes a junction's data-quality trust score from real provenance."""

    @classmethod
    def for_intersection(
        cls, db: Session, intersection_id: str, window_minutes: int = 60
    ) -> Dict[str, Any]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        if not inter:
            return {
                "intersection_id": intersection_id,
                "band": UNRATED,
                "score": None,
                "explanation": "No such junction is configured.",
                "components": [],
            }

        now = datetime.now(timezone.utc)
        since = _naive(now - timedelta(minutes=window_minutes))

        components = [
            cls._controller_component(db, intersection_id, now),
            cls._telemetry_freshness_component(db, intersection_id, now),
            cls._detector_component(db, intersection_id, now),
            cls._signal_log_component(db, intersection_id, since, window_minutes),
            cls._sample_density_component(db, intersection_id, since, window_minutes),
        ]

        scored = [c for c in components if c.status == "SCORED" and c.score is not None]

        if len(scored) < MIN_COMPONENTS_FOR_SCORE:
            return cls._unrated(inter, components, scored, window_minutes)

        # Weights are renormalised across scorable components only, so a
        # junction is never penalised for equipment it does not have.
        total_weight = sum(c.weight for c in scored)
        composite = sum(c.score * c.weight for c in scored) / total_weight

        band = (
            TRUSTED if composite >= 80
            else PARTIAL if composite >= AI_GATE_THRESHOLD
            else UNTRUSTED
        )

        ai_allowed = composite >= AI_GATE_THRESHOLD
        weakest = min(scored, key=lambda c: c.score)

        return {
            "intersection_id": intersection_id,
            "intersection_name": inter.name,
            "score": round(composite, 1),
            "band": band,
            "window_minutes": window_minutes,
            "components": [c.as_dict() for c in components],
            "components_scored": len(scored),
            "components_not_applicable": len(components) - len(scored),
            "weight_basis": (
                "Renormalised across the {} scorable component(s). A junction is not "
                "penalised for equipment it does not have; missing equipment is "
                "reported as coverage, not as a low score.".format(len(scored))
            ),
            "weakest_component": {
                "name": weakest.name,
                "score": round(weakest.score, 1),
                "explanation": weakest.explanation,
            },
            "ai_gate": {
                "allowed": ai_allowed,
                "threshold": AI_GATE_THRESHOLD,
                "reason": (
                    None if ai_allowed else
                    "Trust score {:.1f} is below the {:.0f} threshold. AI recommendations "
                    "are withheld because a proposal computed from data this stale would "
                    "carry a confidence its inputs do not support. The limiting factor is "
                    "{}: {}".format(
                        composite, AI_GATE_THRESHOLD, weakest.label, weakest.explanation
                    )
                ),
            },
            "computed_at": now.isoformat(),
        }

    # ------------------------------------------------------------------
    # Components
    # ------------------------------------------------------------------

    @classmethod
    def _controller_component(
        cls, db: Session, intersection_id: str, now: datetime
    ) -> TrustComponent:
        controller = (
            db.query(SignalController)
            .filter(SignalController.intersection_id == intersection_id)
            .first()
        )

        if controller is None:
            return TrustComponent(
                "controller_readable", "Controller readability", 0.30, None,
                "NOT_CONFIGURED",
                "No signal controller is configured at this junction.",
            )

        heartbeat = _as_utc(controller.last_heartbeat)
        age = (now - heartbeat).total_seconds() if heartbeat else None

        if controller.connection_status == "CONNECTED":
            score = _freshness_score(age)
            explanation = (
                "Controller has a live protocol session; last heartbeat {:.0f}s ago."
                .format(age) if age is not None else
                "Controller reports CONNECTED but has no recorded heartbeat."
            )
            if age is None:
                score = 50.0
        elif controller.connection_status == "REACHABLE":
            # Reachable but unreadable is a real, partial state: the cabinet
            # answers, but nothing it says can be read.
            score = 25.0
            explanation = (
                "Controller answers on its port but its phase state cannot be read "
                "(no protocol session), so no signal state is grounded in hardware."
            )
        else:
            score = 0.0
            explanation = "Controller is {}; no state is being read.".format(
                controller.connection_status
            )

        return TrustComponent(
            "controller_readable", "Controller readability", 0.30, score, "SCORED",
            explanation,
            {
                "connection_status": controller.connection_status,
                "protocol": controller.protocol,
                "last_heartbeat_age_sec": round(age, 1) if age is not None else None,
            },
        )

    @classmethod
    def _telemetry_freshness_component(
        cls, db: Session, intersection_id: str, now: datetime
    ) -> TrustComponent:
        metric = (
            db.query(TrafficMetric)
            .filter(TrafficMetric.intersection_id == intersection_id)
            .order_by(TrafficMetric.timestamp.desc())
            .first()
        )

        if metric is None:
            return TrustComponent(
                "telemetry_freshness", "Telemetry freshness", 0.30, None,
                "NOT_APPLICABLE",
                "No traffic telemetry has ever been recorded for this junction.",
            )

        observed_at = _as_utc(metric.timestamp)
        age = (now - observed_at).total_seconds() if observed_at else None
        score = _freshness_score(age)
        state, _ = DataQualityEngine.evaluate_freshness(metric.timestamp)

        return TrustComponent(
            "telemetry_freshness", "Telemetry freshness", 0.30, score, "SCORED",
            "Most recent traffic metric is {:.0f}s old ({}).".format(age or 0.0, state),
            {
                "observed_at": observed_at.isoformat() if observed_at else None,
                "age_sec": round(age, 1) if age is not None else None,
                "quality_state": state,
                "calculation_method": metric.calculation_method,
            },
        )

    @classmethod
    def _detector_component(
        cls, db: Session, intersection_id: str, now: datetime
    ) -> TrustComponent:
        sensors = db.query(Sensor).filter(
            Sensor.intersection_id == intersection_id
        ).all()
        cameras = db.query(Camera).filter(
            Camera.intersection_id == intersection_id
        ).all()

        total_devices = len(sensors) + len(cameras)
        if total_devices == 0:
            return TrustComponent(
                "detector_health", "Detector health", 0.20, None, "NOT_CONFIGURED",
                "No detectors or cameras are configured at this junction.",
            )

        reporting = 0
        never_reported = 0
        for sensor in sensors:
            seen = _as_utc(sensor.last_observation_timestamp)
            if seen is None:
                never_reported += 1
            elif (now - seen).total_seconds() <= DataQualityEngine.stale_threshold_sec():
                reporting += 1
        for camera in cameras:
            seen = _as_utc(camera.last_frame_timestamp)
            if seen is None:
                never_reported += 1
            elif (now - seen).total_seconds() <= DataQualityEngine.stale_threshold_sec():
                reporting += 1

        score = 100.0 * reporting / total_devices

        return TrustComponent(
            "detector_health", "Detector health", 0.20, score, "SCORED",
            "{} of {} configured device(s) reported within the staleness window"
            "{}.".format(
                reporting, total_devices,
                "; {} have never reported at all".format(never_reported)
                if never_reported else "",
            ),
            {
                "devices_configured": total_devices,
                "devices_reporting": reporting,
                "devices_never_reported": never_reported,
            },
        )

    @classmethod
    def _signal_log_component(
        cls, db: Session, intersection_id: str, since: datetime, window_minutes: int
    ) -> TrustComponent:
        readings = (
            db.query(SignalStateLog)
            .filter(
                SignalStateLog.intersection_id == intersection_id,
                SignalStateLog.timestamp >= since,
            )
            .count()
        )

        controller = (
            db.query(SignalController)
            .filter(SignalController.intersection_id == intersection_id)
            .first()
        )
        if controller is None:
            return TrustComponent(
                "signal_state_coverage", "Signal state coverage", 0.10, None,
                "NOT_CONFIGURED",
                "No controller is configured, so no signal state can be observed.",
            )

        if readings == 0:
            return TrustComponent(
                "signal_state_coverage", "Signal state coverage", 0.10, 0.0, "SCORED",
                "No signal state was observed in the last {} minutes, so phase-based "
                "measures cannot be grounded.".format(window_minutes),
                {"readings_in_window": 0, "window_minutes": window_minutes},
            )

        # One reading per 10 seconds of the window is treated as full coverage.
        expected = max(1.0, (window_minutes * 60) / 10.0)
        score = min(100.0, 100.0 * readings / expected)

        return TrustComponent(
            "signal_state_coverage", "Signal state coverage", 0.10, score, "SCORED",
            "{} signal state reading(s) in the last {} minutes.".format(
                readings, window_minutes
            ),
            {
                "readings_in_window": readings,
                "readings_for_full_coverage": int(expected),
                "window_minutes": window_minutes,
            },
        )

    @classmethod
    def _sample_density_component(
        cls, db: Session, intersection_id: str, since: datetime, window_minutes: int
    ) -> TrustComponent:
        observations = (
            db.query(TrafficObservation)
            .filter(
                TrafficObservation.intersection_id == intersection_id,
                TrafficObservation.timestamp >= since,
            )
            .count()
        )

        has_devices = (
            db.query(Sensor).filter(Sensor.intersection_id == intersection_id).count()
            + db.query(Camera).filter(Camera.intersection_id == intersection_id).count()
        )
        if has_devices == 0:
            return TrustComponent(
                "sample_density", "Observation density", 0.10, None, "NOT_CONFIGURED",
                "No detector is configured, so there is no expected observation rate.",
            )

        # One observation per minute per junction is treated as full density.
        expected = max(1.0, float(window_minutes))
        score = min(100.0, 100.0 * observations / expected)

        return TrustComponent(
            "sample_density", "Observation density", 0.10, score, "SCORED",
            "{} observation(s) stored in the last {} minutes against an expected "
            "{:.0f}.".format(observations, window_minutes, expected),
            {
                "observations_in_window": observations,
                "expected_observations": int(expected),
                "window_minutes": window_minutes,
            },
        )

    # ------------------------------------------------------------------

    @classmethod
    def _unrated(
        cls,
        inter: Intersection,
        components: List[TrustComponent],
        scored: List[TrustComponent],
        window_minutes: int,
    ) -> Dict[str, Any]:
        missing = [c.label for c in components if c.status != "SCORED"]
        return {
            "intersection_id": inter.id,
            "intersection_name": inter.name,
            # Explicitly null, never 0: nothing was measured badly, nothing was
            # measured at all.
            "score": None,
            "band": UNRATED,
            "window_minutes": window_minutes,
            "components": [c.as_dict() for c in components],
            "components_scored": len(scored),
            "components_not_applicable": len(components) - len(scored),
            "explanation": (
                "Only {} scorable component(s); {} are required. This junction is "
                "UNRATED rather than scored zero: a score of zero would mean "
                "'measured and bad', and nothing here has been measured. Not "
                "assessable: {}.".format(
                    len(scored), MIN_COMPONENTS_FOR_SCORE, ", ".join(missing) or "none"
                )
            ),
            "ai_gate": {
                "allowed": False,
                "threshold": AI_GATE_THRESHOLD,
                "reason": (
                    "AI recommendations are withheld for unrated junctions. There is "
                    "not enough measured data here to assess whether a recommendation "
                    "would rest on anything."
                ),
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------

    @classmethod
    def for_network(
        cls, db: Session, window_minutes: int = 60
    ) -> Dict[str, Any]:
        """Trust across every configured junction."""
        intersections = db.query(Intersection).all()
        scores = [
            cls.for_intersection(db, inter.id, window_minutes)
            for inter in intersections
        ]

        rated = [s for s in scores if s["score"] is not None]
        by_band: Dict[str, int] = {}
        for entry in scores:
            by_band[entry["band"]] = by_band.get(entry["band"], 0) + 1

        return {
            "junction_count": len(scores),
            "rated_count": len(rated),
            "unrated_count": len(scores) - len(rated),
            "by_band": by_band,
            # A network mean over rated junctions only, stated as such. An
            # average that silently counted unrated junctions as zero would
            # make an uninstrumented network look like a failing one.
            "mean_score_of_rated": (
                round(sum(s["score"] for s in rated) / len(rated), 1) if rated else None
            ),
            "mean_basis": (
                "Mean over the {} rated junction(s) only. Unrated junctions are "
                "excluded rather than counted as zero.".format(len(rated))
            ),
            "ai_gated_junctions": [
                {"intersection_id": s["intersection_id"], "reason": s["ai_gate"]["reason"]}
                for s in scores if not s["ai_gate"]["allowed"]
            ],
            "junctions": scores,
            "window_minutes": window_minutes,
            "empty_reason": None if scores else "NO_JUNCTIONS_CONFIGURED",
        }
