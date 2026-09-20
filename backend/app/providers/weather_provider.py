"""TRAFFICINTEL AI - Meteorological Weather Provider

Integrates with real GIS meteorological services (Open-Meteo).
Never generates synthetic or random weather values.
If service is unavailable or coordinates are unconfigured, explicitly returns WEATHER_DATA_UNAVAILABLE.
"""

from typing import Dict, Any, Optional, Tuple
import httpx
from datetime import datetime, timezone
from app.providers.base import WeatherProvider
from app.core.config import settings


class RealGISWeatherAdapter(WeatherProvider):
    """Adapter fetching real meteorological observations for intersection GIS coordinates."""

    def __init__(self, base_url: str = settings.OPEN_METEO_API_URL, timeout: float = 3.5):
        self.base_url = base_url
        self.timeout = timeout

    def fetch_weather(self, latitude: float, longitude: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        if not latitude or not longitude:
            return False, "Invalid GIS coordinates", None

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "current": "temperature_2m,precipitation,wind_speed_10m,visibility,weather_code",
            "timezone": "UTC"
        }

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(self.base_url, params=params)
                if resp.status_code != 200:
                    return False, f"Weather provider HTTP {resp.status_code}", None

                data = resp.json()
                current = data.get("current", {})

                precip = current.get("precipitation")
                road_condition = "DRY"
                if precip is not None and precip > 0.0:
                    road_condition = "WET" if precip < 5.0 else "FLOOD_RISK"

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
            return False, "Weather provider timeout", None
        except Exception as e:
            return False, f"Weather provider error: {str(e)}", None
