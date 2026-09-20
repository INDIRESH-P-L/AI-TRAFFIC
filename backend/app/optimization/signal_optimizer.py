"""TRAFFICINTEL AI - Adaptive Signal Optimization Engine

Generates candidate signal timing adjustments based on actual measured queues,
traffic pressure, and arrival rates.
Every candidate MUST pass the Deterministic Safety Engine.
Stores complete reproducible decision snapshots.
"""

from typing import Dict, Any, Optional, Tuple, List
from datetime import datetime, timezone
from app.models.entities import SignalController, SignalPhase, AIDecision, utc_now
from app.safety.safety_engine import DeterministicSafetyEngine


class AdaptiveSignalOptimizer:
    """Computes traffic pressure-based signal adjustments.

    Strictly deterministic and explainable: outputs evidence alongside every recommendation.
    """

    MODEL_VERSION = "max_pressure_v2.1"

    @classmethod
    def evaluate_intersection(
        cls,
        controller: SignalController,
        queue_by_phase: Dict[int, int],
        active_phase: int,
        elapsed_in_phase_sec: float
    ) -> Tuple[str, Optional[int], Optional[int], Dict[str, Any]]:
        """Evaluates whether to extend the current phase or recommend a phase transition.

        Returns: (decision_status, target_phase, hold_duration, evidence_snapshot)
        """
        # If no queue observations exist, do NOT optimize or invent changes
        if not queue_by_phase:
            return (
                "NO_CHANGE",
                None,
                None,
                {
                    "reason": "Insufficient live queue telemetry to calculate pressure differential",
                    "model_version": cls.MODEL_VERSION,
                    "action": "MAINTAIN_CURRENT_CONTROLLER_PLAN"
                }
            )

        active_phase_queue = queue_by_phase.get(active_phase, 0)

        # Find phase with maximum waiting queue
        max_phase = active_phase
        max_queue = active_phase_queue
        for phase_num, q_len in queue_by_phase.items():
            if q_len > max_queue:
                max_queue = q_len
                max_phase = phase_num

        evidence = {
            "model_version": cls.MODEL_VERSION,
            "evaluated_at": utc_now().isoformat(),
            "active_phase": active_phase,
            "active_phase_elapsed_sec": elapsed_in_phase_sec,
            "measured_queues": queue_by_phase,
            "critical_phase": max_phase,
            "max_queue_observed": max_queue
        }

        # Pressure differential rule
        if max_phase != active_phase and max_queue >= (active_phase_queue + 4):
            # Significant competing pressure on competing phase
            evidence["reason"] = f"Competing Phase {max_phase} queue ({max_queue} veh) exceeds active Phase {active_phase} ({active_phase_queue} veh)"
            evidence["recommended_action"] = f"TRANSITION_TO_PHASE_{max_phase}"
            return "RECOMMEND_TRANSITION", max_phase, 15, evidence

        elif active_phase_queue > 2 and elapsed_in_phase_sec < 45:
            # High active queue, recommend extending active phase within safe limits
            extension_sec = min(10, int(active_phase_queue * 2))
            evidence["reason"] = f"Active Phase {active_phase} queue ({active_phase_queue} veh) warrants green extension"
            evidence["recommended_action"] = f"EXTEND_ACTIVE_PHASE_{extension_sec}S"
            return "EXTEND_PHASE", active_phase, extension_sec, evidence

        else:
            evidence["reason"] = "Queues are balanced; current timing plan is optimal"
            evidence["recommended_action"] = "MAINTAIN_PLAN"
            return "NO_CHANGE", None, None, evidence
