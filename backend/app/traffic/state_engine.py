"""TRAFFICINTEL AI - Traffic State & Provenance Engine

Computes fundamental traffic flow parameters (Volume, Flow Rate, Occupancy,
Queue Length, Traffic Pressure) exclusively from real observations.

Every derived value here rests on a modelling assumption, and every one of
those assumptions is declared as a named constant, recorded in the metric's
provenance, and omitted entirely when its input is missing. Three rules:

1. A derived value whose input was not observed is `None`, never a default.
   An unknown occupancy does not become 0.5 so that pressure can be printed.

2. Flow rate requires a known observation window. `vehicles x 60` silently
   assumes a one-minute sample; the caller must supply the real window, and
   without it `flow_rate_vph` stays null.

3. Freshness is measured from the newest contributing observation, never
   assumed. An aggregate built from ten-minute-old readings is STALE, however
   recently the aggregation itself ran.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from app.models.entities import TrafficObservation, TrafficMetric
from app.traffic.quality_engine import DataQualityEngine

# --- Declared modelling constants ------------------------------------------
# Average longitudinal space one queued passenger car occupies, including the
# gap to the vehicle ahead. HCM passenger-car spacing for a standing queue.
QUEUED_VEHICLE_SPACING_METERS = 6.0

# Queue discharge rate at the stop bar, used to convert a standing queue into an
# expected wait. Corresponds to a saturation flow of roughly 1800 veh/h/lane.
QUEUE_DISCHARGE_VEH_PER_SEC = 1.5

CALCULATION_METHOD = "OBSERVATION_WEIGHTED_AGGREGATION_V2"


class TrafficStateEngine:
    """Aggregates and derives traffic engineering metrics with full provenance."""

    @classmethod
    def aggregate_intersection_state(
        cls,
        intersection_id: str,
        observations: List[TrafficObservation],
        sample_window_sec: Optional[float] = None,
    ) -> TrafficMetric:
        """Aggregates lane/approach observations into an intersection-level state.

        Args:
            intersection_id: Intersection the observations belong to.
            observations: Real stored observations. An empty list yields an
                explicit NO_DATA metric with null values.
            sample_window_sec: Duration the vehicle counts were accumulated
                over. Required to extrapolate an hourly flow rate; when absent,
                `flow_rate_vph` is null and the provenance says why.
        """
        now = datetime.now(timezone.utc)

        if not observations:
            return TrafficMetric(
                intersection_id=intersection_id,
                timestamp=now,
                vehicle_count=None,
                flow_rate_vph=None,
                occupancy_pct=None,
                avg_speed_kph=None,
                queue_length_meters=None,
                avg_wait_time_sec=None,
                traffic_pressure=None,
                sample_window_sec=None,
                data_quality="NO_DATA",
                calculation_method="UNAVAILABLE_ZERO_OBSERVATIONS",
                provenance={
                    "observation_count": 0,
                    "status": "NO_LIVE_OBSERVATIONS_AVAILABLE",
                    "sources": []
                }
            )

        counted = [o for o in observations if o.vehicle_count is not None]
        total_vehicles = sum(o.vehicle_count for o in counted) if counted else None

        valid_speeds = [o.avg_speed_kph for o in observations if o.avg_speed_kph is not None]
        valid_occupancies = [o.occupancy_pct for o in observations if o.occupancy_pct is not None]

        mean_speed = sum(valid_speeds) / len(valid_speeds) if valid_speeds else None
        mean_occupancy = (
            sum(valid_occupancies) / len(valid_occupancies) if valid_occupancies else None
        )

        # --- Flow rate: only with a known accumulation window ---------------
        flow_rate: Optional[float] = None
        flow_rate_basis = "NOT_CALCULATED_SAMPLE_WINDOW_UNKNOWN"
        if total_vehicles is not None and sample_window_sec and sample_window_sec > 0:
            flow_rate = round(total_vehicles * (3600.0 / sample_window_sec), 1)
            flow_rate_basis = (
                "EXTRAPOLATED_FROM_{}S_OBSERVATION_WINDOW".format(int(sample_window_sec))
            )

        # --- Queue and wait: derived from counted vehicles ------------------
        queue_meters: Optional[float] = None
        wait_sec: Optional[float] = None
        if total_vehicles is not None:
            queue_meters = round(total_vehicles * QUEUED_VEHICLE_SPACING_METERS, 1)
            wait_sec = round(total_vehicles / QUEUE_DISCHARGE_VEH_PER_SEC, 1)

        # --- Pressure: requires both count and occupancy --------------------
        # Occupancy is the term that distinguishes a moving platoon from a
        # standing queue. Without it there is no pressure value to report.
        traffic_pressure: Optional[float] = None
        if total_vehicles is not None and mean_occupancy is not None:
            traffic_pressure = round(total_vehicles * (mean_occupancy / 100.0), 2)

        # --- Freshness: measured from the newest contributing observation ---
        timestamps = [o.timestamp for o in observations if o.timestamp is not None]
        newest = max(timestamps) if timestamps else None
        quality, age_sec = DataQualityEngine.evaluate_freshness(newest)

        sources_used = sorted({o.source for o in observations if o.source})

        return TrafficMetric(
            intersection_id=intersection_id,
            timestamp=now,
            vehicle_count=total_vehicles,
            flow_rate_vph=flow_rate,
            occupancy_pct=round(mean_occupancy, 1) if mean_occupancy is not None else None,
            avg_speed_kph=round(mean_speed, 1) if mean_speed is not None else None,
            queue_length_meters=queue_meters,
            avg_wait_time_sec=wait_sec,
            traffic_pressure=traffic_pressure,
            sample_window_sec=sample_window_sec,
            data_quality=quality,
            calculation_method=CALCULATION_METHOD,
            provenance={
                "observation_count": len(observations),
                "counted_observation_count": len(counted),
                "sources_used": sources_used,
                "input_speed_samples": len(valid_speeds),
                "input_occupancy_samples": len(valid_occupancies),
                "newest_observation_at": newest.isoformat() if newest else None,
                "observation_age_sec": round(age_sec, 1) if age_sec >= 0 else None,
                "flow_rate_basis": flow_rate_basis,
                "assumptions": {
                    "queued_vehicle_spacing_meters": QUEUED_VEHICLE_SPACING_METERS,
                    "queue_discharge_veh_per_sec": QUEUE_DISCHARGE_VEH_PER_SEC,
                },
                "calculated_at": now.isoformat(),
            }
        )
