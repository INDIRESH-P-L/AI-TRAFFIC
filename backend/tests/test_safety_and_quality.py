"""TRAFFICINTEL AI - Automated Safety Engine & Core Domain Tests
"""

import pytest
from datetime import datetime, timedelta, timezone
from app.models.entities import SignalController, SignalPhase, SignalCommand, utc_now
from app.safety.safety_engine import DeterministicSafetyEngine
from app.traffic.quality_engine import DataQualityEngine
from app.traffic.sensor_fusion import SensorFusionEngine
from app.traffic.state_engine import TrafficStateEngine


def create_test_controller(connection_status="CONNECTED", active_phase=2, elapsed_sec=15.0):
    ctrl = SignalController(
        id="ctrl_test_01",
        intersection_id="inter_test_01",
        name="Main St & 1st Ave Controller",
        vendor="Econolite",
        model="ASC/3",
        protocol="NTCIP_1202",
        ip_address="192.168.1.100",
        port=501,
        connection_status=connection_status,
        active_phase=active_phase,
        current_phase_start=utc_now() - timedelta(seconds=elapsed_sec)
    )

    p2 = SignalPhase(
        controller_id=ctrl.id,
        phase_number=2,
        ring=1,
        barrier=1,
        name="NB Thru",
        min_green=7,
        max_green=65,
        yellow_change=4,
        red_clearance=2,
        conflicting_phases=[4, 8]  # Conflicting cross-street movements
    )
    p4 = SignalPhase(
        controller_id=ctrl.id,
        phase_number=4,
        ring=1,
        barrier=2,
        name="EB Thru",
        min_green=7,
        max_green=50,
        yellow_change=4,
        red_clearance=2,
        conflicting_phases=[2, 6]
    )
    ctrl.phases = [p2, p4]
    return ctrl


def test_safety_rejects_conflicting_phase():
    """Deterministic Safety Engine must REJECT direct transition into a conflicting phase."""
    ctrl = create_test_controller(active_phase=2)
    # Phase 4 conflicts with currently active Phase 2
    res = DeterministicSafetyEngine.validate_command(
        controller=ctrl,
        requested_phase_num=4,
        duration_sec=15,
        issued_at=utc_now(),
        idempotency_key="key_001"
    )
    assert not res.is_safe
    assert any("conflicts with active Phase" in v for v in res.violations)


def test_safety_rejects_before_minimum_green():
    """Cannot cut off an active phase before its minimum green interval has elapsed."""
    # Active phase has only run for 3 seconds, but min_green is 7 seconds
    ctrl = create_test_controller(active_phase=2, elapsed_sec=3.0)
    # Request non-conflicting phase 2 hold
    res = DeterministicSafetyEngine.validate_command(
        controller=ctrl,
        requested_phase_num=2,
        duration_sec=4,  # Under min_green
        issued_at=utc_now(),
        idempotency_key="key_002"
    )
    assert not res.is_safe
    assert any("below minimum green requirement" in v for v in res.violations)


def test_safety_rejects_disconnected_hardware():
    """Cannot issue control commands to disconnected controllers."""
    ctrl = create_test_controller(connection_status="NOT_CONNECTED")
    res = DeterministicSafetyEngine.validate_command(
        controller=ctrl,
        requested_phase_num=2,
        duration_sec=15,
        issued_at=utc_now(),
        idempotency_key="key_003"
    )
    assert not res.is_safe
    assert any("Cannot execute commands on disconnected" in v for v in res.violations)


def test_safety_stale_command_protection():
    """Commands older than 5.0 seconds MUST be rejected to protect against network delay."""
    ctrl = create_test_controller()
    stale_time = utc_now() - timedelta(seconds=8.0)
    res = DeterministicSafetyEngine.validate_command(
        controller=ctrl,
        requested_phase_num=2,
        duration_sec=15,
        issued_at=stale_time,
        idempotency_key="key_004"
    )
    assert not res.is_safe
    assert any("Command expired" in v for v in res.violations)


def test_data_quality_engine_transitions():
    """Telemetry stream freshness transitions: FRESH -> AGING -> STALE -> DISCONNECTED."""
    now = datetime.now(timezone.utc)
    
    # 5 seconds ago -> FRESH
    q, age = DataQualityEngine.evaluate_freshness(now - timedelta(seconds=5))
    assert q == "FRESH"
    
    # 35 seconds ago -> AGING
    q, age = DataQualityEngine.evaluate_freshness(now - timedelta(seconds=35))
    assert q == "AGING"
    
    # 100 seconds ago -> STALE
    q, age = DataQualityEngine.evaluate_freshness(now - timedelta(seconds=100))
    assert q == "STALE"
    
    # 300 seconds ago -> DISCONNECTED
    q, age = DataQualityEngine.evaluate_freshness(now - timedelta(seconds=300))
    assert q == "DISCONNECTED"

    # None -> DISCONNECTED
    q, age = DataQualityEngine.evaluate_freshness(None)
    assert q == "DISCONNECTED"


def test_data_quality_bounds_validation():
    """Physical range validation rejects physically impossible measurements."""
    valid, err = DataQualityEngine.validate_measurement_bounds("occupancy_pct", 150.0)
    assert not valid
    assert "out of physical bounds" in err

    valid, err = DataQualityEngine.validate_measurement_bounds("speed_kph", 320.0)
    assert not valid

    valid, err = DataQualityEngine.validate_measurement_bounds("vehicle_count", -5)
    assert not valid


def test_traffic_state_engine_zero_fake_data():
    """Empty observations return explicit NO_DATA and None values instead of fabricated averages."""
    metric = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_empty",
        observations=[]
    )
    assert metric.data_quality == "NO_DATA"
    assert metric.vehicle_count is None
    assert metric.avg_speed_kph is None
    assert metric.traffic_pressure is None
    assert metric.calculation_method == "UNAVAILABLE_ZERO_OBSERVATIONS"


def test_safety_engine_handles_naive_timestamps_from_the_database():
    """Persisted controllers return naive datetimes; the engine must not raise.

    SQLAlchemy's DateTime column drops the timezone on SQLite, so a controller
    loaded from the database carries a naive `current_phase_start` while the
    engine compares against aware UTC. Subtracting the two used to raise
    TypeError, turning every command against a persisted controller into a 500.
    """
    ctrl = create_test_controller(active_phase=2, elapsed_sec=3.0)
    ctrl.current_phase_start = ctrl.current_phase_start.replace(tzinfo=None)

    res = DeterministicSafetyEngine.validate_command(
        controller=ctrl,
        requested_phase_num=4,
        duration_sec=15,
        issued_at=utc_now().replace(tzinfo=None),
        idempotency_key="key_naive_ts",
    )

    # The point is that it evaluates rather than raising; phase 4 conflicts
    # with the active phase 2, so the verdict is a rejection.
    assert not res.is_safe
    assert res.details["active_phase_elapsed_sec"] == pytest.approx(3.0, abs=1.0)
