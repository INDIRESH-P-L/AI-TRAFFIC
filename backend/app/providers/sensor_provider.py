"""TRAFFICINTEL AI - Traffic Sensor Provider

Ingestion and validation adapters for Radar, Inductive Loop, and Microwave detectors.
Strictly validates ranges; flags out-of-range or malformed telemetry as INVALID.
"""

from typing import Dict, Any, Tuple
from datetime import datetime, timezone
from app.providers.base import TrafficSensorProvider


class RoadsideSensorAdapter(TrafficSensorProvider):
    """Adapter for roadside sensor telemetry streams."""

    def __init__(self, sensor_id: str, sensor_type: str, endpoint: str = ""):
        self.sensor_id = sensor_id
        self.sensor_type = sensor_type
        self.endpoint = endpoint

    def test_connection(self) -> Tuple[bool, str]:
        if not self.endpoint:
            return False, "No telemetry endpoint configured"
        return True, "Telemetry endpoint configured"

    def ingest_telemetry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Ingests and validates raw telemetry data from sensor."""
        vehicle_count = payload.get("vehicle_count")
        occupancy_pct = payload.get("occupancy_pct")
        speed_kph = payload.get("avg_speed_kph")

        # Range validation
        is_valid = True
        reasons = []

        if vehicle_count is None or vehicle_count < 0:
            is_valid = False
            reasons.append("Invalid or missing vehicle count")

        if occupancy_pct is not None and not (0.0 <= occupancy_pct <= 100.0):
            is_valid = False
            reasons.append(f"Occupancy out of bounds (0-100%): {occupancy_pct}")

        if speed_kph is not None and not (0.0 <= speed_kph <= 250.0):
            is_valid = False
            reasons.append(f"Speed measurement physically improbable: {speed_kph} km/h")

        quality = "FRESH" if is_valid else "INVALID"

        return {
            "sensor_id": self.sensor_id,
            "sensor_type": self.sensor_type,
            "timestamp": payload.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "vehicle_count": vehicle_count if is_valid else 0,
            "occupancy_pct": occupancy_pct if is_valid else None,
            "avg_speed_kph": speed_kph if is_valid else None,
            "quality": quality,
            "validation_errors": reasons,
            "provenance": {
                "adapter": "RoadsideSensorAdapter",
                "endpoint": self.endpoint,
                "ingested_at": datetime.now(timezone.utc).isoformat()
            }
        }
