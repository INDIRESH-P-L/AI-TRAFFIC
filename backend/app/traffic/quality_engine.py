"""TRAFFICINTEL AI - Data Quality Engine

Evaluates telemetry stream health and prevents stale data from masquerading as live state.
Streams transition through deterministic states:
FRESH -> AGING -> STALE -> DISCONNECTED / INVALID.
"""

from datetime import datetime, timezone
from typing import Optional, Tuple
from app.core.config import settings


class DataQualityEngine:
    """Evaluates telemetry stream freshness and integrity."""

    @classmethod
    def evaluate_freshness(cls, last_timestamp: Optional[datetime]) -> Tuple[str, float]:
        """Returns quality state and age in seconds."""
        if last_timestamp is None:
            return "DISCONNECTED", -1.0

        now = datetime.now(timezone.utc)
        if last_timestamp.tzinfo is None:
            # Handle naive datetime as UTC
            last_timestamp = last_timestamp.replace(tzinfo=timezone.utc)

        age_sec = (now - last_timestamp).total_seconds()

        if age_sec < 0:
            # Future timestamp anomaly
            return "INVALID", age_sec
        elif age_sec <= settings.DATA_FRESH_THRESHOLD_SEC:
            return "FRESH", age_sec
        elif age_sec <= settings.DATA_AGING_THRESHOLD_SEC:
            return "AGING", age_sec
        elif age_sec <= settings.DATA_STALE_THRESHOLD_SEC:
            return "STALE", age_sec
        else:
            return "DISCONNECTED", age_sec

    @classmethod
    def fresh_threshold_sec(cls) -> int:
        return settings.DATA_FRESH_THRESHOLD_SEC

    @classmethod
    def aging_threshold_sec(cls) -> int:
        return settings.DATA_AGING_THRESHOLD_SEC

    @classmethod
    def stale_threshold_sec(cls) -> int:
        return settings.DATA_STALE_THRESHOLD_SEC

    @classmethod
    def validate_measurement_bounds(cls, measurement_name: str, value: Optional[float]) -> Tuple[bool, Optional[str]]:
        """Physical sanity checks for transportation metrics."""
        if value is None:
            return True, None

        if measurement_name == "occupancy_pct":
            if not (0.0 <= value <= 100.0):
                return False, f"Occupancy {value}% out of physical bounds (0-100%)"
        elif measurement_name == "speed_kph":
            if not (0.0 <= value <= 250.0):
                return False, f"Speed {value} km/h out of physical bounds (0-250 km/h)"
        elif measurement_name == "vehicle_count":
            if value < 0:
                return False, f"Negative vehicle count {value} impossible"

        return True, None
