"""TRAFFICINTEL AI - Short-Horizon Forecasting from Stored Telemetry

Fits an autoregressive model to one junction's stored `traffic_metrics` history
and forecasts the next few bins - or refuses, with a fitted model behind the
refusal.

The model, stated exactly
-------------------------
ARIMA(p, d, 0): an autoregression of order p on the series differenced d times,
fitted by conditional least squares. There are **no moving-average terms**. That
is a real subset of ARIMA, not the full family; it is named as such everywhere
this module reports, because a response claiming "ARIMA" would imply MA terms
nobody fitted. The platform carries no statsmodels (see `stats.py`), and an AR
model with a transparent solver is preferable to an opaque fit nobody can audit.

How the refusal gets a model behind it
--------------------------------------
Previously INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST fired whenever there were
fewer than 100 rows, and "enough rows" led only to NO_FORECAST_MODEL_REGISTERED.
Now there are three ways to be refused, and two of them are measured:

1. **Not enough gap-free history** to train and backtest. Gaps are never
   interpolated: the model trains on the longest gap-free run ending at the
   latest complete bin, consistent with the stringline and replay endpoints.
2. **The latest data is too old** to be a forecast origin - a "next hour"
   forecast from a series that stopped three hours ago predicts the past.
3. **No measured skill.** Every candidate order is backtested by rolling-origin
   evaluation (refit at each origin, no look-ahead) and compared with naive
   persistence - "the next bin equals the last one". A model that cannot beat
   persistence by at least MIN_SKILL_OVER_PERSISTENCE on the junction's own
   history is refused, and the refusal reports that model and its measured
   error. That is the case the old code could never state honestly.

Every forecast point is stamped SCENARIO / HYPOTHETICAL and carries a 95%
interval. The interval's measured coverage on the backtest is reported beside
it, so an operator can see whether the stated 95% held on this junction's own
data.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.analytics.stats import mean, ordinary_least_squares
from app.analytics.verification import _t_critical
from app.models.entities import Intersection, TrafficMetric
from app.scenario.sandbox import SCENARIO_STAMP

METHOD_VERSION = "arima-p-d-0-cls-v1"

FORECASTABLE: Dict[str, Dict[str, Any]] = {
    "flow_rate_vph": {"label": "Throughput", "unit": "veh/h", "bounds": (0.0, None)},
    "occupancy_pct": {"label": "Occupancy", "unit": "%", "bounds": (0.0, 100.0)},
    "avg_speed_kph": {"label": "Average speed", "unit": "km/h", "bounds": (0.0, None)},
}

ALLOWED_BIN_MINUTES = (5, 15, 60)
DEFAULT_BIN_MINUTES = 15

#: Minimum bins the earliest backtest fit may be trained on.
MIN_TRAINING_BINS = 48

#: Upper bound on training length; older history adds cost without helping a
#: short-horizon forecast.
MAX_TRAINING_BINS = 672

#: Rolling-origin backtest origins per candidate model.
BACKTEST_ORIGINS = 12

MAX_HORIZON_BINS = 8

#: Observed bins returned for context beside a forecast or refusal.
RECENT_BINS_RETURNED = 16

#: The latest complete bin must be at most this many bins behind "now".
MAX_ORIGIN_STALENESS_BINS = 2

#: Minimum fractional MAE reduction over persistence before a forecast is
#: offered. A model only marginally better than repeating the last value is not
#: reliable enough to plan against.
MIN_SKILL_OVER_PERSISTENCE = 0.10

CANDIDATE_ORDERS: List[Tuple[int, int]] = [(p, d) for d in (0, 1) for p in (1, 2, 3)]

EXCLUDED_QUALITY = {"INVALID", "NO_DATA"}

FORECAST_AVAILABLE = "FORECAST_AVAILABLE"
REFUSED = "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST"
NOT_COMPUTABLE = "NOT_COMPUTABLE"


def _naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

class ArModel:
    """ARIMA(p, d, 0) fitted by conditional least squares."""

    def __init__(self, p: int, d: int):
        self.p = p
        self.d = d
        self.intercept: Optional[float] = None
        self.phi: List[float] = []
        self.sigma2: Optional[float] = None
        self.residual_df: Optional[int] = None
        self.training_length = 0

    @property
    def order(self) -> str:
        return "ARIMA({},{},0)".format(self.p, self.d)

    def fit(self, series: List[float]) -> bool:
        working = self._difference(series)
        rows, targets = [], []
        for t in range(self.p, len(working)):
            rows.append([1.0] + [working[t - i] for i in range(1, self.p + 1)])
            targets.append(working[t])

        # At least twice as many equations as coefficients, or the residual
        # variance - and so every interval - is estimated from almost nothing.
        if len(rows) < 2 * (self.p + 1):
            return False
        coefficients = ordinary_least_squares(rows, targets)
        if coefficients is None:
            return False

        self.intercept = coefficients[0]
        self.phi = coefficients[1:]
        residuals = [
            y - sum(c * x for c, x in zip(coefficients, row))
            for row, y in zip(rows, targets)
        ]
        self.residual_df = len(rows) - (self.p + 1)
        if self.residual_df <= 0:
            return False
        self.sigma2 = sum(r * r for r in residuals) / self.residual_df
        self.training_length = len(series)
        return True

    def _difference(self, series: List[float]) -> List[float]:
        if self.d == 0:
            return list(series)
        return [series[i] - series[i - 1] for i in range(1, len(series))]

    def forecast(self, series: List[float], horizon: int) -> List[float]:
        working = self._difference(series)
        history = list(working)
        predicted = []
        for _ in range(horizon):
            value = self.intercept + sum(
                self.phi[i - 1] * history[-i] for i in range(1, self.p + 1)
            )
            history.append(value)
            predicted.append(value)
        if self.d == 0:
            return predicted
        level = series[-1]
        levels = []
        for step in predicted:
            level += step
            levels.append(level)
        return levels

    def interval_half_widths(self, horizon: int) -> List[float]:
        """95% half-widths from psi weights and Student's t on residual df."""
        psi = [1.0]
        for j in range(1, horizon):
            psi.append(sum(
                self.phi[i - 1] * psi[j - i] for i in range(1, min(j, self.p) + 1)
            ))
        if self.d == 1:
            cumulative, running = [], 0.0
            for weight in psi:
                running += weight
                cumulative.append(running)
            psi = cumulative
        critical = _t_critical(self.residual_df)
        widths, accumulated = [], 0.0
        for weight in psi:
            accumulated += weight * weight
            widths.append(critical * math.sqrt(self.sigma2 * accumulated))
        return widths

    def describe(self) -> Dict[str, Any]:
        return {
            "family": "ARIMA(p,d,0) - autoregressive, no moving-average terms",
            "order": self.order,
            "p": self.p,
            "d": self.d,
            "intercept": round(self.intercept, 6),
            "ar_coefficients": [round(c, 6) for c in self.phi],
            "residual_std": round(math.sqrt(self.sigma2), 4),
            "residual_degrees_of_freedom": self.residual_df,
            "estimation": "Conditional least squares (normal equations, partial pivoting)",
            "training_bins": self.training_length,
        }


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------

class ShortHorizonForecaster:
    """Bins stored telemetry, selects a model by backtest, forecasts or refuses."""

    @classmethod
    def forecast(
        cls,
        db: Session,
        intersection_id: str,
        metric: str = "flow_rate_vph",
        bin_minutes: int = DEFAULT_BIN_MINUTES,
        horizon_bins: int = 4,
        history_days: int = 7,
        as_of: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        inter = db.query(Intersection).filter(Intersection.id == intersection_id).first()
        if inter is None:
            return {"forecast_status": "NOT_FOUND", "message": "No such junction."}
        if metric not in FORECASTABLE:
            raise ValueError("metric must be one of {}".format(sorted(FORECASTABLE)))
        if bin_minutes not in ALLOWED_BIN_MINUTES:
            raise ValueError("bin_minutes must be one of {}".format(ALLOWED_BIN_MINUTES))
        horizon_bins = max(1, min(horizon_bins, MAX_HORIZON_BINS))

        info = FORECASTABLE[metric]
        as_of = _naive(as_of or datetime.now(timezone.utc))
        bin_width = timedelta(minutes=bin_minutes)

        envelope = {
            "intersection_id": inter.id,
            "intersection_name": inter.name,
            "metric": metric,
            "metric_label": info["label"],
            "unit": info["unit"],
            "as_of": as_of.isoformat(),
            "bin_minutes": bin_minutes,
            "horizon_bins": horizon_bins,
            "method_version": METHOD_VERSION,
            "stamp": SCENARIO_STAMP,
            "data_kind": "MODEL_FORECAST",
            "model": None,
            "backtest": None,
            "forecast_points": [],
        }

        rows = (
            db.query(TrafficMetric)
            .filter(
                TrafficMetric.intersection_id == intersection_id,
                TrafficMetric.timestamp >= as_of - timedelta(days=history_days),
                TrafficMetric.timestamp <= as_of,
            )
            .order_by(TrafficMetric.timestamp.asc())
            .all()
        )
        samples = [
            (r.timestamp, float(getattr(r, metric)))
            for r in rows
            if getattr(r, metric) is not None
            and (r.data_quality or "").upper() not in EXCLUDED_QUALITY
        ]

        if not samples:
            return {
                **envelope,
                "forecast_status": NOT_COMPUTABLE,
                "refusal_reason": "NO_STORED_VALUES_FOR_METRIC",
                "message": (
                    "No {} value has been stored for this junction. There is no "
                    "series to model; connect a source that measures it. Waiting "
                    "will not help.".format(info["label"].lower())
                ),
                "history": {"samples": 0},
            }

        # --- bin, excluding the in-progress bin -------------------------------
        epoch = datetime(1970, 1, 1)
        current_bin = int((as_of - epoch) / bin_width)
        bins: Dict[int, List[float]] = {}
        for timestamp, value in samples:
            index = int((timestamp - epoch) / bin_width)
            if index >= current_bin:
                continue  # partial bin: its mean would be biased by what has not arrived
            bins.setdefault(index, []).append(value)

        history = {
            "samples": len(samples),
            "bins_filled": len(bins),
            "bin_minutes": bin_minutes,
            "in_progress_bin_excluded": True,
        }

        if not bins:
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": "NO_COMPLETE_BIN",
                "message": "Every stored sample falls in the bin still in progress; no complete bin exists to model.",
                "history": history,
            }

        latest = max(bins)
        run = [latest]
        while run[-1] - 1 in bins and len(run) < MAX_TRAINING_BINS:
            run.append(run[-1] - 1)
        run.reverse()
        series = [mean(bins[i]) for i in run]
        span = latest - min(bins) + 1
        gaps = span - len(bins)

        required = MIN_TRAINING_BINS + BACKTEST_ORIGINS + horizon_bins - 1
        # The last observed bins travel with every response past this point, so
        # the console can draw what was measured beside what is forecast - and
        # keep the two visibly distinct.
        tail = run[-RECENT_BINS_RETURNED:]
        history["recent_observed_bins"] = [
            {
                "bin_start": (epoch + index * bin_width).isoformat(),
                "value": round(mean(bins[index]), 3),
                "samples": len(bins[index]),
                "kind": "MEASURED",
            }
            for index in tail
        ]
        history.update({
            "gap_free_run_bins": len(run),
            "gap_free_run_start": (epoch + run[0] * bin_width).isoformat(),
            "latest_complete_bin": (epoch + latest * bin_width).isoformat(),
            "missing_bins_in_history": gaps,
            "bins_required": required,
        })

        staleness = current_bin - 1 - latest
        if staleness > MAX_ORIGIN_STALENESS_BINS:
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": "LATEST_DATA_TOO_OLD",
                "message": (
                    "The latest complete bin is {} bins ({} min) behind now; at most {} "
                    "are allowed. A forecast from a series that stopped reporting would "
                    "predict a period that has already happened.".format(
                        staleness, staleness * bin_minutes, MAX_ORIGIN_STALENESS_BINS
                    )
                ),
                "history": history,
            }

        if len(run) < required:
            reason = "INSUFFICIENT_HISTORY" if len(bins) < required else "GAPS_BREAK_HISTORY"
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": reason,
                "message": (
                    "Training and backtesting need {} consecutive {}-minute bins; the "
                    "gap-free run ending at the latest bin has {}.{}".format(
                        required, bin_minutes, len(run),
                        " {} bins are missing across the history, and gaps are never "
                        "interpolated.".format(gaps) if reason == "GAPS_BREAK_HISTORY" else "",
                    )
                ),
                "history": history,
            }

        # --- rolling-origin backtest over every candidate --------------------
        origins = list(range(len(series) - BACKTEST_ORIGINS - horizon_bins + 1,
                             len(series) - horizon_bins + 1))
        persistence_errors: List[float] = []
        for origin in origins:
            actual = series[origin:origin + horizon_bins]
            persistence_errors.extend(abs(a - series[origin - 1]) for a in actual)
        persistence_mae = mean(persistence_errors)

        candidates = []
        for p, d in CANDIDATE_ORDERS:
            errors, inside, total, fits = [], 0, 0, 0
            for origin in origins:
                model = ArModel(p, d)
                if not model.fit(series[:origin]):
                    continue
                fits += 1
                predicted = model.forecast(series[:origin], horizon_bins)
                widths = model.interval_half_widths(horizon_bins)
                for step, actual in enumerate(series[origin:origin + horizon_bins]):
                    errors.append(abs(actual - predicted[step]))
                    total += 1
                    if abs(actual - predicted[step]) <= widths[step]:
                        inside += 1
            if fits < len(origins):
                candidates.append({
                    "order": "ARIMA({},{},0)".format(p, d),
                    "status": "COULD_NOT_BE_FITTED",
                    "detail": "Singular or under-determined at {} of {} origins.".format(
                        len(origins) - fits, len(origins)
                    ),
                })
                continue
            candidates.append({
                "order": "ARIMA({},{},0)".format(p, d),
                "p": p, "d": d,
                "status": "EVALUATED",
                "mae": round(mean(errors), 4),
                "rmse": round(math.sqrt(mean([e * e for e in errors])), 4),
                "interval_coverage_95": round(inside / total, 3) if total else None,
            })

        evaluated = [c for c in candidates if c["status"] == "EVALUATED"]
        backtest = {
            "method": "Rolling-origin: refit at each origin on data before it only, no look-ahead",
            "origins": len(origins),
            "horizon_bins": horizon_bins,
            "forecast_errors_per_model": len(origins) * horizon_bins,
            "persistence_mae": round(persistence_mae, 4),
            "persistence_definition": "Every future bin equals the last observed bin",
            "minimum_skill_required": MIN_SKILL_OVER_PERSISTENCE,
            "candidates": candidates,
        }

        if not evaluated:
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": "NO_MODEL_COULD_BE_FITTED",
                "message": "No candidate order could be fitted at every backtest origin.",
                "history": history,
                "backtest": backtest,
            }

        best = min(evaluated, key=lambda c: c["mae"])
        backtest["selected_order"] = best["order"]
        backtest["selected_mae"] = best["mae"]
        backtest["selected_rmse"] = best["rmse"]
        backtest["selected_interval_coverage_95"] = best["interval_coverage_95"]

        if persistence_mae <= 0:
            backtest["skill_vs_persistence"] = None
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": "SERIES_UNCHANGED_IN_BACKTEST",
                "message": (
                    "The series did not change across the backtest period, so repeating "
                    "the last value was exact and no model can demonstrate skill over it."
                ),
                "history": history,
                "backtest": backtest,
            }

        skill = 1.0 - best["mae"] / persistence_mae
        backtest["skill_vs_persistence"] = round(skill, 4)

        final = ArModel(best["p"], best["d"])
        final.fit(series)

        if skill < MIN_SKILL_OVER_PERSISTENCE:
            return {
                **envelope,
                "forecast_status": REFUSED,
                "refusal_reason": "NO_SKILL_OVER_PERSISTENCE",
                "message": (
                    "The best model ({}) was fitted and backtested on this junction's "
                    "own history. Its error was {:.1%} lower than simply repeating the "
                    "last value; at least {:.0%} is required. No forecast is offered "
                    "from a model that has not demonstrated it is better than that."
                    .format(best["order"], skill, MIN_SKILL_OVER_PERSISTENCE)
                ),
                "history": history,
                "model": final.describe(),
                "backtest": backtest,
            }

        # --- forecast ------------------------------------------------------
        predicted = final.forecast(series, horizon_bins)
        widths = final.interval_half_widths(horizon_bins)
        lower_bound, upper_bound = info["bounds"]
        points = []
        for step, (value, width) in enumerate(zip(predicted, widths), start=1):
            low, high = value - width, value + width
            clipped = False
            if lower_bound is not None:
                if value < lower_bound or low < lower_bound:
                    clipped = True
                value, low, high = max(value, lower_bound), max(low, lower_bound), max(high, lower_bound)
            if upper_bound is not None:
                if value > upper_bound or high > upper_bound:
                    clipped = True
                value, low, high = min(value, upper_bound), min(low, upper_bound), min(high, upper_bound)
            points.append({
                "step": step,
                "bin_start": (epoch + (latest + step) * bin_width).isoformat(),
                "value": round(value, 3),
                "lower_95": round(low, 3),
                "upper_95": round(high, 3),
                "clipped_to_physical_bounds": clipped,
                "kind": "MODEL_FORECAST",
            })

        return {
            **envelope,
            "forecast_status": FORECAST_AVAILABLE,
            "refusal_reason": None,
            "message": (
                "{} forecast for the next {} x {}-minute bins. Model output from this "
                "junction's stored history - not an observation.".format(
                    best["order"], horizon_bins, bin_minutes
                )
            ),
            "history": history,
            "model": final.describe(),
            "backtest": backtest,
            "forecast_points": points,
            "caveats": [
                "Each value is the forecast mean over the {}-minute bin starting at "
                "bin_start.".format(bin_minutes),
                "Intervals assume the fitted residuals are roughly normal; the measured "
                "backtest coverage shows whether that held on this junction's data.",
                "The model knows only this junction's own history. It cannot anticipate "
                "an incident, an event or a timing-plan change.",
            ],
        }
