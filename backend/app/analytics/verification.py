"""TRAFFICINTEL AI - Post-Change Verification

After a timing change, compare the measured before and after and report one of:

    IMPROVED                  the change is larger than the noise
    DEGRADED                  likewise, in the wrong direction
    NO_MEASURABLE_CHANGE      a difference exists but is inside the noise
    INSUFFICIENT_DATA         not enough samples on one or both sides

**Why this needs a statistical test and not a mean comparison.** Traffic
metrics are noisy. Two thirty-minute windows at the same junction with no
change at all will differ by several percent, and a bare before/after mean
would report that as an improvement roughly half the time. A platform that
claims credit for noise is worse than one that stays silent, because it
teaches an agency to retime signals on the strength of randomness.

So: Welch's t-test (unequal variances, which is the realistic case when
demand differs between windows), with a confidence interval on the
difference. **When the interval contains zero, the verdict is
NO_MEASURABLE_CHANGE** — the data does not distinguish the change from
nothing, and saying so is the finding.

The t-distribution critical value is approximated rather than exact. The
approximation is stated on every result, and it is conservative at the sample
sizes this module refuses below.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.entities import (
    Intersection, SignalCommand, SignalController, TrafficMetric,
)

logger = logging.getLogger("trafficintel.analytics.verification")

IMPROVED = "IMPROVED"
DEGRADED = "DEGRADED"
NO_MEASURABLE_CHANGE = "NO_MEASURABLE_CHANGE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

#: Minimum samples on EACH side. Below this, no verdict is offered: a t-test
#: on four samples has so little power that "no measurable change" would mean
#: "we could not have detected one anyway".
MIN_SAMPLES_PER_SIDE = 8

CONFIDENCE = 0.95

#: Metrics that improve when they go DOWN.
LOWER_IS_BETTER = {"avg_wait_time_sec", "queue_length_meters", "occupancy_pct"}

METRIC_LABELS = {
    "avg_wait_time_sec": "Control delay",
    "queue_length_meters": "Queue length",
    "occupancy_pct": "Occupancy",
    "avg_speed_kph": "Average speed",
    "flow_rate_vph": "Flow rate",
}

METRIC_UNITS = {
    "avg_wait_time_sec": "s/veh",
    "queue_length_meters": "m",
    "occupancy_pct": "%",
    "avg_speed_kph": "km/h",
    "flow_rate_vph": "veh/h",
}


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _t_critical(df: float) -> float:
    """Two-tailed 95% critical value for Student's t.

    Interpolated from a small table rather than computed exactly, because
    doing it properly needs the inverse incomplete beta function and pulling
    SciPy in for one number is not a trade worth making here. The table is
    exact at its breakpoints and the interpolation is conservative between
    them; every result says so.
    """
    table = [
        (1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571),
        (6, 2.447), (7, 2.365), (8, 2.306), (9, 2.262), (10, 2.228),
        (12, 2.179), (15, 2.131), (20, 2.086), (25, 2.060), (30, 2.042),
        (40, 2.021), (60, 2.000), (120, 1.980),
    ]
    if df <= 1:
        return table[0][1]
    if df >= 120:
        return 1.960  # normal approximation

    for (df_low, t_low), (df_high, t_high) in zip(table, table[1:]):
        if df_low <= df <= df_high:
            span = df_high - df_low
            if span == 0:
                return t_low
            weight = (df - df_low) / span
            return t_low + weight * (t_high - t_low)
    return 1.960


@dataclass
class ComparisonResult:
    metric: str
    verdict: str
    before_mean: Optional[float]
    after_mean: Optional[float]
    difference: Optional[float]
    ci_low: Optional[float]
    ci_high: Optional[float]
    before_n: int
    after_n: int
    explanation: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "metric": self.metric,
            "label": METRIC_LABELS.get(self.metric, self.metric),
            "unit": METRIC_UNITS.get(self.metric),
            "verdict": self.verdict,
            "before_mean": self.before_mean,
            "after_mean": self.after_mean,
            "difference": self.difference,
            "confidence_interval": (
                [self.ci_low, self.ci_high]
                if self.ci_low is not None else None
            ),
            "confidence_level": CONFIDENCE,
            "before_sample_size": self.before_n,
            "after_sample_size": self.after_n,
            "minimum_samples_per_side": MIN_SAMPLES_PER_SIDE,
            "lower_is_better": self.metric in LOWER_IS_BETTER,
            "explanation": self.explanation,
        }


def welch_compare(
    before: List[float], after: List[float], metric: str
) -> ComparisonResult:
    """Welch's t-test with a confidence interval on the difference of means."""
    before_n, after_n = len(before), len(after)

    if before_n < MIN_SAMPLES_PER_SIDE or after_n < MIN_SAMPLES_PER_SIDE:
        return ComparisonResult(
            metric, INSUFFICIENT_DATA,
            round(statistics.mean(before), 2) if before else None,
            round(statistics.mean(after), 2) if after else None,
            None, None, None, before_n, after_n,
            (
                "{} sample(s) before and {} after; {} are required on each side. "
                "A test on fewer would lack the power to detect a real change, so "
                "'no measurable change' would be meaningless."
                .format(before_n, after_n, MIN_SAMPLES_PER_SIDE)
            ),
        )

    mean_before = statistics.mean(before)
    mean_after = statistics.mean(after)
    var_before = statistics.variance(before)
    var_after = statistics.variance(after)
    difference = mean_after - mean_before

    standard_error = math.sqrt(var_before / before_n + var_after / after_n)

    if standard_error == 0:
        # Both sides are constant. Either identical (no change) or a clean step.
        if difference == 0:
            return ComparisonResult(
                metric, NO_MEASURABLE_CHANGE,
                round(mean_before, 2), round(mean_after, 2), 0.0, 0.0, 0.0,
                before_n, after_n,
                "Both windows are identical constants; there is no difference to detect.",
            )
        verdict = _direction_verdict(metric, difference)
        return ComparisonResult(
            metric, verdict,
            round(mean_before, 2), round(mean_after, 2), round(difference, 2),
            round(difference, 2), round(difference, 2), before_n, after_n,
            (
                "Both windows are constant with no variance, so the difference of "
                "{:+.2f} carries no sampling uncertainty.".format(difference)
            ),
        )

    # Welch-Satterthwaite degrees of freedom.
    numerator = (var_before / before_n + var_after / after_n) ** 2
    denominator = (
        (var_before / before_n) ** 2 / (before_n - 1)
        + (var_after / after_n) ** 2 / (after_n - 1)
    )
    df = numerator / denominator if denominator > 0 else float(before_n + after_n - 2)

    margin = _t_critical(df) * standard_error
    ci_low = difference - margin
    ci_high = difference + margin

    # The interval containing zero is the whole decision: the data does not
    # distinguish this change from no change.
    if ci_low <= 0.0 <= ci_high:
        verdict = NO_MEASURABLE_CHANGE
        explanation = (
            "The difference of {:+.2f} has a 95% confidence interval of "
            "[{:+.2f}, {:+.2f}], which contains zero. The measurement does not "
            "distinguish this change from no change at all."
            .format(difference, ci_low, ci_high)
        )
    else:
        verdict = _direction_verdict(metric, difference)
        explanation = (
            "The difference of {:+.2f} has a 95% confidence interval of "
            "[{:+.2f}, {:+.2f}], which excludes zero, so the change is larger than "
            "the sampling noise.".format(difference, ci_low, ci_high)
        )

    return ComparisonResult(
        metric, verdict,
        round(mean_before, 2), round(mean_after, 2), round(difference, 2),
        round(ci_low, 2), round(ci_high, 2), before_n, after_n, explanation,
    )


def _direction_verdict(metric: str, difference: float) -> str:
    if metric in LOWER_IS_BETTER:
        return IMPROVED if difference < 0 else DEGRADED
    return IMPROVED if difference > 0 else DEGRADED


class PostChangeVerification:
    """Verifies whether a signal change measurably changed anything."""

    @classmethod
    def verify_command(
        cls,
        db: Session,
        command_id: str,
        window_minutes: int = 30,
        settle_minutes: int = 2,
    ) -> Dict[str, Any]:
        """Compares measured conditions before and after one signal command.

        A settling period immediately after the change is excluded from the
        'after' window: the first cycles following a timing change are a
        transition, not the new steady state, and including them would bias
        the comparison against every change.
        """
        command = db.query(SignalCommand).filter(SignalCommand.id == command_id).first()
        if command is None:
            return {"status": "NOT_FOUND", "detail": "No such signal command."}

        controller = (
            db.query(SignalController)
            .filter(SignalController.id == command.controller_id)
            .first()
        )
        if controller is None:
            return {
                "status": "NOT_COMPUTABLE",
                "detail": "The command's controller no longer exists.",
            }

        if command.status != "EXECUTED":
            return {
                "status": "NOT_APPLICABLE",
                "command_id": command_id,
                "command_status": command.status,
                "detail": (
                    "This command was {}, so nothing reached the hardware and there "
                    "is nothing to verify.".format(command.status)
                ),
            }

        changed_at = command.issued_at
        before_start = changed_at - timedelta(minutes=window_minutes)
        after_start = changed_at + timedelta(minutes=settle_minutes)
        after_end = after_start + timedelta(minutes=window_minutes)

        now = _naive(datetime.now(timezone.utc))
        window_complete = after_end <= now

        return cls._compare_windows(
            db,
            intersection_id=controller.intersection_id,
            before=(before_start, changed_at),
            after=(after_start, after_end),
            context={
                "command_id": command_id,
                "controller_id": controller.id,
                "requested_phase": command.requested_phase,
                "duration_sec": command.duration_sec,
                "changed_at": changed_at.isoformat(),
                "settle_minutes": settle_minutes,
                "window_minutes": window_minutes,
                "after_window_complete": window_complete,
                "after_window_note": (
                    None if window_complete else
                    "The after-window has not fully elapsed yet, so this verdict is "
                    "provisional and based on the samples recorded so far."
                ),
            },
        )

    @classmethod
    def verify_window(
        cls,
        db: Session,
        intersection_id: str,
        changed_at: datetime,
        window_minutes: int = 30,
        settle_minutes: int = 2,
        label: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compares before/after around an arbitrary operator-supplied moment."""
        changed_at = _naive(changed_at)
        return cls._compare_windows(
            db,
            intersection_id=intersection_id,
            before=(changed_at - timedelta(minutes=window_minutes), changed_at),
            after=(
                changed_at + timedelta(minutes=settle_minutes),
                changed_at + timedelta(minutes=settle_minutes + window_minutes),
            ),
            context={
                "label": label or "Operator-specified change",
                "changed_at": changed_at.isoformat(),
                "settle_minutes": settle_minutes,
                "window_minutes": window_minutes,
            },
        )

    # ------------------------------------------------------------------

    @classmethod
    def _collect(
        cls, db: Session, intersection_id: str, start: datetime, end: datetime
    ) -> List[TrafficMetric]:
        return (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= _naive(start),
                TrafficMetric.timestamp < _naive(end),
            )
            .order_by(TrafficMetric.timestamp.asc())
            .all()
        )

    @classmethod
    def _compare_windows(
        cls,
        db: Session,
        intersection_id: str,
        before: Tuple[datetime, datetime],
        after: Tuple[datetime, datetime],
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()

        before_rows = cls._collect(db, intersection_id, *before)
        after_rows = cls._collect(db, intersection_id, *after)

        comparisons: List[Dict[str, Any]] = []
        for metric in ("avg_wait_time_sec", "queue_length_meters", "occupancy_pct",
                       "avg_speed_kph", "flow_rate_vph"):
            before_values = [
                getattr(row, metric) for row in before_rows
                if getattr(row, metric) is not None
            ]
            after_values = [
                getattr(row, metric) for row in after_rows
                if getattr(row, metric) is not None
            ]
            if not before_values and not after_values:
                continue  # this metric was never recorded at all
            comparisons.append(
                welch_compare(before_values, after_values, metric).as_dict()
            )

        if not comparisons:
            return {
                "status": INSUFFICIENT_DATA,
                "overall_verdict": INSUFFICIENT_DATA,
                "intersection_id": intersection_id,
                "intersection_name": inter.name if inter else None,
                "before_window": [before[0].isoformat(), before[1].isoformat()],
                "after_window": [after[0].isoformat(), after[1].isoformat()],
                "comparisons": [],
                "detail": (
                    "No traffic telemetry was recorded on either side of this change, "
                    "so its effect cannot be measured. This is not evidence the change "
                    "had no effect."
                ),
                **context,
            }

        decided = [c for c in comparisons if c["verdict"] in (IMPROVED, DEGRADED)]
        insufficient = [c for c in comparisons if c["verdict"] == INSUFFICIENT_DATA]

        if not decided and insufficient:
            overall = INSUFFICIENT_DATA
            headline = (
                "Not enough samples on both sides to measure any metric. Nothing is "
                "being claimed about this change."
            )
        elif not decided:
            overall = NO_MEASURABLE_CHANGE
            headline = (
                "Every measured metric changed by less than its sampling noise. The "
                "data does not distinguish this change from no change."
            )
        else:
            improved = [c for c in decided if c["verdict"] == IMPROVED]
            degraded = [c for c in decided if c["verdict"] == DEGRADED]
            if improved and not degraded:
                overall = IMPROVED
                headline = "{} metric(s) improved beyond the noise; none degraded.".format(
                    len(improved)
                )
            elif degraded and not improved:
                overall = DEGRADED
                headline = "{} metric(s) degraded beyond the noise; none improved.".format(
                    len(degraded)
                )
            else:
                overall = "MIXED"
                headline = (
                    "{} metric(s) improved and {} degraded beyond the noise. The change "
                    "traded one against the other rather than improving overall."
                    .format(len(improved), len(degraded))
                )

        return {
            "status": "COMPUTED",
            "overall_verdict": overall,
            "headline": headline,
            "intersection_id": intersection_id,
            "intersection_name": inter.name if inter else None,
            "before_window": [before[0].isoformat(), before[1].isoformat()],
            "after_window": [after[0].isoformat(), after[1].isoformat()],
            "before_samples": len(before_rows),
            "after_samples": len(after_rows),
            "comparisons": comparisons,
            "method": (
                "Welch's t-test (unequal variances) with a {:.0f}% confidence interval "
                "on the difference of means. A verdict of NO_MEASURABLE_CHANGE means "
                "the interval contains zero."
                .format(CONFIDENCE * 100)
            ),
            "method_caveats": [
                "The t critical value is interpolated from a table rather than computed "
                "exactly; it is conservative at these sample sizes.",
                "A settling period immediately after the change is excluded, because "
                "the first cycles after a retime are a transition, not the new steady "
                "state.",
                "Demand is not controlled for. A change measured during a different "
                "traffic pattern may reflect the pattern rather than the change.",
            ],
            **context,
        }

    @classmethod
    def recent_verifications(
        cls, db: Session, intersection_id: Optional[str] = None, limit: int = 10,
        window_minutes: int = 30,
    ) -> Dict[str, Any]:
        """Verifies the most recent executed commands."""
        query = db.query(SignalCommand).filter(SignalCommand.status == "EXECUTED")

        if intersection_id:
            controller_ids = [
                c.id for c in db.query(SignalController)
                .filter(SignalController.intersection_id == intersection_id).all()
            ]
            if not controller_ids:
                return {
                    "count": 0,
                    "verifications": [],
                    "empty_reason": "NO_CONTROLLER_AT_THIS_JUNCTION",
                }
            query = query.filter(SignalCommand.controller_id.in_(controller_ids))

        commands = query.order_by(SignalCommand.issued_at.desc()).limit(limit).all()

        return {
            "count": len(commands),
            "empty_reason": None if commands else "NO_EXECUTED_COMMANDS_TO_VERIFY",
            "verifications": [
                cls.verify_command(db, command.id, window_minutes=window_minutes)
                for command in commands
            ],
        }
