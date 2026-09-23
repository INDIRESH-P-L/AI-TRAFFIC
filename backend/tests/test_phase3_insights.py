"""TRAFFICINTEL AI - Phase 3 Operator Insight Tests

Trust scoring, post-change verification, corridor stringlines and shift
handover.

The theme across all four: each one produces a number that an operator would
act on, and each one has a specific way of producing a confident-looking number
from nothing. These tests pin the refusals.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.main import app
from app.models.entities import (
    Approach, Corridor, Intersection, Lane, Sensor, ShiftHandover,
    SignalController, SignalPhase, SignalStateLog, TrafficMetric,
    TrafficObservation, User, utc_now,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def headers():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "p3_admin").first():
            db.add(User(
                username="p3_admin", email="p3_admin@trafficintel.gov",
                hashed_password=get_password_hash("SecretPass123!"),
                full_name="Phase 3 Admin", role="ADMIN",
            ))
            db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "p3_admin", "password": "SecretPass123!"},
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


@pytest.fixture
def bare_junction():
    """A junction with nothing attached: no controller, no detectors."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "P3-BARE").first()
        if not inter:
            inter = Intersection(
                name="P3 Bare Junction", code="P3-BARE",
                latitude=11.10, longitude=76.10, operational_status="DISCONNECTED",
            )
            db.add(inter)
            db.commit()
            db.refresh(inter)
        return inter.id
    finally:
        db.close()


@pytest.fixture
def equipped_junction():
    """A junction with a controller and a detector that has reported."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "P3-EQUIP").first()
        if not inter:
            inter = Intersection(
                name="P3 Equipped Junction", code="P3-EQUIP",
                latitude=11.20, longitude=76.20, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="P3 Cab",
                vendor="Emulator", model="NTCIP-1202", protocol="NTCIP_1202",
                ip_address="127.0.0.1", port=9,
                connection_status="CONNECTED",
                last_heartbeat=utc_now(),
                active_phase=2,
                current_phase_start=utc_now() - timedelta(seconds=20),
            )
            db.add(controller)
            db.flush()
            db.add_all([
                SignalPhase(controller_id=controller.id, phase_number=2, ring=1,
                            barrier=1, name="NB", min_green=7, max_green=65,
                            conflicting_phases=[4]),
                SignalPhase(controller_id=controller.id, phase_number=4, ring=1,
                            barrier=2, name="EB", min_green=7, max_green=50,
                            conflicting_phases=[2]),
            ])
            db.add(Sensor(
                intersection_id=inter.id, name="P3 loop", sensor_type="INDUCTIVE_LOOP",
                health_status="CONNECTED",
                last_observation_timestamp=_naive(datetime.now(timezone.utc)),
            ))
            db.add(TrafficMetric(
                intersection_id=inter.id,
                timestamp=_naive(datetime.now(timezone.utc)),
                vehicle_count=12, occupancy_pct=18.0, avg_speed_kph=34.0,
                avg_wait_time_sec=12.0, sample_window_sec=60.0,
                data_quality="FRESH", calculation_method="TEST",
            ))
            now = _naive(datetime.now(timezone.utc))
            for offset in range(30):
                db.add(SignalStateLog(
                    controller_id=controller.id, intersection_id=inter.id,
                    timestamp=now - timedelta(seconds=offset * 10),
                    green_phases=[2, 6] if offset % 2 == 0 else [4, 8],
                    yellow_phases=[], red_phases=[],
                    source="NTCIP_1202_POLL", read_latency_ms=2.0,
                ))
            db.commit()
            db.refresh(inter)
        return inter.id
    finally:
        db.close()


# ===========================================================================
# Trust score
# ===========================================================================

def test_junction_with_nothing_attached_is_unrated_not_zero(headers, bare_junction):
    """Zero means 'measured and bad'. Nothing here has been measured."""
    response = client.get("/api/v1/trust/{}".format(bare_junction), headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert body["band"] == "UNRATED"
    assert body["score"] is None, "An unmonitored junction must not score zero"
    assert "measured and bad" in body["explanation"]
    assert body["ai_gate"]["allowed"] is False


def test_trust_components_are_individually_visible(headers, equipped_junction):
    """A single opaque number is the thing this platform exists to refuse."""
    body = client.get(
        "/api/v1/trust/{}".format(equipped_junction), headers=headers
    ).json()

    assert body["score"] is not None
    assert body["band"] in ("TRUSTED", "PARTIAL", "UNTRUSTED")

    names = {c["name"] for c in body["components"]}
    assert names == {
        "controller_readable", "telemetry_freshness", "detector_health",
        "signal_state_coverage", "sample_density",
    }

    for component in body["components"]:
        assert component["explanation"]
        assert component["status"] in ("SCORED", "NOT_APPLICABLE", "NOT_CONFIGURED")
        if component["status"] != "SCORED":
            assert component["score"] is None

    assert body["weakest_component"]["name"] in names


def test_missing_equipment_is_excluded_from_the_mean_not_scored_zero(
    headers, bare_junction, equipped_junction
):
    """A junction is not penalised for a camera it does not have."""
    body = client.get(
        "/api/v1/trust/{}".format(equipped_junction), headers=headers
    ).json()

    not_applicable = [c for c in body["components"] if c["status"] != "SCORED"]
    for component in not_applicable:
        assert component["score"] is None

    assert "Renormalised" in body["weight_basis"]
    assert body["components_scored"] + body["components_not_applicable"] == len(
        body["components"]
    )


def test_network_trust_excludes_unrated_from_the_mean(headers, bare_junction, equipped_junction):
    """Counting unrated junctions as zero would make an uninstrumented network
    look like a failing one."""
    body = client.get("/api/v1/trust/network", headers=headers).json()

    assert body["rated_count"] + body["unrated_count"] == body["junction_count"]
    assert "excluded rather than counted as zero" in body["mean_basis"]

    if body["rated_count"]:
        assert body["mean_score_of_rated"] is not None
    else:
        assert body["mean_score_of_rated"] is None


def test_optimizer_is_gated_by_trust_on_measured_demand(headers):
    """A recommendation from stale detectors carries unearned confidence."""
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "P3-GATED").first()
        if not inter:
            inter = Intersection(
                name="P3 Gated Junction", code="P3-GATED",
                latitude=11.30, longitude=76.30, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            approach = Approach(
                intersection_id=inter.id, direction="NORTHBOUND",
                road_name="Gated Rd", speed_limit_kph=50,
            )
            db.add(approach)
            db.flush()
            lane = Lane(
                approach_id=approach.id, lane_number=1,
                movement_type="THRU", assigned_phase=2,
            )
            db.add(lane)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="Gated Cab",
                vendor="Generic", model="X", protocol="NTCIP_1202",
                ip_address="127.0.0.1", port=9,
                connection_status="NOT_CONNECTED",
            )
            db.add(controller)
            db.flush()
            db.add(SignalPhase(
                controller_id=controller.id, phase_number=2, ring=1, barrier=1,
                name="NB", min_green=7, max_green=65, conflicting_phases=[4],
            ))

            now = _naive(datetime.now(timezone.utc))
            for offset in range(12):
                db.add(TrafficObservation(
                    intersection_id=inter.id, lane_id=lane.id, source="radar",
                    timestamp=now - timedelta(minutes=offset),
                    vehicle_count=14, quality="FRESH",
                ))
            db.commit()
            db.refresh(inter)
        intersection_id = inter.id
    finally:
        db.close()

    # Measured demand: gated.
    gated = client.post("/api/v1/optimizer/recommend", headers=headers,
                        json={"intersection_id": intersection_id}).json()
    assert gated["status"] == "REFUSED"
    assert gated["reason"] == "TRUST_SCORE_BELOW_AI_GATE"
    assert gated["trust"]["band"] in ("UNTRUSTED", "UNRATED")
    assert "Enter volumes directly" in gated["remedy"]

    # Operator-entered volumes: not gated. A typed volume is the operator's own
    # assertion, and the platform has no business second-guessing it.
    entered = client.post("/api/v1/optimizer/recommend", headers=headers, json={
        "intersection_id": intersection_id,
        "movements": [
            {"phase_number": 2, "name": "NB", "volume_vph": 600, "lanes": 2},
            {"phase_number": 4, "name": "EB", "volume_vph": 400, "lanes": 1},
        ],
    }).json()
    assert entered["status"] == "COMPUTED"
    assert entered["trust"]["ai_gate_allowed"] in (True, False)
    assert "entered by the operator" in entered["trust"]["note"]


def test_structural_refusal_precedes_the_trust_gate(headers, bare_junction):
    """No amount of data quality fixes a missing lane-to-phase mapping."""
    response = client.post("/api/v1/optimizer/recommend", headers=headers,
                           json={"intersection_id": bare_junction})
    # No controller at all is a 400; the point is it is not a trust refusal.
    assert response.status_code == 400
    assert "no volumes were supplied" in response.json()["detail"]


# ===========================================================================
# Post-change verification
# ===========================================================================

def test_welch_reports_no_measurable_change_when_the_interval_spans_zero():
    """A bare mean comparison would call this an improvement half the time."""
    from app.analytics.verification import NO_MEASURABLE_CHANGE, welch_compare

    before = [30.0, 32.0, 28.0, 31.0, 29.0, 33.0, 27.0, 30.0, 31.0, 29.0]
    after = [29.0, 31.0, 30.0, 28.0, 32.0, 30.0, 29.0, 31.0, 30.0, 28.0]

    result = welch_compare(before, after, "avg_wait_time_sec")

    assert result.verdict == NO_MEASURABLE_CHANGE
    assert result.ci_low is not None and result.ci_high is not None
    assert result.ci_low <= 0.0 <= result.ci_high
    assert "contains zero" in result.explanation


def test_welch_detects_a_change_larger_than_the_noise():
    from app.analytics.verification import IMPROVED, welch_compare

    before = [45.0, 47.0, 44.0, 46.0, 45.0, 48.0, 43.0, 46.0, 45.0, 47.0]
    after = [28.0, 30.0, 27.0, 29.0, 28.0, 31.0, 26.0, 29.0, 28.0, 30.0]

    result = welch_compare(before, after, "avg_wait_time_sec")

    assert result.verdict == IMPROVED  # delay went down
    assert result.ci_high < 0.0, "The whole interval should be below zero"
    assert "excludes zero" in result.explanation


def test_welch_knows_which_direction_is_better():
    """Delay down is good; speed down is not."""
    from app.analytics.verification import DEGRADED, IMPROVED, welch_compare

    low = [10.0] * 5 + [11.0, 9.0, 10.5, 9.5, 10.2]
    high = [40.0] * 5 + [41.0, 39.0, 40.5, 39.5, 40.2]

    # Delay rising is a degradation.
    assert welch_compare(low, high, "avg_wait_time_sec").verdict == DEGRADED
    # Speed rising is an improvement.
    assert welch_compare(low, high, "avg_speed_kph").verdict == IMPROVED


def test_verification_refuses_a_verdict_on_too_few_samples():
    from app.analytics.verification import INSUFFICIENT_DATA, MIN_SAMPLES_PER_SIDE, welch_compare

    result = welch_compare([30.0, 31.0, 29.0], [28.0, 27.0, 29.0], "avg_wait_time_sec")

    assert result.verdict == INSUFFICIENT_DATA
    assert result.ci_low is None
    assert str(MIN_SAMPLES_PER_SIDE) in result.explanation
    assert "lack the power" in result.explanation


def test_verification_of_a_junction_with_no_telemetry_is_not_no_effect(headers, bare_junction):
    """'We could not measure it' is a different claim from 'it did nothing'."""
    changed_at = datetime.now(timezone.utc) - timedelta(hours=1)
    # Passed through `params` rather than interpolated: an ISO timestamp carries
    # a "+00:00" offset, and a bare "+" in a query string decodes as a space.
    response = client.get(
        "/api/v1/verification/window/{}".format(bare_junction),
        params={"changed_at": changed_at.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    assert body["overall_verdict"] == "INSUFFICIENT_DATA"
    assert "not evidence the change had no effect" in body["detail"]


def test_verification_states_its_method_and_caveats(headers, equipped_junction):
    changed_at = datetime.now(timezone.utc) - timedelta(minutes=45)
    response = client.get(
        "/api/v1/verification/window/{}".format(equipped_junction),
        params={"changed_at": changed_at.isoformat()},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    if body["status"] == "COMPUTED":
        assert "Welch" in body["method"]
        assert len(body["method_caveats"]) >= 3
        assert any("Demand is not controlled for" in c for c in body["method_caveats"])


def test_verification_of_a_rejected_command_is_not_applicable(headers, equipped_junction):
    """A command that never reached the hardware has nothing to verify."""
    db = SessionLocal()
    try:
        controller = (
            db.query(SignalController)
            .filter(SignalController.intersection_id == equipped_junction)
            .first()
        )
        controller_id = controller.id
    finally:
        db.close()

    rejected = client.post("/api/v1/signals/commands", headers=headers, json={
        "controller_id": controller_id,
        "requested_phase": 4,          # conflicts with the active phase 2
        "duration_sec": 15,
        "idempotency_key": "p3-verify-rejected",
    }).json()

    body = client.get(
        "/api/v1/verification/command/{}".format(rejected["command_id"]), headers=headers
    ).json()

    assert body["status"] == "NOT_APPLICABLE"
    assert "nothing reached the hardware" in body["detail"]


# ===========================================================================
# Stringline
# ===========================================================================

@pytest.fixture
def corridor_with_logs():
    """A corridor of two junctions with observed, offset green intervals."""
    db = SessionLocal()
    try:
        corridor = db.query(Corridor).filter(Corridor.name == "P3 Test Corridor").first()
        if corridor:
            return corridor.id

        corridor = Corridor(
            name="P3 Test Corridor", description="Stringline fixture",
            coordination_mode="GREEN_WAVE", cycle_length_sec=90,
        )
        db.add(corridor)
        db.flush()

        base = _naive(datetime.now(timezone.utc)) - timedelta(minutes=5)

        for index, (lat, lng, code, offset_sec) in enumerate([
            (11.4000, 76.4000, "P3-C1", 0),
            (11.4045, 76.4000, "P3-C2", 20),   # ~500 m north, 20 s downstream
        ]):
            inter = Intersection(
                name="P3 Corridor {}".format(index + 1), code=code,
                latitude=lat, longitude=lng, operational_status="HEALTHY",
                corridor_id=corridor.id,
            )
            db.add(inter)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="Cab {}".format(index + 1),
                vendor="Emulator", model="NTCIP-1202", protocol="NTCIP_1202",
                ip_address="127.0.0.1", port=9, connection_status="CONNECTED",
            )
            db.add(controller)
            db.flush()

            # 90 s cycle: phase 2 green for the first 40 s, sampled every 5 s.
            for tick in range(60):
                timestamp = base + timedelta(seconds=tick * 5)
                position_in_cycle = (tick * 5 - offset_sec) % 90
                greens = [2, 6] if 0 <= position_in_cycle < 40 else [4, 8]
                db.add(SignalStateLog(
                    controller_id=controller.id, intersection_id=inter.id,
                    timestamp=timestamp, green_phases=greens,
                    yellow_phases=[], red_phases=[],
                    source="NTCIP_1202_POLL", read_latency_ms=2.0,
                ))

        db.commit()
        db.refresh(corridor)
        return corridor.id
    finally:
        db.close()


def test_stringline_builds_bands_from_observed_state(headers, corridor_with_logs):
    body = client.get(
        "/api/v1/stringline/{}?minutes=10".format(corridor_with_logs), headers=headers
    ).json()

    assert body["status"] == "COMPUTED"
    assert body["junction_count"] == 2
    assert body["junctions_with_observations"] == 2
    assert body["corridor_length_m"] > 0

    for junction in body["junctions"]:
        assert junction["bands"], "Each junction should have observed green bands"
        # Edge uncertainty is carried, not hidden.
        assert junction["edge_uncertainty_sec"] is not None
        for band in junction["bands"]:
            assert band["start"] < band["end"] or band["duration_sec"] >= 0

    assert "not from a timing plan" in body["data_basis"]
    assert "Straight-line" in body["distance_basis"]


def test_stringline_refuses_a_speed_from_a_sub_resolution_offset(headers):
    """Dividing a real distance by an unmeasurable offset is not a measurement."""
    db = SessionLocal()
    try:
        corridor = db.query(Corridor).filter(Corridor.name == "P3 Sync Corridor").first()
        if not corridor:
            corridor = Corridor(name="P3 Sync Corridor", coordination_mode="GREEN_WAVE")
            db.add(corridor)
            db.flush()

            base = _naive(datetime.now(timezone.utc)) - timedelta(minutes=3)
            for index, (lat, lng, code) in enumerate([
                (11.5000, 76.5000, "P3-S1"),
                (11.5040, 76.5000, "P3-S2"),
            ]):
                inter = Intersection(
                    name="P3 Sync {}".format(index + 1), code=code,
                    latitude=lat, longitude=lng, corridor_id=corridor.id,
                    operational_status="HEALTHY",
                )
                db.add(inter)
                db.flush()
                controller = SignalController(
                    intersection_id=inter.id, name="Sync cab {}".format(index),
                    vendor="E", model="M", protocol="NTCIP_1202",
                    ip_address="127.0.0.1", port=9, connection_status="CONNECTED",
                )
                db.add(controller)
                db.flush()

                # Identical timing at both junctions: offset is exactly zero.
                for tick in range(40):
                    timestamp = base + timedelta(seconds=tick * 5)
                    greens = [2, 6] if (tick * 5) % 90 < 40 else [4, 8]
                    db.add(SignalStateLog(
                        controller_id=controller.id, intersection_id=inter.id,
                        timestamp=timestamp, green_phases=greens,
                        yellow_phases=[], red_phases=[],
                        source="NTCIP_1202_POLL",
                    ))
            db.commit()
            db.refresh(corridor)
        corridor_id = corridor.id
    finally:
        db.close()

    body = client.get(
        "/api/v1/stringline/{}?minutes=10".format(corridor_id), headers=headers
    ).json()

    segment = body["progression"]["segments"][0]
    assert segment["status"] == "OFFSET_BELOW_MEASUREMENT_RESOLUTION"
    assert segment["implied_progression_speed_kph"] is None
    assert "cannot be distinguished from zero" in segment["detail"]
    assert "artefact of the division" in body["progression"]["resolution_note"]


def test_stringline_needs_two_junctions(headers):
    db = SessionLocal()
    try:
        corridor = db.query(Corridor).filter(Corridor.name == "P3 Lonely Corridor").first()
        if not corridor:
            corridor = Corridor(name="P3 Lonely Corridor", coordination_mode="UNCOORDINATED")
            db.add(corridor)
            db.commit()
            db.refresh(corridor)
        corridor_id = corridor.id
    finally:
        db.close()

    body = client.get("/api/v1/stringline/{}".format(corridor_id), headers=headers).json()
    assert body["status"] == "NOT_COMPUTABLE"
    assert "at least two junctions" in body["detail"]


# ===========================================================================
# Shift handover
# ===========================================================================

def test_handover_preview_stores_nothing(headers):
    db = SessionLocal()
    before = db.query(ShiftHandover).count()
    db.close()

    body = client.get("/api/v1/handover/preview?shift_hours=8", headers=headers).json()

    db = SessionLocal()
    after = db.query(ShiftHandover).count()
    db.close()

    assert after == before
    assert body["preview"] is True
    assert "snapshot" in body


def test_handover_lists_blind_spots_as_a_first_class_section(headers, bare_junction):
    """The junction nobody was measuring is the thing to hand over."""
    body = client.get("/api/v1/handover/preview?shift_hours=8", headers=headers).json()
    blind = body["snapshot"]["blind_spots"]

    assert "count" in blind
    assert "why_this_matters" in blind
    assert "not that nothing happened" in blind["why_this_matters"]

    if blind["count"]:
        entry = blind["items"][0]
        assert entry["reasons"], "Each blind spot names why it was blind"


def test_a_junction_watched_on_one_channel_is_partial_not_unseen(
    headers, bare_junction, equipped_junction
):
    """Filing "no loops fitted" alongside "went dark" makes the section cry wolf.

    An operator who learns that a blind spot usually means missing detectors
    will skim past the junction that actually stopped reporting.
    """
    blind = client.get(
        "/api/v1/handover/preview?shift_hours=8", headers=headers
    ).json()["snapshot"]["blind_spots"]

    assert blind["total_blind_count"] + blind["partially_blind_count"] == blind["count"]

    by_id = {item["intersection_id"]: item for item in blind["items"]}

    # Nothing attached at all: genuinely unseen.
    assert by_id[bare_junction]["severity"] == "TOTAL"
    assert by_id[bare_junction]["observed_channels"] == []

    # Controller polled all shift, no detectors: partial, and the section says
    # which channel did report rather than implying nothing was known.
    equipped = by_id.get(equipped_junction)
    if equipped:
        assert equipped["severity"] == "PARTIAL"
        assert "signal state" in equipped["observed_channels"]
        assert equipped["signal_readings_this_shift"] > 0

    assert "not observed at all" in blind["why_this_matters"]
    assert "partial coverage" in blind["why_this_matters"]


def test_coverage_actions_separate_unseen_from_partial(headers, bare_junction, equipped_junction):
    """Only one of the two is urgent, so they are raised as separate items."""
    created = client.post("/api/v1/handover", headers=headers,
                          json={"shift_hours": 8}).json()
    kinds = {a["kind"] for a in created["pending_actions"]}

    snapshot = created["generated_snapshot"]["blind_spots"]
    if snapshot["total_blind_count"]:
        assert "DATA_COVERAGE_TOTAL_BLIND" in kinds
        total_item = next(
            a for a in created["pending_actions"]
            if a["kind"] == "DATA_COVERAGE_TOTAL_BLIND"
        )
        assert "not observed at all" in total_item["summary"]
    if snapshot["partially_blind_count"]:
        assert "DATA_COVERAGE_PARTIAL" in kinds
        partial_item = next(
            a for a in created["pending_actions"]
            if a["kind"] == "DATA_COVERAGE_PARTIAL"
        )
        assert "partial coverage" in partial_item["summary"]
        # The partial item must not claim the junctions went unobserved.
        assert "not observed at all" not in partial_item["summary"]


def test_handover_seeds_pending_actions_from_real_state(headers, bare_junction):
    created = client.post("/api/v1/handover", headers=headers,
                          json={"shift_hours": 8}).json()

    assert created["status"] == "DRAFT"
    assert created["editable"] is True

    # Auto-generated items are distinguishable from operator-added ones.
    for action in created["pending_actions"]:
        assert action["source"] in ("AUTO_GENERATED", "OPERATOR")
        assert action["summary"]


def test_editing_a_handover_never_touches_the_generated_snapshot(headers):
    created = client.post("/api/v1/handover", headers=headers,
                          json={"shift_hours": 8}).json()
    original_snapshot = created["generated_snapshot"]

    edited = client.patch(
        "/api/v1/handover/{}".format(created["id"]), headers=headers,
        json={"operator_notes": "Crew dispatched at 14:20."},
    ).json()

    assert edited["operator_notes"] == "Crew dispatched at 14:20."
    assert edited["generated_snapshot"] == original_snapshot


def test_signed_off_handover_cannot_be_revised(headers):
    """A handover the next shift has acted on is not a draft."""
    created = client.post("/api/v1/handover", headers=headers,
                          json={"shift_hours": 8}).json()

    signed = client.post(
        "/api/v1/handover/{}/sign-off".format(created["id"]), headers=headers
    ).json()
    assert signed["status"] == "SIGNED_OFF"
    assert signed["editable"] is False
    assert signed["signed_off_by"]

    blocked = client.patch(
        "/api/v1/handover/{}".format(created["id"]), headers=headers,
        json={"operator_notes": "rewriting history"},
    )
    assert blocked.status_code == 409
    assert "cannot be revised" in blocked.json()["detail"]


def test_a_draft_cannot_be_acknowledged(headers):
    """The incoming operator acknowledges a finished handover, not a draft."""
    created = client.post("/api/v1/handover", headers=headers,
                          json={"shift_hours": 8}).json()

    response = client.post(
        "/api/v1/handover/{}/acknowledge".format(created["id"]), headers=headers
    )
    assert response.status_code == 409
    assert "still a draft" in response.json()["detail"]


def test_handover_snapshot_reports_unprobed_providers_distinctly(headers):
    body = client.get("/api/v1/handover/preview?shift_hours=8", headers=headers).json()
    providers = body["snapshot"]["providers"]

    assert "degraded_count" in providers
    assert "unprobed_count" in providers
    if providers["unprobed_count"]:
        assert "not the same as working" in providers["unprobed_note"]
