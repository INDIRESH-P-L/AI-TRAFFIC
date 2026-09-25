"""TRAFFICINTEL AI - Statistical Anomaly Detection on Stored Telemetry

Flags readings that are statistically unusual for a junction, using only the
`traffic_metrics` rows the platform actually stored. Two complementary tests:

* **Point anomaly** - a prediction-interval test. For a baseline of n samples
  with mean x̄ and sample deviation s, a new reading x gives

        T = (x - x̄) / (s * sqrt(1 + 1/n))

  which follows Student's t with n-1 degrees of freedom when the reading comes
  from the same process as the baseline. The two-sided p-value is exact (see
  `stats.student_t_two_sided_p`) and the reported confidence is 1 - p.

  This is what makes confidence *derived from sample size*: the same deviation
  measured against a smaller baseline has fewer degrees of freedom and a wider
  prediction interval, so it earns a lower confidence. A 3-sigma reading
  against 30 samples is less certain than against 300, and the number says so.

* **Sustained shift** - a two-sided tabular CUSUM (k = 0.5, h = 5, the
  standard design for detecting a one-sigma shift) run over the test window.
  A CUSUM alarm is only a *suspicion*: it is reported as a measured anomaly
  only after Welch's test (reused from post-change verification) confirms the
  post-onset readings differ from the baseline with a 95% interval excluding
  zero. An alarm with too few post-onset samples to test is reported as
  suspected, never as confirmed.

Refusals, in the platform's vocabulary:

* `NOT_COMPUTABLE` - the metric was never recorded for this junction (no speed
  sensor, so no speed anomaly), or the baseline has zero variance and the test
  statistic does not exist. Waiting will not fix either.
* `INSUFFICIENT_DATA` - the metric exists, but there is nothing recent to test
  or too few baseline samples to test it against. Not a finding that
  conditions are normal.

Multiple testing: every reading in the test window is a separate test, so the
family-wise alpha is Bonferroni-divided across them. Without that, a quiet
fifteen-minute window of one-minute samples would raise a false flag at 1%
per reading - roughly one junction in seven every quarter hour, network-wide.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.analytics.stats import mean, sample_std, student_t_two_sided_p
from app.analytics.verification import welch_compare
from app.models.entities import Intersection, TrafficMetric

METHOD_VERSION = "anomaly-v1"

#: The three measured quantities this detector examines, keyed by column.
METRICS: Dict[str, Dict[str, str]] = {
    "flow_rate_vph": {"label": "Throughput", "unit": "veh/h"},
    "occupancy_pct": {"label": "Occupancy", "unit": "%"},
    "avg_speed_kph": {"label": "Average speed", "unit": "km/h"},
}

#: Below this many baseline samples no anomaly is reported. The t-test is
#: formally valid for smaller n, but its interval becomes so wide that the
#: only readings it could flag are physically implausible ones, and a detector
#: that is silent for structural reasons must say so rather than read as calm.
MIN_BASELINE_SAMPLES = 30

#: Family-wise significance level per metric, before Bonferroni division.
FAMILY_ALPHA = 0.01

#: Half-width of the same-time-of-day baseline band.
TIME_OF_DAY_HALF_WIDTH_MIN = 30

#: A same-time-of-day sample must be at least this old, which guarantees it
#: came from a previous day rather than from the window being tested.
TIME_OF_DAY_MIN_AGE_HOURS = 12

#: Fallback baseline when not enough same-time-of-day history exists.
RECENT_BASELINE_HOURS = 2

CUSUM_K = 0.5
CUSUM_H = 5.0

#: Rows with these quality states are not measurements and are excluded.
EXCLUDED_QUALITY = {"INVALID", "NO_DATA"}

MEASURED_ANOMALY = "MEASURED_ANOMALY"
NO_ANOMALY = "NO_ANOMALY"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
NOT_COMPUTABLE = "NOT_COMPUTABLE"


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _minutes_of_day(value: datetime) -> float:
    return value.hour * 60 + value.minute + value.second / 60.0


def _circular_minutes_apart(a: float, b: float) -> float:
    diff = abs(a - b) % 1440
    return min(diff, 1440 - diff)


def _welch_confidence(first: List[float], second: List[float]) -> Optional[float]:
    """1 - p for Welch's unequal-variance t statistic, computed exactly.

    Computed directly from the samples with the Welch-Satterthwaite degrees of
    freedom, rather than back-derived from the reported interval: the interval
    uses an interpolated critical value, and inverting it would print a
    confidence carrying that interpolation's error.
    """
    n1, n2 = len(first), len(second)
    if n1 < 2 or n2 < 2:
        return None
    v1, v2 = sample_std(first) ** 2 / n1, sample_std(second) ** 2 / n2
    standard_error = math.sqrt(v1 + v2)
    if standard_error <= 0:
        return None
    df = (v1 + v2) ** 2 / ((v1 ** 2) / (n1 - 1) + (v2 ** 2) / (n2 - 1))
    t_value = abs(mean(second) - mean(first)) / standard_error
    return round(1.0 - student_t_two_sided_p(t_value, df), 6)


Sample = Tuple[datetime, float, str, Optional[str]]  # (timestamp, value, row id, quality)


class AnomalyDetector:
    """Point and sustained-shift anomaly detection over stored metrics."""

    @classmethod
    def detect(
        cls,
        db: Session,
        intersection_id: str,
        as_of: Optional[datetime] = None,
        test_minutes: int = 15,
        history_days: int = 7,
    ) -> Dict[str, Any]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        if inter is None:
            return {"status": "NOT_FOUND", "detail": "No such junction."}

        as_of = _naive(as_of or datetime.now(timezone.utc))
        test_start = as_of - timedelta(minutes=test_minutes)
        history_start = as_of - timedelta(days=history_days)

        rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= history_start,
                TrafficMetric.timestamp <= as_of,
            )
            .order_by(TrafficMetric.timestamp.asc())
            .all()
        )
        excluded_rows = sum(1 for r in rows if (r.data_quality or "").upper() in EXCLUDED_QUALITY)
        usable = [r for r in rows if (r.data_quality or "").upper() not in EXCLUDED_QUALITY]

        results = []
        for metric in METRICS:
            samples: List[Sample] = [
                (r.timestamp, float(getattr(r, metric)), r.id, r.data_quality)
                for r in usable
                if getattr(r, metric) is not None
            ]
            results.append(cls._evaluate_metric(metric, samples, as_of, test_start))

        return cls._summarise(
            inter, results, as_of, test_start, history_start, len(rows), excluded_rows,
        )

    # ------------------------------------------------------------------

    @classmethod
    def _evaluate_metric(
        cls,
        metric: str,
        samples: List[Sample],
        as_of: datetime,
        test_start: datetime,
    ) -> Dict[str, Any]:
        info = METRICS[metric]
        base = {"metric": metric, "label": info["label"], "unit": info["unit"]}

        if not samples:
            return {
                **base,
                "status": NOT_COMPUTABLE,
                "reason": "NO_STORED_VALUES_FOR_METRIC",
                "explanation": (
                    "No {} value has been stored for this junction in the history "
                    "window. There is no series to test; connect a source that "
                    "measures it. Waiting will not help.".format(info["label"].lower())
                ),
            }

        test = [s for s in samples if s[0] > test_start]
        if not test:
            return {
                **base,
                "status": INSUFFICIENT_DATA,
                "reason": "NO_SAMPLES_IN_TEST_WINDOW",
                "explanation": (
                    "{} has history but nothing was recorded in the last test window, "
                    "so there is nothing current to test. This is not a finding that "
                    "conditions are normal.".format(info["label"])
                ),
                "most_recent_sample_at": samples[-1][0].isoformat(),
            }

        baseline, mode, caveat, candidates = cls._choose_baseline(samples, test_start, as_of)
        if baseline is None:
            return {
                **base,
                "status": INSUFFICIENT_DATA,
                "reason": "BASELINE_TOO_SMALL",
                "explanation": (
                    "At least {} baseline samples are required and neither baseline "
                    "had enough (same time of day on previous days: {}; preceding "
                    "{} h: {}). No anomaly is reported rather than one measured "
                    "against too little history.".format(
                        MIN_BASELINE_SAMPLES, candidates["same_time_of_day"],
                        RECENT_BASELINE_HOURS, candidates["recent_window"],
                    )
                ),
                "minimum_baseline_samples": MIN_BASELINE_SAMPLES,
                "baseline_candidates": candidates,
            }

        values = [s[1] for s in baseline]
        n = len(values)
        mu = mean(values)
        sigma = sample_std(values)

        baseline_block = {
            "mode": mode,
            "sample_size": n,
            "minimum_samples": MIN_BASELINE_SAMPLES,
            "mean": round(mu, 3),
            "std_dev": round(sigma, 3),
            "window_start": baseline[0][0].isoformat(),
            "window_end": baseline[-1][0].isoformat(),
            "caveat": caveat,
        }
        test_block = {
            "window_start": test_start.isoformat(),
            "window_end": as_of.isoformat(),
            "sample_size": len(test),
        }

        if sigma < 1e-9:
            return {
                **base,
                "status": NOT_COMPUTABLE,
                "reason": "BASELINE_HAS_ZERO_VARIANCE",
                "explanation": (
                    "Every baseline reading is identical ({:.3f} {}), so no deviation "
                    "can be expressed in standard deviations and the test statistic "
                    "does not exist. A constant series usually means a stuck or "
                    "placeholder feed rather than genuinely constant traffic."
                    .format(mu, info["unit"])
                ),
                "baseline": baseline_block,
                "test_window": test_block,
            }

        # --- point anomalies ------------------------------------------------
        per_point_alpha = FAMILY_ALPHA / len(test)
        scale = sigma * math.sqrt(1.0 + 1.0 / n)
        flagged = []
        for timestamp, value, row_id, quality in test:
            t_stat = (value - mu) / scale
            p_value = student_t_two_sided_p(t_stat, n - 1)
            if p_value < per_point_alpha:
                flagged.append({
                    "timestamp": timestamp.isoformat(),
                    "value": round(value, 3),
                    "direction": "HIGH" if value > mu else "LOW",
                    "deviation_std": round((value - mu) / sigma, 2),
                    "t_statistic": round(t_stat, 3),
                    "degrees_of_freedom": n - 1,
                    "p_value": p_value,
                    "confidence": round(1.0 - p_value, 6),
                    "source_table": "traffic_metrics",
                    "source_row_id": row_id,
                    "recorded_quality": quality,
                })

        shift = cls._sustained_shift(metric, test, values, mu, sigma)
        anomalous = bool(flagged) or (shift is not None and shift["status"] == "CONFIRMED")

        confidences = [f["confidence"] for f in flagged]
        if shift and shift["status"] == "CONFIRMED" and shift.get("confidence") is not None:
            confidences.append(shift["confidence"])

        if anomalous:
            explanation = (
                "{} reading(s) in the test window fall outside the baseline's "
                "prediction interval at a family-wise alpha of {} (Bonferroni over "
                "{} readings){}.".format(
                    len(flagged), FAMILY_ALPHA, len(test),
                    "; a sustained shift was also confirmed" if shift and shift["status"] == "CONFIRMED" else "",
                )
            )
        else:
            explanation = (
                "No reading in the test window falls outside the baseline's "
                "prediction interval at a family-wise alpha of {}, and no sustained "
                "shift was confirmed.".format(FAMILY_ALPHA)
            )

        return {
            **base,
            "status": MEASURED_ANOMALY if anomalous else NO_ANOMALY,
            "reason": None,
            "explanation": explanation,
            "confidence": max(confidences) if confidences else None,
            "confidence_basis": (
                "1 - p for the most extreme flagged reading, from Student's t with "
                "n-1 = {} degrees of freedom and a prediction interval widened by "
                "sqrt(1 + 1/n). A smaller baseline yields a lower confidence for "
                "the same deviation.".format(n - 1)
            ),
            "family_alpha": FAMILY_ALPHA,
            "per_reading_alpha": per_point_alpha,
            "baseline": baseline_block,
            "test_window": test_block,
            "flagged_points": flagged,
            "sustained_shift": shift,
        }

    @classmethod
    def _choose_baseline(
        cls, samples: List[Sample], test_start: datetime, test_end: datetime,
    ) -> Tuple[Optional[List[Sample]], Optional[str], Optional[str], Dict[str, int]]:
        prior = [s for s in samples if s[0] <= test_start]
        # Centred on the middle of the window being tested, not its start: the
        # band should describe the time of day actually under test, and
        # anchoring it at one edge skews it by half the window.
        centre = _minutes_of_day(test_start + (test_end - test_start) / 2)
        min_age = timedelta(hours=TIME_OF_DAY_MIN_AGE_HOURS)

        same_time = [
            s for s in prior
            if test_start - s[0] >= min_age
            and _circular_minutes_apart(_minutes_of_day(s[0]), centre) <= TIME_OF_DAY_HALF_WIDTH_MIN
        ]
        recent_start = test_start - timedelta(hours=RECENT_BASELINE_HOURS)
        recent = [s for s in prior if s[0] > recent_start]

        candidates = {"same_time_of_day": len(same_time), "recent_window": len(recent)}

        if len(same_time) >= MIN_BASELINE_SAMPLES:
            return same_time, "SAME_TIME_OF_DAY", (
                "Readings within {} min of the same time of day on previous days, "
                "which accounts for the daily traffic pattern.".format(TIME_OF_DAY_HALF_WIDTH_MIN)
            ), candidates

        if len(recent) >= MIN_BASELINE_SAMPLES:
            return recent, "RECENT_WINDOW", (
                "Fallback: the preceding {} h, because fewer than {} same-time-of-day "
                "readings exist. This does not account for the daily pattern, so the "
                "onset of a normal peak can register as an anomaly - check the time "
                "of day before acting on a flag.".format(
                    RECENT_BASELINE_HOURS, MIN_BASELINE_SAMPLES
                )
            ), candidates

        return None, None, None, candidates

    @classmethod
    def _sustained_shift(
        cls,
        metric: str,
        test: List[Sample],
        baseline_values: List[float],
        mu: float,
        sigma: float,
    ) -> Optional[Dict[str, Any]]:
        upper = lower = 0.0
        upper_zero_at = lower_zero_at = -1
        alarm_index = None
        direction = None

        for index, (_ts, value, _rid, _q) in enumerate(test):
            z = (value - mu) / sigma
            upper = max(0.0, upper + z - CUSUM_K)
            lower = max(0.0, lower - z - CUSUM_K)
            if upper == 0.0:
                upper_zero_at = index
            if lower == 0.0:
                lower_zero_at = index
            if upper > CUSUM_H:
                alarm_index, direction = index, "HIGH"
                break
            if lower > CUSUM_H:
                alarm_index, direction = index, "LOW"
                break

        if alarm_index is None:
            return None

        onset_index = (upper_zero_at if direction == "HIGH" else lower_zero_at) + 1
        post_onset = [s[1] for s in test[onset_index:]]
        comparison = welch_compare(baseline_values, post_onset, metric)

        shift = {
            "direction": direction,
            "alarm_at": test[alarm_index][0].isoformat(),
            "estimated_onset_at": test[onset_index][0].isoformat(),
            "post_onset_samples": len(post_onset),
            "cusum_parameters": {"k": CUSUM_K, "h": CUSUM_H},
            "confirmation_test": comparison.as_dict(),
        }

        if comparison.ci_low is None:
            shift.update({
                "status": "SUSPECTED_TOO_FEW_SAMPLES_TO_CONFIRM",
                "confidence": None,
                "explanation": (
                    "CUSUM raised an alarm, but only {} readings follow the estimated "
                    "onset - too few for Welch's test to confirm the shift. Reported "
                    "as a suspicion, not an anomaly.".format(len(post_onset))
                ),
            })
            return shift

        excludes_zero = comparison.ci_low > 0 or comparison.ci_high < 0
        agrees = (comparison.difference or 0) > 0 if direction == "HIGH" else (comparison.difference or 0) < 0
        if excludes_zero and agrees:
            confidence = _welch_confidence(baseline_values, post_onset)
            shift.update({
                "status": "CONFIRMED",
                "confidence": confidence,
                "explanation": (
                    "CUSUM alarm confirmed: post-onset readings differ from the "
                    "baseline with a 95% interval of [{:.2f}, {:.2f}] {}, which "
                    "excludes zero.".format(
                        comparison.ci_low, comparison.ci_high, METRICS[metric]["unit"]
                    )
                ),
            })
        else:
            shift.update({
                "status": "NOT_CONFIRMED",
                "confidence": None,
                "explanation": (
                    "CUSUM raised an alarm, but Welch's test does not distinguish the "
                    "post-onset readings from the baseline. Not reported as an anomaly."
                ),
            })
        return shift

    @classmethod
    def _summarise(
        cls,
        inter: Intersection,
        results: List[Dict[str, Any]],
        as_of: datetime,
        test_start: datetime,
        history_start: datetime,
        rows_read: int,
        rows_excluded: int,
    ) -> Dict[str, Any]:
        statuses = [r["status"] for r in results]
        evaluated = [r["label"] for r in results if r["status"] in (MEASURED_ANOMALY, NO_ANOMALY)]
        not_evaluated = [
            "{} ({})".format(r["label"], r["reason"]) for r in results
            if r["status"] not in (MEASURED_ANOMALY, NO_ANOMALY)
        ]

        if MEASURED_ANOMALY in statuses:
            overall = MEASURED_ANOMALY
            flagged = [r["label"] for r in results if r["status"] == MEASURED_ANOMALY]
            detail = "Measured anomaly in: {}.".format(", ".join(flagged))
        elif NO_ANOMALY in statuses:
            overall = NO_ANOMALY
            detail = "No anomaly in the evaluated metrics ({}).".format(", ".join(evaluated))
        elif INSUFFICIENT_DATA in statuses:
            overall = INSUFFICIENT_DATA
            detail = "No metric had enough data to test."
        else:
            overall = NOT_COMPUTABLE
            detail = "None of the examined metrics is recorded for this junction."

        if not_evaluated and overall in (MEASURED_ANOMALY, NO_ANOMALY):
            detail += (
                " Not evaluated: {}. The absence of a flag there is not evidence "
                "that conditions are normal.".format("; ".join(not_evaluated))
            )

        return {
            "status": overall,
            "detail": detail,
            "intersection_id": inter.id,
            "intersection_name": inter.name,
            "as_of": as_of.isoformat(),
            "test_window_start": test_start.isoformat(),
            "history_start": history_start.isoformat(),
            "rows_read": rows_read,
            "rows_excluded_as_not_measurements": rows_excluded,
            "metrics_evaluated": evaluated,
            "metrics_not_evaluated": not_evaluated,
            "metrics": results,
            "method": (
                "Prediction-interval t-test per reading (Bonferroni across the test "
                "window) plus a two-sided CUSUM confirmed by Welch's test. Source: "
                "stored traffic_metrics rows only."
            ),
            "method_version": METHOD_VERSION,
            "data_kind": "MEASURED",
        }
