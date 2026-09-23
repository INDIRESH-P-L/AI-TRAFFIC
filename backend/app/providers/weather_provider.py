"""TRAFFICINTEL AI - Meteorological Weather Provider

Integrates with real GIS meteorological services (Open-Meteo).
Never generates synthetic or random weather values.
If service is unavailable or coordinates are unconfigured, explicitly returns WEATHER_DATA_UNAVAILABLE.
"""

import time
from typing import Dict, Any, Optional, Tuple

import httpx
from datetime import datetime, timezone
from app.providers.base import WeatherProvider
from app.core.config import settings
from app.health.circuit import CircuitOpenError
from app.health.monitor import provider_monitor


class RealGISWeatherAdapter(WeatherProvider):
    """Adapter fetching real meteorological observations for intersection GIS coordinates."""

    def __init__(self, base_url: str = settings.OPEN_METEO_API_URL, timeout: float = 3.5):
        self.base_url = base_url
        self.timeout = timeout

    #: One health key for the whole provider: it is a single upstream service.
    HEALTH_KEY = "weather:open-meteo"

    def fetch_weather(self, latitude: float, longitude: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if not latitude or not longitude:
            return False, "Invalid GIS coordinates", None

        # A tripped breaker refuses the call outright rather than making the
        # console wait for another timeout. The refusal is stated, never
        # papered over with a cached value presented as current.
        provider = provider_monitor.register(
            self.HEALTH_KEY, "WEATHER", "Open-Meteo GIS"
        )
        try:
            provider.circuit.raise_if_open()
        except CircuitOpenError as exc:
            return False, (
                "Weather provider circuit is open after repeated failures; "
                "retrying in {:.0f}s. Last error: {}".format(
                    exc.retry_after_sec, provider.circuit.last_error
                )
            ), None

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,precipitation,wind_speed_10m,visibility,weather_code",
            "timezone": "UTC"
        }

        started = time.monotonic()

        def _record(success: bool, error: Optional[str] = None) -> None:
            provider_monitor.record(
                key=self.HEALTH_KEY,
                success=success,
                latency_ms=(time.monotonic() - started) * 1000.0 if success else None,
                error=error,
                kind="WEATHER",
                label="Open-Meteo GIS",
            )

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self.base_url, params=params)
                if resp.status_code != 200:
                    _record(False, f"HTTP {resp.status_code}")
                    return False, f"Weather provider HTTP {resp.status_code}", None

                data = resp.json()
                current = data.get("current", {})

                precip = current.get("precipitation")
                road_condition = "DRY"
                if precip is not None and precip > 0.0:
                    road_condition = "WET" if precip < 5.0 else "FLOOD_RISK"

                _record(True)
                return True, "Success", {
                    "latitude": latitude,
                    "longitude": longitude,
                    "temperature_c": current.get("temperature_2m"),
                    "precipitation_mm": precip,
                    "wind_speed_kph": current.get("wind_speed_10m"),
                    "visibility_meters": current.get("visibility"),
                    "weather_code": current.get("weather_code"),
                    "road_condition": road_condition,
                    "status": "CONNECTED",
                    "source": "Open-Meteo Historical & Real-Time GIS",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
        except httpx.TimeoutException:
            _record(False, "timeout after {}s".format(self.timeout))
            return False, "Weather provider timeout", None
        except Exception as e:
            _record(False, str(e))
            return False, f"Weather provider error: {str(e)}", None
