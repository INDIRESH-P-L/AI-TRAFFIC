"""TRAFFICINTEL AI - Phase 1 Operations Console Tests

Covers the endpoints the interactive console depends on: the dry-run command
preview, the layered map, and the junction timeline/replay. The recurring theme
is that each must report absence truthfully and must not have side effects the
operator did not ask for.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.main import app
from app.models.entities import (
    Camera, Intersection, Sensor, SignalCommand, SignalController, SignalPhase,
    TrafficMetric, TrafficObservation, User, utc_now,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def headers():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "console_admin").first():
            db.add(User(
                username="console_admin",
                email="console_admin@trafficintel.gov",
                hashed_password=get_password_hash("SecretPass123!"),
                full_name="Console Test Operator",
                role="ADMIN",
            ))
            db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "console_admin", "password": "SecretPass123!"},
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def junction():
    """A junction with a CONNECTED controller displaying phase 2."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "CON-001").first()
        if not inter:
            inter = Intersection(
                name="Console Test Junction", code="CON-001",
                latitude=12.9716, longitude=77.5946, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="Console Controller",
                vendor="Emulator", model="NTCIP-1202", protocol="ASC3_ETHERNET",
                ip_address="127.0.0.1", port=9,
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
            db.add(Sensor(
                intersection_id=inter.id, name="NB stop bar", sensor_type="RADAR",
                health_status="DISCONNECTED",
            ))
            db.add(Camera(
                intersection_id=inter.id, name="NB approach",
                stream_url="rtsp://127.0.0.1:554/s", stream_status="OFFLINE",
            ))
            db.commit()

        controller = (
            db.query(SignalController)
            .filter(SignalController.intersection_id == inter.id)
            .first()
        )
        return {"intersection_id": inter.id, "controller_id": controller.id}
    finally:
        db.close()


# ===========================================================================
# Structured per-rule safety verdicts
# ===========================================================================

def test_safety_result_reports_every_rule_with_its_own_verdict():
    """The console renders one row per rule, so each needs its own outcome."""
    from app.safety.safety_engine import DeterministicSafetyEngine

    controller = SignalController(
        id="ctrl_checks", intersection_id="i", name="C", vendor="v", model="m",
        protocol="NTCIP_1202", ip_address="127.0.0.1", port=161,
        connection_status="CONNECTED", active_phase=2,
        current_phase_start=utc_now() - timedelta(seconds=30),
    )
    controller.phases = [
        SignalPhase(controller_id="ctrl_checks", phase_number=2, ring=1, barrier=1,
                    name="NB", min_green=7, max_green=65, conflicting_phases=[4]),
        SignalPhase(controller_id="ctrl_checks", phase_number=4, ring=1, barrier=2,
                    name="EB", min_green=7, max_green=50, conflicting_phases=[2]),
    ]

    result = DeterministicSafetyEngine.validate_command(
        controller=controller, requested_phase_num=4, duration_sec=15,
        issued_at=utc_now(), idempotency_key="checks_key_1",
    )

    assert len(result.checks) == len(result.checks_performed)
    codes = {c.code for c in result.checks}
    for expected in (
        "IDEMPOTENCY_VERIFICATION",
        "COMMAND_FRESHNESS_CHECK",
        "CONTROLLER_STATE_VALIDATION",
        "PHASE_CONFIGURATION_LOOKUP",
        "ACTIVE_PHASE_MINIMUM_GREEN_CHECK",
        "PHASE_CONFLICT_MATRIX_VALIDATION",
        "CLEARANCE_INTERVAL_CONFLICT_CHECK",
        "MAX_GREEN_DURATION_CHECK",
    ):
        assert expected in codes, expected

    # Passing rules explain themselves too - the panel shows why a rule passed,
    # not only why one failed.
    assert all(c.detail for c in result.checks)

    conflict = next(c for c in result.checks if c.code == "PHASE_CONFLICT_MATRIX_VALIDATION")
    assert conflict.passed is False
    assert conflict.standard and "NEMA" in conflict.standard

    # violations stays the list of failed details, for older consumers.
    assert result.violations == [c.detail for c in result.checks if not c.passed]


# ===========================================================================
# Dry-run command preview
# ===========================================================================

def test_command_preview_writes_no_command_row(headers, junction):
    """A preview must not consume its idempotency key or create a command."""
    db = SessionLocal()
    before = db.query(SignalCommand).count()
    db.close()

    response = client.post(
        "/api/v1/signals/commands/validate?refresh_state=false",
        json={
            "controller_id": junction["controller_id"],
            "requested_phase": 2,
            "command_type": "PHASE_HOLD",
            "duration_sec": 15,
            "idempotency_key": "preview-does-not-write",
        },
        headers=headers,
    )

    assert response.status_code == 200

    db = SessionLocal()
    after = db.query(SignalCommand).count()
    spent = db.query(SignalCommand).filter(
        SignalCommand.idempotency_key == "preview-does-not-write"
    ).first()
    db.close()

    assert after == before, "Preview must not persist a command"
    assert spent is None, "Preview must not consume the idempotency key"


def test_command_preview_returns_per_rule_verdicts(headers, junction):
    response = client.post(
        "/api/v1/signals/commands/validate?refresh_state=false",
        json={
            "controller_id": junction["controller_id"],
            "requested_phase": 4,
            "command_type": "PHASE_HOLD",
            "duration_sec": 15,
            "idempotency_key": "preview-conflict",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["would_be_accepted"] is False

    checks = body["safety_report"]["checks"]
    assert len(checks) >= 6
    failed = [c for c in checks if not c["passed"]]
    assert failed, "A conflicting phase must fail at least one rule"
    assert any("conflicts with" in c["detail"] for c in failed)


def test_command_preview_refresh_marks_unreadable_controller(headers, junction):
    """With refresh on, the preview re-reads the hardware and reports what it found."""
    response = client.post(
        "/api/v1/signals/commands/validate?refresh_state=true",
        json={
            "controller_id": junction["controller_id"],
            "requested_phase": 2,
            "command_type": "PHASE_HOLD",
            "duration_sec": 15,
            "idempotency_key": "preview-refresh",
        },
        headers=headers,
    )

    assert response.status_code == 200
    body = response.json()

    # The fixture controller points at a closed port on a reachability-only
    # protocol, so a real read fails and the command must be refused.
    assert body["would_be_accepted"] is False
    assert body["controller_state"]["state_readable"] is False
    state_check = next(
        c for c in body["safety_report"]["checks"]
        if c["code"] == "CONTROLLER_STATE_VALIDATION"
    )
    assert state_check["passed"] is False


# ===========================================================================
# Map layers
# ===========================================================================

def test_map_layers_carry_provenance_on_every_feature(headers, junction):
    response = client.get("/api/v1/map", headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert set(body["quality_thresholds_sec"]) == {"fresh", "aging", "stale"}

    for layer_name, layer in body["layers"].items():
        for feature in layer["features"]:
            assert "quality" in feature, f"{layer_name} feature missing provenance"
            quality = feature["quality"]
            assert set(quality) >= {"state", "age_sec", "observed_at", "source"}


def test_map_layers_report_truthful_empty_reasons(headers):
    response = client.get("/api/v1/map", headers=headers)
    layers = response.json()["layers"]

    # Layers with no real records name the reason rather than looking broken.
    for name in ("weather", "transit"):
        layer = layers[name]
        if not layer["features"]:
            assert layer["empty_reason"] is not None
            assert layer["empty_reason"].isupper()


def test_map_layer_filter_returns_only_requested_layers(headers):
    response = client.get("/api/v1/map?include=junctions", headers=headers)
    assert response.status_code == 200
    assert list(response.json()["layers"].keys()) == ["junctions"]


def test_map_devices_declare_inherited_coordinates(headers, junction):
    """Cameras and sensors have no coordinates of their own, and say so."""
    response = client.get("/api/v1/map?include=cameras,sensors", headers=headers)
    layers = response.json()["layers"]

    for name in ("cameras", "sensors"):
        for feature in layers[name]["features"]:
            assert feature["position_source"] == (
                "INHERITED_FROM_INTERSECTION_NO_DEVICE_COORDINATES"
            )


def test_map_junction_without_telemetry_reports_no_data(headers, junction):
    response = client.get("/api/v1/map?include=junctions", headers=headers)
    features = response.json()["layers"]["junctions"]["features"]
    feature = next(f for f in features if f["id"] == junction["intersection_id"])

    assert feature["traffic"]["data_quality"] == "NO_DATA"
    assert feature["traffic"]["quality"]["state"] == "DISCONNECTED"
    assert feature["traffic"]["quality"]["observed_at"] is None


# ===========================================================================
# Timeline & replay
# ===========================================================================

def test_timeline_returns_real_recorded_events(headers, junction):
    response = client.get(f"/api/v1/timeline/{junction['intersection_id']}", headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["intersection_id"] == junction["intersection_id"]
    for event in body["events"]:
        assert event["timestamp"]
        assert event["kind"] in {
            "INCIDENT", "INCIDENT_RESOLVED", "SIGNAL_COMMAND", "PREEMPTION", "AUDIT",
        }


def test_timeline_reports_empty_window_truthfully(headers):
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "CON-EMPTY").first()
        if not inter:
            inter = Intersection(
                name="Console Empty Junction", code="CON-EMPTY",
                latitude=12.5, longitude=77.5, operational_status="HEALTHY",
            )
            db.add(inter)
            db.commit()
            db.refresh(inter)
        intersection_id = inter.id
    finally:
        db.close()

    response = client.get(f"/api/v1/timeline/{intersection_id}?hours=1", headers=headers)
    body = response.json()

    assert body["events"] == []
    assert body["empty_reason"] == "NO_RECORDED_EVENTS_IN_WINDOW"


def test_replay_refuses_to_draw_a_trend_from_too_few_samples(headers, junction):
    response = client.get(
        f"/api/v1/timeline/{junction['intersection_id']}/replay?minutes=60",
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["sufficient_data"] is False
    assert body["empty_reason"] in (
        "NO_STORED_TELEMETRY_FOR_THIS_WINDOW",
        "INSUFFICIENT_SAMPLES_FOR_REPLAY",
    )
    assert body["interpolation"] == "NONE_GAPS_ARE_PRESERVED"
    assert body["metrics"] == []


def test_replay_returns_stored_samples_without_interpolating(headers):
    """With real stored metrics the replay returns exactly those samples."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "CON-REPLAY").first()
        if not inter:
            inter = Intersection(
                name="Console Replay Junction", code="CON-REPLAY",
                latitude=12.6, longitude=77.6, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            base = datetime.now(timezone.utc).replace(tzinfo=None)
            # Deliberately uneven spacing, including a gap: the endpoint must
            # return the samples as recorded rather than filling the hole.
            for offset_min, count in ((30, 4), (28, 6), (26, 5), (5, 9)):
                db.add(TrafficMetric(
                    intersection_id=inter.id,
                    timestamp=base - timedelta(minutes=offset_min),
                    vehicle_count=count,
                    occupancy_pct=12.5,
                    avg_speed_kph=31.0,
                    sample_window_sec=60.0,
                    data_quality="FRESH",
                    calculation_method="TEST_FIXTURE_STORED_SAMPLE",
                    provenance={"sources_used": ["radar_north"]},
                ))
                db.add(TrafficObservation(
                    intersection_id=inter.id,
                    source="radar_north",
                    timestamp=base - timedelta(minutes=offset_min),
                    vehicle_count=count,
                    quality="FRESH",
                ))
            db.commit()
            db.refresh(inter)
        intersection_id = inter.id
    finally:
        db.close()

    response = client.get(
        f"/api/v1/timeline/{intersection_id}/replay?minutes=60", headers=headers
    )
    body = response.json()

    assert body["sufficient_data"] is True
    assert body["sample_count"] == 4
    assert len(body["metrics"]) == 4
    assert body["interpolation"] == "NONE_GAPS_ARE_PRESERVED"

    # Samples come back in recorded order, gap intact.
    stamps = [m["timestamp"] for m in body["metrics"]]
    assert stamps == sorted(stamps)

    # Every sample carries its calculation method and window.
    for metric in body["metrics"]:
        assert metric["calculation_method"]
        assert metric["sample_window_sec"] == 60.0


def test_junction_quality_rolls_up_worst_source_not_freshest(headers):
    """A live controller must not mask detectors that went silent.

    The junction marker colour comes from this roll-up. Taking the most recent
    source would paint a junction green because its controller answered a
    heartbeat, while the detectors feeding every traffic number on screen had
    stopped reporting an hour earlier.
    """
    from app.api.v1.endpoints.map_layers import _worst_quality

    fresh_controller = {
        "state": "FRESH", "age_sec": 2.0,
        "observed_at": "2026-01-01T00:00:02+00:00", "source": "controller:NTCIP_1202",
    }
    stale_detectors = {
        "state": "STALE", "age_sec": 140.0,
        "observed_at": "2026-01-01T00:00:00+00:00", "source": ["radar_north"],
    }

    rolled = _worst_quality([fresh_controller, stale_detectors])
    assert rolled["state"] == "STALE"
    assert rolled["age_sec"] == 140.0
    # Both contributing sources stay visible in the envelope.
    assert "controller:NTCIP_1202" in rolled["source"]

    # No configured source at all is NO_DATA, not FRESH and not an error.
    empty = _worst_quality([])
    assert empty["state"] == "NO_DATA"
    assert empty["observed_at"] is None


def test_junction_quality_basis_names_its_sources(headers, junction):
    response = client.get("/api/v1/map?include=junctions", headers=headers)
    features = response.json()["layers"]["junctions"]["features"]
    feature = next(f for f in features if f["id"] == junction["intersection_id"])

    assert feature["quality"]["state"] in {
        "FRESH", "AGING", "STALE", "DISCONNECTED", "NO_DATA", "UNKNOWN", "INVALID",
    }
    assert feature["quality_basis"], "Every junction states what its verdict rests on"
