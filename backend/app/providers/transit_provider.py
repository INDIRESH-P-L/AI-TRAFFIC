"""TRAFFICINTEL AI - GTFS-Realtime Transit Provider

Fetches an agency's GTFS-Realtime VehiclePositions and TripUpdates feeds over
HTTP. Every fetch is recorded with the provider health monitor, so a feed that
has gone quiet shows as DEGRADED on the provider health page rather than as a
network with no buses.

There is deliberately no demo mode. A feed that invented buses would put
fabricated vehicles - and fabricated lateness - into a decision that changes
signal timing. To see transit signal priority work, point these settings at a
real agency feed (many publish openly) or push real feed bytes to
POST /transit/tsp/evaluate-feed from an on-board or depot gateway.
"""

from __future__ import annotations

from typing import Optional, Tuple

import httpx

from app.core.config import settings
from app.health.monitor import provider_monitor
from app.providers.base import TransitProvider


class GtfsRealtimeProvider(TransitProvider):
    def __init__(self, vehicle_positions_url: Optional[str] = None,
                 trip_updates_url: Optional[str] = None):
        self.vehicle_positions_url = (
            vehicle_positions_url if vehicle_positions_url is not None
            else settings.GTFS_RT_VEHICLE_POSITIONS_URL
        )
        self.trip_updates_url = (
            trip_updates_url if trip_updates_url is not None
            else settings.GTFS_RT_TRIP_UPDATES_URL
        )

    @property
    def configured(self) -> bool:
        return bool(self.vehicle_positions_url)

    def _fetch(self, url: str, label: str) -> Tuple[bool, str, Optional[bytes]]:
        if not url:
            return False, "{} feed URL is not configured.".format(label), None
        headers = {}
        if settings.GTFS_RT_API_KEY_HEADER and settings.GTFS_RT_API_KEY:
            headers[settings.GTFS_RT_API_KEY_HEADER] = settings.GTFS_RT_API_KEY
        key = "transit:gtfs-rt:{}".format(label.lower().replace(" ", "-"))
        with provider_monitor.observe(key, "TRANSIT", "GTFS-RT {}".format(label)) as observation:
            try:
                response = httpx.get(url, headers=headers, timeout=settings.GTFS_RT_TIMEOUT_SEC)
            except httpx.HTTPError as exc:
                observation.failed(str(exc))
                return False, "Could not fetch {} feed: {}".format(label, exc), None
            if response.status_code != 200:
                observation.failed("HTTP {}".format(response.status_code))
                return False, "{} feed returned HTTP {}.".format(label, response.status_code), None
            return True, "Fetched {} bytes.".format(len(response.content)), response.content

    def fetch_vehicle_positions(self) -> Tuple[bool, str, Optional[bytes]]:
        return self._fetch(self.vehicle_positions_url, "Vehicle Positions")

    def fetch_trip_updates(self) -> Tuple[bool, str, Optional[bytes]]:
        return self._fetch(self.trip_updates_url, "Trip Updates")
