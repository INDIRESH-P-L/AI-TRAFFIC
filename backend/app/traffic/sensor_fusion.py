"""TRAFFICINTEL AI - Sensor Fusion Engine

Fuses multi-sensor observations (Camera, Radar, Inductive Loop) using weighted confidence.
Retains fusion provenance and individual source measurements.
"""

from typing import List, Dict, Any, Optional
from datetime import datetime, timezone


class SensorFusionEngine:
    """Fuses multi-modal traffic observations."""

    @classmethod
    def fuse_approach_telemetry(
        cls,
        observations: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fuses multiple sensor readings for an approach.

        Each reading: {'source': str, 'type': str, 'vehicle_count': int, 'confidence': float, 'speed_kph': Optional[float]}
        """
        if not observations:
            return {
                "fused_count": None,
                "fused_speed_kph": None,
                "confidence": 0.0,
                "status": "NO_OBSERVATIONS",
                "sources_fused": []
            }

        total_weight = 0.0
        weighted_count = 0.0
        weighted_speed = 0.0
        speed_weight = 0.0
        sources_used = []

        for obs in observations:
            conf = obs.get("confidence", 0.5)
            count = obs.get("vehicle_count", 0)
            speed = obs.get("speed_kph")
            src = obs.get("source", "unknown")

            sources_used.append({
                "source": src,
                "type": obs.get("type"),
                "reported_count": count,
                "confidence": conf
            })

            weighted_count += count * conf
            total_weight += conf

            if speed is not None:
                weighted_speed += speed * conf
                speed_weight += conf

        fused_count = round(weighted_count / total_weight) if total_weight > 0 else 0
        fused_speed = round(weighted_speed / speed_weight, 1) if speed_weight > 0 else None
        avg_confidence = round(total_weight / len(observations), 2) if observations else 0.0

        return {
            "fused_count": fused_count,
            "fused_speed_kph": fused_speed,
            "confidence": avg_confidence,
            "status": "FUSED",
            "sources_fused": sources_used,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
