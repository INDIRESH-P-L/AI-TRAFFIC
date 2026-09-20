"""TRAFFICINTEL AI - Provider Abstractions

Abstract Base Classes for external hardware, GIS, sensor, and weather integrations.
No fake implementations. If not connected, return truthful UNAVAILABLE / DISCONNECTED state.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Tuple
from datetime import datetime


class SignalControllerProvider(ABC):
    """Abstract interface for physical traffic light controllers."""

    @abstractmethod
    def connect(self) -> Tuple[bool, str]:
        """Attempt connection to controller hardware."""
        pass

    @abstractmethod
    def disconnect(self) -> bool:
        """Close connection to controller."""
        pass

    @abstractmethod
    def health_check(self) -> Dict[str, Any]:
        """Query physical hardware health & communication latency."""
        pass

    @abstractmethod
    def get_controller_status(self) -> Dict[str, Any]:
        """Get controller running mode, active plan, cycle state."""
        pass

    @abstractmethod
    def get_current_phase(self) -> Optional[int]:
        """Read the real currently illuminated phase from controller registers."""
        pass

    @abstractmethod
    def send_command(self, phase_number: int, duration_sec: int) -> Tuple[bool, str, Dict[str, Any]]:
        """Send safety-verified phase command to controller registers."""
        pass

    @abstractmethod
    def get_faults(self) -> list:
        """Query controller MMU/CMU conflict monitor unit fault log."""
        pass


class CameraProvider(ABC):
    """Abstract interface for video cameras (RTSP / ONVIF / Edge Ingest)."""

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Verify network socket or RTSP stream connectivity."""
        pass

    @abstractmethod
    def get_stream_info(self) -> Dict[str, Any]:
        """Fetch stream resolution, codec, and measured FPS."""
        pass


class TrafficSensorProvider(ABC):
    """Abstract interface for roadside traffic sensors (Radar, Loops, Microwave)."""

    @abstractmethod
    def test_connection(self) -> Tuple[bool, str]:
        """Verify sensor telemetry endpoint."""
        pass

    @abstractmethod
    def ingest_telemetry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Process raw telemetry observation with quality validation."""
        pass


class WeatherProvider(ABC):
    """Abstract interface for weather meteorological providers."""

    @abstractmethod
    def fetch_weather(self, latitude: float, longitude: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """Fetch real weather observations from GIS/meteorological service."""
        pass
