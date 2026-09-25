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

    def write_timing_plan(self, pattern_number: int, cycle_sec: int, offset_sec: int,
                          splits: Dict[int, int], coord_phase: int) -> Tuple[bool, str, Dict[str, Any]]:
        """Write and activate a coordination plan. Refused unless implemented.

        Deliberately not abstract: most adapters have no timing-plan channel,
        and the honest default is a refusal the caller can record.
        """
        return False, "This adapter has no timing-plan channel.", {
            "rejected_reason": "NO_COMMAND_CHANNEL_FOR_TIMING_PLAN"
        }


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


class TransitProvider(ABC):
    """Abstract interface for real-time transit vehicle feeds (GTFS-Realtime).

    Implementations return the bytes an agency actually served - never a
    fabricated vehicle. With no feed configured, `configured` is False and the
    platform reports TRANSIT_FEED_NOT_CONFIGURED rather than an empty network.
    """

    @property
    @abstractmethod
    def configured(self) -> bool:
        """Whether a feed endpoint has been configured at all."""

    @abstractmethod
    def fetch_vehicle_positions(self) -> Tuple[bool, str, Optional[bytes]]:
        """Fetch the VehiclePositions feed."""

    @abstractmethod
    def fetch_trip_updates(self) -> Tuple[bool, str, Optional[bytes]]:
        """Fetch the TripUpdates feed (schedule adherence)."""
