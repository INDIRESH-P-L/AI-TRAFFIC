"""TRAFFICINTEL AI - Phase 0 Truthfulness Tests

These tests pin the invariants that Phase 0 repaired. Each one fails if the
platform starts reporting something it did not measure.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.main import app
from app.models.entities import (
    Intersection, SignalController, SignalPhase, TrafficObservation, User, utc_now
)
from app.providers import snmp_codec as snmp
from app.providers.camera_provider import NetworkCameraAdapter
from app.providers.controller_provider import (
    Ntcip1202Adapter,
    ReachabilityOnlyAdapter,
    get_controller_adapter,
)
from app.providers.controller_sync import apply_controller_reading
from app.traffic.state_engine import TrafficStateEngine
from tools.ntcip_emulator import ConcurrentGroup, NtcipEmulatorServer, SignalControllerEmulator

client = TestClient(app)


# ===========================================================================
# Adapter honesty
# ===========================================================================

def test_reachability_adapter_never_reports_a_phase_it_did_not_read():
    """A TCP handshake carries no phase information, so none may be reported."""
    adapter = ReachabilityOnlyAdapter(ip_address="203.0.113.1", port=501, timeout=0.05)

    assert adapter.get_current_phase() is None

    status = adapter.get_controller_status()
    assert status["state_readable"] is False
    assert status["active_plan"] is None
    assert status["cycle_second"] is None
    assert status["green_phases"] is None
    assert status["state_unreadable_reason"] in (
        "NOT_CONNECTED",
        "UNREADABLE_NO_PROTOCOL_SESSION",
    )


def test_reachability_adapter_refuses_to_claim_a_command_succeeded():
    """Without a command channel the adapter must fail, not acknowledge."""
    adapter = ReachabilityOnlyAdapter(ip_address="203.0.113.1", port=501, timeout=0.05)
    success, message, payload = adapter.send_command(phase_number=2, duration_sec=15)

    assert success is False
    assert payload["rejected_reason"] == "NO_COMMAND_CHANNEL_FOR_PROTOCOL"
    assert "NTCIP_1202" in message


def test_adapter_factory_only_returns_a_command_capable_adapter_for_ntcip():
    assert isinstance(
        get_controller_adapter("Econolite", "ASC/3", "NTCIP_1202", "127.0.0.1", 161),
        Ntcip1202Adapter,
    )
    for protocol in ("ASC3_ETHERNET", "REST_GATEWAY", "TEST_SOCKET", ""):
        adapter = get_controller_adapter("Generic", "Model", protocol, "127.0.0.1", 501)
        assert isinstance(adapter, ReachabilityOnlyAdapter)
        assert adapter.supports_command is False


def test_camera_adapter_does_not_invent_stream_properties():
    """A closed port yields nulls and a reason, never a typical resolution."""
    adapter = NetworkCameraAdapter(stream_url="rtsp://203.0.113.1:554/stream", timeout=0.05)
    info = adapter.get_stream_info()

    assert info["fps"] is None
    assert info["resolution"] is None
    assert info["measurement_status"].startswith("NOT_MEASURED")


# ===========================================================================
# NTCIP 1202 over the real protocol
# ===========================================================================

def test_snmp_codec_roundtrips_get_set_and_response():
    get_pdu = snmp.build_get_request("public", 42, ["1.3.6.1.4.1.1206.4.2.1.1.4.1.4.1"])
    parsed = snmp.parse_message(get_pdu)
    assert parsed.pdu_tag == snmp.TAG_GET_REQUEST
    assert parsed.request_id == 42
    assert parsed.varbinds[0].oid == "1.3.6.1.4.1.1206.4.2.1.1.4.1.4.1"

    set_pdu = snmp.build_set_request("private", 7, [("1.3.6.1.4.1.1206.4.2.1.1.5.1.4.1", 2)])
    parsed_set = snmp.parse_message(set_pdu)
    assert parsed_set.pdu_tag == snmp.TAG_SET_REQUEST
    assert parsed_set.varbinds[0].value == 2

    response = snmp.build_response("public", 42, [snmp.VarBind(oid="1.3.6.1.2.1.1.1.0", value=8)])
    parsed_response = snmp.parse_message(response)
    assert parsed_response.error_status == 0
    assert parsed_response.varbinds[0].value == 8


def test_snmp_codec_rejects_malformed_payloads():
    """A truncated datagram raises rather than decoding to a plausible value."""
    with pytest.raises(snmp.SnmpDecodeError):
        snmp.parse_message(b"\x30\x82\xff\xff\x02\x01\x00")


@pytest.fixture
def emulator():
    """A fast-cycling NTCIP 1202 emulator on an ephemeral port."""
    groups = [
        ConcurrentGroup(
            phases=phases,
            min_green_sec=0.6,
            max_green_sec=3.0,
            yellow_sec=0.3,
            red_clearance_sec=0.2,
        )
        for phases in ([2, 6], [4, 8])
    ]
    server = NtcipEmulatorServer(
        host="127.0.0.1", port=0, emulator=SignalControllerEmulator(groups=groups)
    ).start()
    yield server
    server.stop()


def test_ntcip_adapter_reads_real_phase_state_from_the_wire(emulator):
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=emulator.port, timeout=1.0)

    connected, message = adapter.connect()
    assert connected, message

    status = adapter.read_phase_status()
    assert status["readable"] is True
    # Dual-ring: the emulator serves two concurrent greens, or none mid-clearance.
    assert status["greens"] in ([2, 6], [4, 8], [])
    # Whatever is not green or yellow must be reported red - no phase is unaccounted for.
    accounted = set(status["greens"]) | set(status["yellows"]) | set(status["reds"])
    assert accounted == {2, 4, 6, 8}


def test_ntcip_adapter_observes_the_sequence_advancing(emulator):
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=emulator.port, timeout=1.0)
    assert adapter.connect()[0]

    observed = set()
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline and len(observed) < 2:
        status = adapter.read_phase_status()
        if status["readable"] and status["greens"]:
            observed.add(tuple(status["greens"]))
        time.sleep(0.15)

    assert observed == {(2, 6), (4, 8)}, "Both barrier groups should be served"


def test_ntcip_hold_is_acknowledged_and_read_back(emulator):
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=emulator.port, timeout=1.0)
    assert adapter.connect()[0]

    success, message, payload = adapter.send_command(phase_number=2, duration_sec=15)

    assert success is True
    assert payload["hold_bitmap"] == 0b10  # phase 2 -> bit 1
    assert payload["control_oid"].startswith("1.3.6.1.4.1.1206.4.2.1.1.5.1.4")
    # The read-back is evidence, and it is always present on success.
    assert payload["readback"]["readable"] is True


def test_ntcip_adapter_reports_unreadable_when_nothing_answers():
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=9, timeout=0.2, retries=0)

    connected, _message = adapter.connect()
    assert connected is False
    assert adapter.get_current_phase() is None

    status = adapter.get_controller_status()
    assert status["state_readable"] is False
    assert status["green_phases"] is None


# ===========================================================================
# Controller state synchronisation
# ===========================================================================

def _controller(**overrides) -> SignalController:
    controller = SignalController(
        id="ctrl_sync_test",
        intersection_id="inter_sync_test",
        name="Sync Test Controller",
        vendor="Econolite",
        model="ASC/3",
        protocol=overrides.pop("protocol", "NTCIP_1202"),
        ip_address="127.0.0.1",
        port=overrides.pop("port", 161),
        connection_status=overrides.pop("connection_status", "NOT_CONNECTED"),
        active_phase=overrides.pop("active_phase", None),
        current_phase_start=overrides.pop("current_phase_start", None),
    )
    for key, value in overrides.items():
        setattr(controller, key, value)
    return controller


def test_unreadable_controller_clears_stale_phase_state():
    """A controller that cannot be read must not keep showing its last phase."""
    controller = _controller(
        connection_status="CONNECTED",
        active_phase=2,
        current_phase_start=utc_now(),
        port=9,
    )
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=9, timeout=0.2, retries=0)

    provenance = apply_controller_reading(controller, adapter)

    assert provenance["state_readable"] is False
    assert controller.active_phase is None
    assert controller.current_phase_start is None
    assert controller.connection_status in ("DISCONNECTED", "NOT_CONNECTED")


def test_reachable_but_unreadable_controller_is_not_marked_connected():
    """REACHABLE is a distinct state, and the safety engine refuses commands on it."""
    from app.safety.safety_engine import DeterministicSafetyEngine

    controller = _controller(protocol="ASC3_ETHERNET", connection_status="REACHABLE")
    phase = SignalPhase(
        controller_id=controller.id, phase_number=2, ring=1, barrier=1,
        name="NB Thru", min_green=7, max_green=65, conflicting_phases=[4],
    )
    controller.phases = [phase]

    result = DeterministicSafetyEngine.validate_command(
        controller=controller,
        requested_phase_num=2,
        duration_sec=15,
        issued_at=utc_now(),
        idempotency_key="reachable_only_key",
    )

    assert result.is_safe is False
    assert any("phase state cannot be read" in v for v in result.violations)


def test_controller_sync_records_observed_phase_not_requested_phase(emulator):
    controller = _controller(port=emulator.port)
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=emulator.port, timeout=1.0)

    provenance = apply_controller_reading(controller, adapter)

    assert controller.connection_status == "CONNECTED"
    assert provenance["state_readable"] is True
    if controller.active_phase is not None:
        # Whatever was recorded must be a phase the emulator actually displayed.
        assert controller.active_phase in provenance["green_phases"]


# ===========================================================================
# Traffic state engine: declared assumptions, measured freshness
# ===========================================================================

def _observation(count=10, occupancy=None, speed=None, age_sec=1.0, source="radar_north"):
    return TrafficObservation(
        intersection_id="inter_state_test",
        source=source,
        timestamp=datetime.now(timezone.utc) - timedelta(seconds=age_sec),
        vehicle_count=count,
        occupancy_pct=occupancy,
        avg_speed_kph=speed,
        quality="FRESH",
    )


def test_flow_rate_is_null_without_a_known_sample_window():
    """`vehicles x 60` silently assumed a one-minute sample. It must not."""
    metric = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=12)],
    )

    assert metric.flow_rate_vph is None
    assert metric.sample_window_sec is None
    assert metric.provenance["flow_rate_basis"] == "NOT_CALCULATED_SAMPLE_WINDOW_UNKNOWN"


def test_flow_rate_is_extrapolated_from_the_declared_window():
    metric = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=12)],
        sample_window_sec=60.0,
    )

    assert metric.flow_rate_vph == pytest.approx(720.0)
    assert metric.sample_window_sec == 60.0
    assert "60S" in metric.provenance["flow_rate_basis"]


def test_traffic_pressure_is_null_when_occupancy_was_not_observed():
    """Pressure previously defaulted a missing occupancy to 0.5 to stay printable."""
    metric = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=12, occupancy=None)],
    )

    assert metric.occupancy_pct is None
    assert metric.traffic_pressure is None


def test_aggregate_freshness_follows_the_oldest_input_not_the_run_time():
    """An aggregate of stale readings is stale, however recently it was computed."""
    stale = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=5, age_sec=100.0)],
    )
    assert stale.data_quality == "STALE"

    fresh = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=5, age_sec=2.0)],
    )
    assert fresh.data_quality == "FRESH"

    disconnected = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=5, age_sec=400.0)],
    )
    assert disconnected.data_quality == "DISCONNECTED"


def test_declared_assumptions_travel_with_the_metric():
    metric = TrafficStateEngine.aggregate_intersection_state(
        intersection_id="inter_state_test",
        observations=[_observation(count=4, occupancy=30.0)],
    )
    assumptions = metric.provenance["assumptions"]

    assert assumptions["queued_vehicle_spacing_meters"] == 6.0
    assert assumptions["queue_discharge_veh_per_sec"] == 1.5
    assert metric.provenance["newest_observation_at"] is not None


# ===========================================================================
# Emergency preemption goes through the safety engine
# ===========================================================================

@pytest.fixture(scope="module")
def auth_headers():
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "evp_admin").first()
        if not user:
            db.add(User(
                username="evp_admin",
                email="evp_admin@trafficintel.gov",
                hashed_password=get_password_hash("SecretPass123!"),
                full_name="EVP Test Operator",
                role="ADMIN",
            ))
            db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "evp_admin", "password": "SecretPass123!"},
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def evp_intersection():
    """An intersection with a CONNECTED controller running phase 2."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "EVP-001").first()
        if not inter:
            inter = Intersection(
                name="EVP Test Junction", code="EVP-001",
                latitude=12.9716, longitude=77.5946, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="EVP Controller",
                vendor="Econolite", model="ASC/3", protocol="NTCIP_1202",
                ip_address="127.0.0.1", port=161,
                connection_status="CONNECTED",
                active_phase=2,
                current_phase_start=utc_now() - timedelta(seconds=30),
            )
            db.add(controller)
            db.flush()
            db.add_all([
                SignalPhase(
                    controller_id=controller.id, phase_number=2, ring=1, barrier=1,
                    name="NB Thru", min_green=7, max_green=65, conflicting_phases=[4, 8],
                ),
                SignalPhase(
                    controller_id=controller.id, phase_number=4, ring=1, barrier=2,
                    name="EB Thru", min_green=7, max_green=50, conflicting_phases=[2, 6],
                ),
            ])
            db.commit()
        return inter.id
    finally:
        db.close()


def test_preemption_is_rejected_when_it_would_create_a_conflict(auth_headers, evp_intersection):
    """Preemption raises priority, never permission: phase 4 conflicts with active phase 2."""
    response = client.post(
        "/api/v1/emergency",
        json={
            "intersection_id": evp_intersection,
            "vehicle_id": "MED-402",
            "vehicle_type": "AMBULANCE",
            "requested_phase": 4,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["safety_clearance_passed"] is False
    assert body["status"] == "REJECTED"
    assert any("conflicts with active Phase" in v for v in body["safety_report"]["violations"])


def test_preemption_records_the_full_safety_report(auth_headers, evp_intersection):
    response = client.post(
        "/api/v1/emergency",
        json={
            "intersection_id": evp_intersection,
            "vehicle_id": "MED-403",
            "vehicle_type": "FIRE_TRUCK",
            "requested_phase": 2,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    report = response.json()["safety_report"]
    assert "PHASE_CONFLICT_MATRIX_VALIDATION" in report["checks_performed"]
    assert "COMMAND_FRESHNESS_CHECK" in report["checks_performed"]
    assert "CONTROLLER_STATE_VALIDATION" in report["checks_performed"]


def test_preemption_without_a_controller_is_rejected(auth_headers):
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "EVP-NOCTRL").first()
        if not inter:
            inter = Intersection(
                name="EVP No Controller Junction", code="EVP-NOCTRL",
                latitude=12.9, longitude=77.6, operational_status="HEALTHY",
            )
            db.add(inter)
            db.commit()
            db.refresh(inter)
        intersection_id = inter.id
    finally:
        db.close()

    response = client.post(
        "/api/v1/emergency",
        json={
            "intersection_id": intersection_id,
            "vehicle_id": "MED-404",
            "vehicle_type": "POLICE",
            "requested_phase": 2,
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["safety_clearance_passed"] is False
    assert body["controller_id"] is None
    assert any("no controllable hardware" in v for v in body["safety_report"]["violations"])


# ===========================================================================
# Forecasting refuses to report metrics for a model that does not exist
# ===========================================================================

def test_forecast_without_history_invents_no_points_model_or_error_metrics(
    auth_headers, evp_intersection
):
    """No stored history, so nothing may be drawn, fitted or measured.

    Originally this pinned NO_FORECAST_MODEL_REGISTERED. The endpoint now fits a
    real model when history allows; with no history at all the metric is
    NOT_COMPUTABLE, and the invariant this test exists for is unchanged: no
    forecast line, no model and no error metric appear from nothing.
    """
    response = client.get(
        "/api/v1/predictions/forecast/" + evp_intersection, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["forecast_points"] == []
    assert body["forecast_status"] in (
        "NOT_COMPUTABLE",
        "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST",
    )
    assert body["model"] is None
    assert body["backtest"] is None
    assert body.get("validation_metrics") is None


# ===========================================================================
# Schema is migration-managed
# ===========================================================================

def test_database_schema_is_at_migration_head():
    from app.core.migrations import check_schema_is_current

    is_current, message = check_schema_is_current()
    assert is_current, message


# ===========================================================================
# Clearance interval conflicts
# ===========================================================================

def test_conflicting_phase_is_rejected_during_a_clearance_interval():
    """No phase reads green during yellow, but the intersection is still occupied.

    A conflict check that looked only at `active_phase` approved a conflicting
    movement while the opposing approach was mid-yellow, because `active_phase`
    is null whenever no phase displays green.
    """
    from app.safety.safety_engine import DeterministicSafetyEngine

    controller = _controller(connection_status="CONNECTED", active_phase=None)
    controller.clearing_phases = [2, 6]  # phases 2 and 6 are in yellow change
    controller.phases = [
        SignalPhase(
            controller_id=controller.id, phase_number=4, ring=1, barrier=2,
            name="EB Thru", min_green=7, max_green=50, conflicting_phases=[2, 6],
        ),
    ]

    result = DeterministicSafetyEngine.validate_command(
        controller=controller,
        requested_phase_num=4,
        duration_sec=15,
        issued_at=utc_now(),
        idempotency_key="clearance_conflict_key",
    )

    assert result.is_safe is False
    assert "CLEARANCE_INTERVAL_CONFLICT_CHECK" in result.checks_performed
    assert any("still in yellow change or all-red clearance" in v for v in result.violations)
    assert result.details["phases_in_clearance"] == [2, 6]


def test_non_conflicting_phase_is_allowed_during_a_clearance_interval():
    """The clearance check must gate conflicts only, not freeze the controller."""
    from app.safety.safety_engine import DeterministicSafetyEngine

    controller = _controller(connection_status="CONNECTED", active_phase=None)
    controller.clearing_phases = [2, 6]
    controller.phases = [
        SignalPhase(
            controller_id=controller.id, phase_number=6, ring=2, barrier=1,
            name="SB Thru", min_green=7, max_green=65, conflicting_phases=[4, 8],
        ),
    ]

    result = DeterministicSafetyEngine.validate_command(
        controller=controller,
        requested_phase_num=6,
        duration_sec=15,
        issued_at=utc_now(),
        idempotency_key="clearance_nonconflict_key",
    )

    assert result.is_safe is True, result.violations


def test_clearance_phases_are_cleared_when_state_becomes_unreadable():
    """Stale clearance data must not outlive the reading it came from."""
    controller = _controller(connection_status="CONNECTED", active_phase=2, port=9)
    controller.clearing_phases = [4, 8]
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=9, timeout=0.2, retries=0)

    apply_controller_reading(controller, adapter)

    assert controller.clearing_phases is None


def test_clearance_phases_are_recorded_from_the_emulator(emulator):
    """During a yellow interval the emulator's yellows land on the controller row."""
    controller = _controller(port=emulator.port)
    adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=emulator.port, timeout=1.0)

    saw_clearance = False
    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        provenance = apply_controller_reading(controller, adapter)
        assert provenance["state_readable"] is True
        if controller.clearing_phases:
            saw_clearance = True
            # Nothing is green while a phase is clearing.
            assert controller.active_phase is None
            assert set(controller.clearing_phases) in ({2, 6}, {4, 8})
            break
        time.sleep(0.05)

    assert saw_clearance, "A yellow interval should have been observed within the window"
