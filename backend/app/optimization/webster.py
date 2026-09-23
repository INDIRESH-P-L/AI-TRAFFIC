"""TRAFFICINTEL AI - Explainable Signal Timing Optimiser

Implements recognised, auditable traffic engineering methods rather than an
opaque model:

  * **Webster's optimum cycle length** (Webster 1958, Road Research Technical
    Paper No. 39):   C0 = (1.5 L + 5) / (1 - Y)
    where L is total lost time per cycle and Y is the sum of critical flow
    ratios.

  * **Green split allocation** proportional to critical flow ratios, bounded by
    each phase's configured minimum and maximum green.

  * **HCM v/c ratio** per critical movement, and **Webster's delay** per
    approach:
        d = C(1-g/C)^2 / (2(1-(g/C)x))  +  x^2 / (2q(1-x))
    the first term being uniform delay and the second random/overflow delay.

Two properties matter more than the formulas:

1. **Every calculation step is returned.** The `trace` in the result lists each
   intermediate value with its symbol and where it came from, so an engineer
   can check the arithmetic rather than trust it.

2. **It refuses rather than guesses.** Webster's method is undefined when
   Y >= 1 (demand at or above capacity) and unreliable on thin data. Both cases
   return a refusal with the reason, not a number.

Inputs are either real measured detector volumes or volumes an operator typed
in — never generated. Which one was used is stamped on the result.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("trafficintel.optimizer")

METHOD_VERSION = "webster_hcm_v1"

# Saturation flow rate per lane, vehicles per hour of green. HCM 6th edition
# base value for through movements under ideal conditions; declared here as a
# parameter rather than buried, because every capacity figure below scales
# directly with it.
DEFAULT_SATURATION_FLOW_VPHPL = 1900.0

# Startup lost time + clearance lost time per phase, seconds. HCM default.
DEFAULT_LOST_TIME_PER_PHASE_SEC = 4.0

MIN_CYCLE_SEC = 30
MAX_CYCLE_SEC = 180

#: Below this many measured samples per movement, a timing recommendation is
#: refused: a cycle length derived from two counts is not engineering.
MIN_SAMPLES_PER_MOVEMENT = 5


@dataclass
class MovementDemand:
    """Demand on one critical movement (one phase)."""

    phase_number: int
    name: str
    volume_vph: float
    lanes: int = 1
    saturation_flow_vphpl: float = DEFAULT_SATURATION_FLOW_VPHPL
    min_green_sec: int = 7
    max_green_sec: int = 65
    #: How this volume was obtained.
    source: str = "OPERATOR_ENTERED"
    sample_size: int = 0

    @property
    def saturation_flow_vph(self) -> float:
        return self.saturation_flow_vphpl * max(1, self.lanes)

    @property
    def flow_ratio(self) -> float:
        """y = q / s, the movement's flow ratio."""
        return self.volume_vph / self.saturation_flow_vph


@dataclass
class TraceStep:
    symbol: str
    label: str
    value: Any
    formula: str
    source: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "label": self.label,
            "value": self.value,
            "formula": self.formula,
            "source": self.source,
        }


@dataclass
class OptimizationResult:
    status: str                       # COMPUTED | REFUSED
    reason: Optional[str] = None
    cycle_length_sec: Optional[int] = None
    splits: List[Dict[str, Any]] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    expected_delay: Optional[Dict[str, Any]] = None
    inputs: List[Dict[str, Any]] = field(default_factory=list)
    method_version: str = METHOD_VERSION

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "reason": self.reason,
            "method_version": self.method_version,
            "cycle_length_sec": self.cycle_length_sec,
            "splits": self.splits,
            "expected_delay": self.expected_delay,
            "inputs": self.inputs,
            "trace": self.trace,
        }


class WebsterOptimizer:
    """Webster cycle length and split allocation with a full calculation trace."""

    @classmethod
    def optimize(
        cls,
        movements: List[MovementDemand],
        lost_time_per_phase_sec: float = DEFAULT_LOST_TIME_PER_PHASE_SEC,
        current_cycle_sec: Optional[int] = None,
    ) -> OptimizationResult:
        trace: List[TraceStep] = []

        inputs = [
            {
                "phase": m.phase_number,
                "name": m.name,
                "volume_vph": m.volume_vph,
                "lanes": m.lanes,
                "saturation_flow_vph": round(m.saturation_flow_vph, 1),
                "flow_ratio_y": round(m.flow_ratio, 4),
                "source": m.source,
                "sample_size": m.sample_size,
                "min_green_sec": m.min_green_sec,
                "max_green_sec": m.max_green_sec,
            }
            for m in movements
        ]

        if not movements:
            return OptimizationResult(
                status="REFUSED",
                reason="NO_MOVEMENT_DEMAND_SUPPLIED",
                inputs=inputs,
                trace=[],
            )

        # --- refuse on thin measured data ---------------------------------
        # A movement with no stated provenance is not treated as measured: the
        # sample-size guard exists to stop a cycle length being derived from
        # three detector readings, and an unlabelled input gets the benefit of
        # no doubt.
        measured = [
            m for m in movements if (m.source or "").startswith("MEASURED")
        ]
        thin = [m for m in measured if m.sample_size < MIN_SAMPLES_PER_MOVEMENT]
        if thin:
            return OptimizationResult(
                status="REFUSED",
                reason="INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST",
                inputs=inputs,
                trace=[TraceStep(
                    "n", "Samples per movement",
                    {m.name: m.sample_size for m in thin},
                    "n >= {}".format(MIN_SAMPLES_PER_MOVEMENT),
                    "measured detector samples",
                ).as_dict()],
            )

        # --- Y: sum of critical flow ratios -------------------------------
        y_values = {m.name: round(m.flow_ratio, 4) for m in movements}
        total_y = sum(m.flow_ratio for m in movements)

        trace.append(TraceStep(
            "y_i", "Flow ratio per critical movement",
            y_values, "y = q / s", "measured or operator-entered volume / saturation flow",
        ))
        trace.append(TraceStep(
            "Y", "Sum of critical flow ratios", round(total_y, 4),
            "Y = sum(y_i)", "derived",
        ))

        # --- L: total lost time -------------------------------------------
        lost_time = lost_time_per_phase_sec * len(movements)
        trace.append(TraceStep(
            "L", "Total lost time per cycle", round(lost_time, 1),
            "L = {} s/phase x {} phases".format(lost_time_per_phase_sec, len(movements)),
            "HCM default startup + clearance lost time",
        ))

        # --- Webster is undefined at or above capacity ---------------------
        if total_y >= 1.0:
            return OptimizationResult(
                status="REFUSED",
                reason="DEMAND_AT_OR_ABOVE_CAPACITY",
                inputs=inputs,
                trace=[t.as_dict() for t in trace] + [TraceStep(
                    "C0", "Optimum cycle length", None,
                    "C0 = (1.5L + 5) / (1 - Y) is undefined for Y >= 1",
                    (
                        "Critical flow ratios sum to {:.3f}. The intersection is at or "
                        "over capacity: no cycle length clears this demand, and any "
                        "number produced here would be meaningless. Geometry or demand "
                        "management is required, not retiming.".format(total_y)
                    ),
                ).as_dict()],
            )

        # --- C0: Webster's optimum cycle length ---------------------------
        c0 = (1.5 * lost_time + 5.0) / (1.0 - total_y)
        cycle = int(max(MIN_CYCLE_SEC, min(MAX_CYCLE_SEC, round(c0 / 5.0) * 5)))

        trace.append(TraceStep(
            "C0", "Webster optimum cycle length", round(c0, 1),
            "C0 = (1.5L + 5) / (1 - Y) = (1.5 x {:.1f} + 5) / (1 - {:.4f})".format(
                lost_time, total_y
            ),
            "Webster 1958, RRL Technical Paper No. 39",
        ))
        trace.append(TraceStep(
            "C", "Practical cycle length", cycle,
            "C = round(C0 to nearest 5s), clamped to [{}, {}]".format(MIN_CYCLE_SEC, MAX_CYCLE_SEC),
            "practical rounding",
        ))

        # --- Green splits proportional to flow ratio ----------------------
        effective_green_total = cycle - lost_time
        splits: List[Dict[str, Any]] = []
        raw_greens: Dict[int, float] = {}

        for movement in movements:
            share = (movement.flow_ratio / total_y) if total_y > 0 else 1.0 / len(movements)
            raw_greens[movement.phase_number] = effective_green_total * share

        # Clamp to configured envelopes, then redistribute the remainder so
        # the splits still sum to the available green.
        clamped: Dict[int, float] = {}
        for movement in movements:
            raw = raw_greens[movement.phase_number]
            clamped[movement.phase_number] = min(
                max(raw, movement.min_green_sec), movement.max_green_sec
            )

        total_clamped = sum(clamped.values())
        if total_clamped > 0 and abs(total_clamped - effective_green_total) > 0.5:
            scale = effective_green_total / total_clamped
            for movement in movements:
                scaled = clamped[movement.phase_number] * scale
                clamped[movement.phase_number] = min(
                    max(scaled, movement.min_green_sec), movement.max_green_sec
                )

        trace.append(TraceStep(
            "g_i", "Effective green per phase", {
                m.name: round(clamped[m.phase_number], 1) for m in movements
            },
            "g_i = (C - L) x y_i / Y, clamped to [min_green, max_green]",
            "Webster split allocation, bounded by controller configuration",
        ))

        # --- v/c and Webster delay per movement ---------------------------
        delays: Dict[str, float] = {}
        for movement in movements:
            green = clamped[movement.phase_number]
            capacity = movement.saturation_flow_vph * (green / cycle)
            vc = movement.volume_vph / capacity if capacity > 0 else float("inf")

            delay = cls._webster_delay(
                cycle_sec=cycle,
                green_sec=green,
                volume_vph=movement.volume_vph,
                capacity_vph=capacity,
            )
            if delay is not None:
                delays[movement.name] = delay

            splits.append({
                "phase": movement.phase_number,
                "name": movement.name,
                "effective_green_sec": round(green, 1),
                "green_ratio": round(green / cycle, 3),
                "capacity_vph": round(capacity, 1),
                "volume_vph": movement.volume_vph,
                "v_over_c": round(vc, 3) if math.isfinite(vc) else None,
                "v_over_c_status": (
                    "OVER_CAPACITY" if not math.isfinite(vc) or vc >= 1.0
                    else "APPROACHING_CAPACITY" if vc >= 0.85
                    else "WITHIN_CAPACITY"
                ),
                "estimated_delay_sec_per_veh": round(delay, 1) if delay is not None else None,
                "volume_source": movement.source,
            })

        trace.append(TraceStep(
            "x_i", "Degree of saturation (v/c) per movement",
            {s["name"]: s["v_over_c"] for s in splits},
            "x = q / (s x g/C)", "HCM 6th ed. capacity relationship",
        ))

        expected_delay = None
        if delays:
            total_volume = sum(m.volume_vph for m in movements)
            weighted = (
                sum(delays.get(m.name, 0.0) * m.volume_vph for m in movements) / total_volume
                if total_volume > 0 else None
            )
            trace.append(TraceStep(
                "d", "Webster delay per movement",
                {k: round(v, 1) for k, v in delays.items()},
                "d = C(1-g/C)^2 / (2(1-(g/C)x)) + x^2 / (2q(1-x))",
                "Webster 1958 uniform + random delay",
            ))
            expected_delay = {
                "volume_weighted_delay_sec_per_veh": (
                    round(weighted, 1) if weighted is not None else None
                ),
                "per_movement": {k: round(v, 1) for k, v in delays.items()},
                "uncertainty": (
                    "Webster's delay assumes random arrivals and steady demand over the "
                    "cycle. Actual delay depends on platoon arrival patterns this "
                    "calculation does not model, so treat it as an estimate with an "
                    "expected error of tens of percent, not a prediction."
                ),
                "basis": "WEBSTER_UNIFORM_PLUS_RANDOM_DELAY",
            }

        return OptimizationResult(
            status="COMPUTED",
            cycle_length_sec=cycle,
            splits=splits,
            trace=[t.as_dict() for t in trace],
            expected_delay=expected_delay,
            inputs=inputs,
        )

    @staticmethod
    def _webster_delay(
        cycle_sec: float, green_sec: float, volume_vph: float, capacity_vph: float
    ) -> Optional[float]:
        """Webster's average delay per vehicle, seconds.

        Returns None where the formula is undefined (x >= 1, zero demand):
        an over-saturated movement has unbounded steady-state delay, and
        printing a large finite number for it would be a fiction.
        """
        if volume_vph <= 0 or capacity_vph <= 0:
            return None

        x = volume_vph / capacity_vph
        if x >= 1.0:
            return None

        green_ratio = green_sec / cycle_sec
        denominator = 2.0 * (1.0 - green_ratio * x)
        if denominator <= 0:
            return None

        uniform = cycle_sec * (1.0 - green_ratio) ** 2 / denominator

        q_per_sec = volume_vph / 3600.0
        random_term_denominator = 2.0 * q_per_sec * (1.0 - x)
        if random_term_denominator <= 0:
            return None
        random = (x ** 2) / random_term_denominator

        return uniform + random
