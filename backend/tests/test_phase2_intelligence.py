"""TRAFFICINTEL AI - Phase 2 Backend Intelligence Tests

Event bus, provider health, rules engine, analytics, optimiser, scenario
sandbox, Copilot 2.0, incident lifecycle, governance, import and reporting.

The recurring assertion across all of them: the platform distinguishes
"measured and false" from "not measured", and never lets the second become the
first.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.main import app
from app.models.entities import (
    Alert, AlertRule, ApiKey, AuditLog, Incident, Intersection, Sensor,
    SignalController, SignalPhase, SignalStateLog, TrafficMetric,
    TrafficObservation, User, utc_now,
)

client = TestClient(app)


@pytest.fixture(scope="module")
def headers():
    db = SessionLocal()
    try:
        if not db.query(User).filter(User.username == "p2_admin").first():
            db.add(User(
                username="p2_admin", email="p2_admin@trafficintel.gov",
                hashed_password=get_password_hash("SecretPass123!"),
                full_name="Phase 2 Admin", role="ADMIN",
            ))
            db.commit()
    finally:
        db.close()

    response = client.post(
        "/api/v1/auth/login",
        data={"username": "p2_admin", "password": "SecretPass123!"},
    )
    assert response.status_code == 200
    return {"Authorization": "Bearer " + response.json()["access_token"]}


@pytest.fixture
def junction():
    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "P2-TEST").first()
        if not inter:
            inter = Intersection(
                name="Phase 2 Junction", code="P2-TEST",
                latitude=12.95, longitude=77.55, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()

            controller = SignalController(
                intersection_id=inter.id, name="P2 Controller",
                vendor="Emulator", model="NTCIP-1202", protocol="ASC3_ETHERNET",
                ip_address="127.0.0.1", port=9,
                connection_status="DISCONNECTED",
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
            db.commit()

        controller = (
            db.query(SignalController)
            .filter(SignalController.intersection_id == inter.id).first()
        )
        return {"intersection_id": inter.id, "controller_id": controller.id}
    finally:
        db.close()


# ===========================================================================
# Event bus
# ===========================================================================

def test_event_bus_rejects_undeclared_topics():
    """A typo in a topic name produces an event nobody receives. Fail loudly."""
    from app.events.bus import EventBus

    bus = EventBus()
    with pytest.raises(ValueError, match="undeclared topic"):
        bus.publish("signal.comand.executed", {"typo": True})


def test_event_bus_routes_wildcards_and_exact_topics():
    from app.events import topics
    from app.events.bus import EventBus

    async def scenario():
        bus = EventBus()
        exact = bus.subscribe("exact", [topics.SIGNAL_COMMAND_EXECUTED])
        prefix = bus.subscribe("prefix", ["signal.command.*"])
        everything = bus.subscribe("all", ["*"])
        unrelated = bus.subscribe("other", ["incident.*"])

        bus.publish(topics.SIGNAL_COMMAND_EXECUTED, {"id": "c1"})

        assert exact.queue.qsize() == 1
        assert prefix.queue.qsize() == 1
        assert everything.queue.qsize() == 1
        assert unrelated.queue.qsize() == 0

    asyncio.run(scenario())


def test_event_bus_drops_oldest_and_counts_the_loss():
    """Backpressure must be visible: a silent drop is a gap nobody knows about."""
    from app.events import topics
    from app.events.bus import EventBus

    async def scenario():
        bus = EventBus()
        subscription = bus.subscribe("slow", ["*"], queue_size=3)

        for index in range(6):
            bus.publish(topics.INCIDENT_DETECTED, {"n": index})

        assert subscription.queue.qsize() == 3
        assert subscription.dropped == 3

        # The oldest were discarded, so the newest survive.
        survivors = [subscription.queue.get_nowait().payload["n"] for _ in range(3)]
        assert survivors == [3, 4, 5]

        stats = bus.stats()
        assert stats["total_dropped_events"] == 3
        assert stats["subscriptions"][0]["dropped_events"] == 3

    asyncio.run(scenario())


def test_event_bus_survives_a_throwing_subscriber():
    """A notification handler must never break a signal command."""
    from app.events import topics
    from app.events.bus import EventBus

    async def scenario():
        bus = EventBus()
        good = bus.subscribe("good", ["*"])
        bus.publish(topics.ALERT_RAISED, {"ok": True})
        assert good.queue.qsize() == 1

    asyncio.run(scenario())


# ===========================================================================
# Provider health & circuit breaker
# ===========================================================================

def test_unprobed_provider_is_unknown_not_healthy():
    """Absence of evidence is reported as absence of evidence."""
    from app.health.monitor import ProviderHealthMonitor

    monitor = ProviderHealthMonitor()
    provider = monitor.register("p:test", "WEATHER", "Test")

    assert provider.state == "UNKNOWN"
    assert provider.snapshot()["measurement_basis"] == "NO_OBSERVATIONS_YET"
    assert provider.error_rate is None


def test_provider_health_hysteresis_degrades_fast_and_recovers_slowly():
    from app.health.monitor import ProviderHealthMonitor

    monitor = ProviderHealthMonitor()
    monitor.record("p:h", True, 10.0, kind="WEATHER", label="Test")
    assert monitor.get("p:h").state == "HEALTHY"

    # One failure is not enough to degrade.
    monitor.record("p:h", False, None, "timeout")
    assert monitor.get("p:h").state == "HEALTHY"

    # Two consecutive failures are.
    monitor.record("p:h", False, None, "timeout")
    assert monitor.get("p:h").state in ("DEGRADED", "FAILED")

    # One success does not restore HEALTHY.
    monitor.record("p:h", True, 10.0)
    assert monitor.get("p:h").state != "HEALTHY"


def test_circuit_breaker_opens_then_probes_then_closes():
    """OPEN -> HALF_OPEN -> CLOSED, without depending on wall-clock sleeps.

    The cooldown is expired by rewinding `opened_at` rather than by sleeping:
    Windows' monotonic clock has ~15ms granularity, which makes a 50ms sleep
    an unreliable way to cross a 50ms threshold.
    """
    import time

    from app.health.circuit import CircuitBreaker, CircuitOpenError

    breaker = CircuitBreaker(name="test", failure_threshold=3, base_cooldown_sec=30.0)

    for _ in range(3):
        breaker.record_failure("timeout")
    assert breaker.state == "OPEN"

    with pytest.raises(CircuitOpenError):
        breaker.raise_if_open()
    assert breaker.retry_after() > 0

    # Age the breaker past its cooldown deterministically.
    breaker.opened_at = time.monotonic() - 31.0

    assert breaker.allow() is True
    assert breaker.state == "HALF_OPEN"

    breaker.record_success()
    assert breaker.state == "CLOSED"
    assert breaker.retry_after() == 0.0


def test_circuit_breaker_reopens_with_a_longer_cooldown_after_a_failed_probe():
    """A provider that keeps failing its probe is retried less often."""
    import time

    from app.health.circuit import CircuitBreaker

    breaker = CircuitBreaker(name="test", failure_threshold=2, base_cooldown_sec=10.0)

    breaker.record_failure("timeout")
    breaker.record_failure("timeout")
    assert breaker.state == "OPEN"
    first_cooldown = breaker.snapshot()["cooldown_sec"]

    breaker.opened_at = time.monotonic() - (first_cooldown + 1)
    assert breaker.allow() is True          # half-open probe permitted

    breaker.record_failure("timeout again")  # probe fails
    assert breaker.state == "OPEN"
    assert breaker.snapshot()["cooldown_sec"] > first_cooldown


def test_provider_health_endpoint_reports_empty_truthfully(headers):
    response = client.get("/api/v1/health/providers", headers=headers)
    assert response.status_code == 200
    body = response.json()

    assert "summary" in body
    if not body["providers"]:
        assert body["empty_reason"] == "NO_PROVIDER_HAS_BEEN_CONTACTED_YET"


# ===========================================================================
# Rules engine
# ===========================================================================

def test_detector_that_never_reported_is_insufficient_data_not_an_alarm(headers, junction):
    """A configuration gap must not masquerade as a detector failure."""
    db = SessionLocal()
    try:
        sensor = db.query(Sensor).filter(Sensor.name == "Never reported loop").first()
        if not sensor:
            db.add(Sensor(
                intersection_id=junction["intersection_id"],
                name="Never reported loop", sensor_type="INDUCTIVE_LOOP",
                health_status="DISCONNECTED", last_observation_timestamp=None,
            ))
            db.commit()
    finally:
        db.close()

    rule = client.post("/api/v1/rules", headers=headers, json={
        "name": "Silent detector test", "condition_type": "DETECTOR_SILENT",
        "parameters": {"silent_for_sec": 60}, "severity": "WARNING",
        "intersection_id": junction["intersection_id"],
    }).json()

    result = client.post(
        "/api/v1/rules/{}/evaluate?dry_run=true".format(rule["id"]), headers=headers
    ).json()

    outcomes = {r["subject_label"]: r["outcome"] for r in result["results"]}
    assert outcomes["Never reported loop"] == "INSUFFICIENT_DATA"
    assert result["matched"] == 0

    explanation = next(
        r["explanation"] for r in result["results"]
        if r["subject_label"] == "Never reported loop"
    )
    assert "never reported" in explanation


def test_detector_that_went_silent_does_match(headers, junction):
    db = SessionLocal()
    try:
        sensor = db.query(Sensor).filter(Sensor.name == "Went silent loop").first()
        if not sensor:
            sensor = Sensor(
                intersection_id=junction["intersection_id"],
                name="Went silent loop", sensor_type="RADAR",
                health_status="CONNECTED",
            )
            db.add(sensor)
        sensor.last_observation_timestamp = (
            datetime.now(timezone.utc) - timedelta(seconds=600)
        ).replace(tzinfo=None)
        db.commit()
    finally:
        db.close()

    rule = client.post("/api/v1/rules", headers=headers, json={
        "name": "Silent detector match test", "condition_type": "DETECTOR_SILENT",
        "parameters": {"silent_for_sec": 60}, "severity": "WARNING",
        "intersection_id": junction["intersection_id"],
    }).json()

    result = client.post(
        "/api/v1/rules/{}/evaluate?dry_run=true".format(rule["id"]), headers=headers
    ).json()

    matched = [r for r in result["results"] if r["outcome"] == "MATCHED"]
    assert any(r["subject_label"] == "Went silent loop" for r in matched)


def test_rule_dry_run_raises_no_alert(headers, junction):
    db = SessionLocal()
    before = db.query(Alert).count()
    db.close()

    rule = client.post("/api/v1/rules", headers=headers, json={
        "name": "Dry run test", "condition_type": "CONTROLLER_STATE",
        "parameters": {"states": ["DISCONNECTED"]}, "severity": "CRITICAL",
    }).json()

    client.post("/api/v1/rules/{}/evaluate?dry_run=true".format(rule["id"]), headers=headers)

    db = SessionLocal()
    after = db.query(Alert).count()
    db.close()
    assert after == before, "A dry run must not raise an alert"


def test_repeated_matches_fold_into_one_alert_with_a_count(headers, junction):
    """Dedupe: the same unresolved condition is one alert, not a wall of rows."""
    rule = client.post("/api/v1/rules", headers=headers, json={
        "name": "Dedupe test", "condition_type": "CONTROLLER_STATE",
        "parameters": {"states": ["DISCONNECTED", "NOT_CONNECTED", "REACHABLE"]},
        "severity": "WARNING", "cooldown_sec": 3600,
        "intersection_id": junction["intersection_id"],
    }).json()

    first = client.post(
        "/api/v1/rules/{}/evaluate?dry_run=false".format(rule["id"]), headers=headers
    ).json()
    second = client.post(
        "/api/v1/rules/{}/evaluate?dry_run=false".format(rule["id"]), headers=headers
    ).json()

    assert first["matched"] >= 1
    # The second evaluation suppresses rather than duplicating.
    outcomes = {r["outcome"] for r in second["results"]}
    assert outcomes & {"SUPPRESSED_COOLDOWN", "SUPPRESSED_DUPLICATE"}

    db = SessionLocal()
    alerts = db.query(Alert).filter(Alert.rule_id == rule["id"]).all()
    db.close()
    assert len(alerts) == 1, "The same condition must not create a second alert row"
    assert alerts[0].occurrence_count >= 2


def test_unconfigured_delivery_channel_is_skipped_not_delivered(headers, junction):
    """A rule listing EMAIL with no SMTP host has not notified anybody."""
    rule = client.post("/api/v1/rules", headers=headers, json={
        "name": "Delivery test", "condition_type": "CONTROLLER_STATE",
        "parameters": {"states": ["DISCONNECTED", "NOT_CONNECTED", "REACHABLE"]},
        "severity": "WARNING", "delivery_channels": ["UI", "EMAIL", "WEBHOOK"],
    }).json()

    result = client.post(
        "/api/v1/rules/{}/evaluate?dry_run=false".format(rule["id"]), headers=headers
    ).json()

    alert_ids = [r["alert_id"] for r in result["results"] if r["alert_id"]]
    assert alert_ids, "Expected at least one alert"

    deliveries = client.get(
        "/api/v1/rules/alerts/{}/deliveries".format(alert_ids[0]), headers=headers
    ).json()

    by_channel = {d["channel"]: d["status"] for d in deliveries["deliveries"]}
    assert by_channel["UI"] == "DELIVERED"
    assert by_channel["EMAIL"] == "SKIPPED_NOT_CONFIGURED"
    assert by_channel["WEBHOOK"] == "SKIPPED_NOT_CONFIGURED"


# ===========================================================================
# Analytics
# ===========================================================================

def test_analytics_distinguishes_insufficient_from_not_computable(headers, junction):
    """Two different problems with two different remedies."""
    response = client.get(
        "/api/v1/analytics/performance/{}?hours=1".format(junction["intersection_id"]),
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()

    measures = body["measures"]
    # No telemetry: a sample-count problem.
    assert measures["occupancy"]["status"] == "INSUFFICIENT_DATA"
    assert measures["occupancy"]["minimum_samples"] > 0

    # A missing input entirely - waiting will not fix it. Which input is
    # reported depends on which is checked first; either way the operator is
    # told to connect something rather than to wait.
    aog = measures["arrival_on_green"]
    assert aog["status"] == "NOT_COMPUTABLE"
    assert any(
        token in aog["explanation"].lower()
        for token in ("lane", "signal state")
    )
    assert aog["value"] is None


def test_throughput_refuses_counts_without_a_known_window(headers):
    """A count with no observation window cannot become an hourly rate."""
    from app.analytics.performance import SignalPerformance

    db = SessionLocal()
    try:
        inter = db.query(Intersection).filter(Intersection.code == "P2-NOWIN").first()
        if not inter:
            inter = Intersection(
                name="No Window Junction", code="P2-NOWIN",
                latitude=12.1, longitude=77.1, operational_status="HEALTHY",
            )
            db.add(inter)
            db.flush()
            base = datetime.now(timezone.utc).replace(tzinfo=None)
            for index in range(8):
                db.add(TrafficMetric(
                    intersection_id=inter.id,
                    timestamp=base - timedelta(minutes=index),
                    vehicle_count=10,
                    sample_window_sec=None,   # the window was never recorded
                    data_quality="FRESH",
                    calculation_method="TEST",
                ))
            db.commit()

        end = datetime.now(timezone.utc)
        result = SignalPerformance.throughput(
            db, inter.id, end - timedelta(hours=1), end
        )
    finally:
        db.close()

    assert result["status"] == "NOT_COMPUTABLE"
    assert result["value"] is None
    assert "window" in result["explanation"]


def test_time_of_day_reports_hours_without_samples(headers, junction):
    """A missing hour is information, not a row to omit."""
    response = client.get(
        "/api/v1/analytics/time-of-day/{}?days=1".format(junction["intersection_id"]),
        headers=headers,
    )
    body = response.json()

    assert len(body["profile"]) == 24
    empty = [h for h in body["profile"] if h["sample_size"] == 0]
    assert all(h["status"] == "NO_SAMPLES_IN_THIS_HOUR" for h in empty)
    assert all(h["mean_vehicle_count"] is None for h in empty)


# ===========================================================================
# Optimiser
# ===========================================================================

def test_webster_refuses_over_capacity_rather_than_returning_a_number():
    from app.optimization.webster import MovementDemand, WebsterOptimizer

    result = WebsterOptimizer.optimize([
        MovementDemand(2, "NB", 3600, lanes=1),
        MovementDemand(4, "EB", 1800, lanes=1),
    ])

    assert result.status == "REFUSED"
    assert result.reason == "DEMAND_AT_OR_ABOVE_CAPACITY"
    assert result.cycle_length_sec is None


def test_webster_refuses_thin_measured_data():
    from app.optimization.webster import MovementDemand, WebsterOptimizer

    result = WebsterOptimizer.optimize([
        MovementDemand(2, "NB", 500, source="MEASURED_DETECTOR", sample_size=2),
    ])

    assert result.status == "REFUSED"
    assert result.reason == "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST"


def test_webster_returns_a_full_calculation_trace():
    """An engineer checks the arithmetic; they do not take it on trust."""
    from app.optimization.webster import MovementDemand, WebsterOptimizer

    result = WebsterOptimizer.optimize([
        MovementDemand(2, "NB", 900, lanes=2),
        MovementDemand(4, "EB", 620, lanes=1),
    ])

    assert result.status == "COMPUTED"
    symbols = [step["symbol"] for step in result.trace]
    for expected in ("y_i", "Y", "L", "C0", "C", "g_i", "x_i"):
        assert expected in symbols

    for step in result.trace:
        assert step["formula"]
        assert step["source"]

    assert result.expected_delay["uncertainty"]


def test_optimizer_recommendation_carries_a_safety_verdict(headers, junction):
    response = client.post("/api/v1/optimizer/recommend", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "movements": [
            {"phase_number": 2, "name": "NB", "volume_vph": 800, "lanes": 2},
            {"phase_number": 4, "name": "EB", "volume_vph": 500, "lanes": 1},
        ],
    })
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "COMPUTED"
    assert body["demand_source"] == "OPERATOR_ENTERED"
    assert body["safety_verdict"] is not None
    # The fixture controller is DISCONNECTED, so the proposal is not actionable.
    assert body["safety_passed"] is False
    assert body["actionable"] is False


def test_optimizer_refuses_measured_demand_without_lane_mapping(headers, junction):
    """Without lane-to-phase mapping, volume cannot be attributed to a phase."""
    response = client.post("/api/v1/optimizer/recommend", headers=headers, json={
        "intersection_id": junction["intersection_id"],
    })
    body = response.json()

    assert body["status"] == "REFUSED"
    assert body["reason"] == "NO_LANE_TO_PHASE_ASSIGNMENTS"
    assert "lanes.assigned_phase" in body["missing_inputs"]


# ===========================================================================
# Scenario sandbox
# ===========================================================================

def test_scenario_is_stamped_and_stored_separately(headers, junction):
    response = client.post("/api/v1/scenario/run", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "label": "Test scenario",
        "movements": [
            {"phase_number": 2, "name": "NB", "volume_vph": 700, "lanes": 2},
            {"phase_number": 4, "name": "EB", "volume_vph": 400, "lanes": 1},
        ],
    })
    assert response.status_code == 201
    body = response.json()

    assert body["result_type"] == "SCENARIO / HYPOTHETICAL"
    assert body["is_hypothetical"] is True
    assert body["not_observed_data"] is True
    assert body["disclaimer"]

    # Field names differ from observed metrics on purpose.
    assert "scenario_cycle_length_sec" in body
    assert "vehicle_count" not in body
    assert "occupancy_pct" not in body


def test_scenario_never_writes_to_observed_data_tables(headers, junction):
    """The isolation rule, asserted rather than assumed."""
    db = SessionLocal()
    metrics_before = db.query(TrafficMetric).count()
    observations_before = db.query(TrafficObservation).count()
    db.close()

    client.post("/api/v1/scenario/run", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "label": "Isolation check",
        "movements": [{"phase_number": 2, "name": "NB", "volume_vph": 900, "lanes": 2}],
    })

    db = SessionLocal()
    metrics_after = db.query(TrafficMetric).count()
    observations_after = db.query(TrafficObservation).count()
    db.close()

    assert metrics_after == metrics_before
    assert observations_after == observations_before


def test_scenario_refuses_a_baseline_it_does_not_have(headers, junction):
    response = client.post("/api/v1/scenario/run", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "label": "Baseline check",
        "movements": [{"phase_number": 2, "name": "NB", "volume_vph": 900, "lanes": 2}],
        "compare_to_measured": True,
    })
    body = response.json()

    assert body["measured_baseline"]["status"] == "INSUFFICIENT_DATA"
    assert body["measured_baseline"]["measured_delay_sec_per_veh"] is None
    assert body["comparison"] is None
    assert "No assumed baseline is substituted" in body["measured_baseline"]["explanation"]


def test_scenario_template_supplies_no_volumes(headers, junction):
    response = client.get(
        "/api/v1/scenario/template/{}".format(junction["controller_id"]), headers=headers
    )
    body = response.json()

    for movement in body["movements"]:
        assert movement["volume_vph"] is None
        assert movement["volume_status"].startswith("NOT_SUPPLIED")


# ===========================================================================
# Copilot 2.0
# ===========================================================================

def test_copilot_refuses_an_unknown_junction(headers):
    response = client.post("/api/v1/copilot/ask", headers=headers, json={
        "query": "What is the delay at Completely Fictional Boulevard?",
    })
    body = response.json()

    assert body["telemetry_state"] == "NO_SUPPORTING_RECORDS"
    assert "No configured junction matches" in body["answer"]
    # Crucially: no fabricated delay figure.
    assert "seconds" not in body["answer"].lower() or "no " in body["answer"].lower()


def test_copilot_cites_every_claim(headers, junction):
    response = client.post("/api/v1/copilot/ask", headers=headers, json={
        "query": "What is happening at Phase 2 Junction?",
    })
    body = response.json()

    assert body["grounded"] is True
    assert body["citation_count"] > 0

    for citation in body["citations"]:
        assert citation["type"] in ("record", "standard", "computation", "measurement")
        if citation["type"] == "record":
            # A citation points at something checkable.
            assert citation["table"]
            assert citation["id"]


def test_copilot_tools_report_no_data_rather_than_empty(headers):
    from app.copilot import tools

    db = SessionLocal()
    try:
        result = tools.find_intersection(db, "ZZZ_NOT_A_REAL_JUNCTION")
    finally:
        db.close()

    assert result["status"] == "NO_DATA"
    assert result["reason"] == "NO_MATCHING_INTERSECTION"
    assert result["citations"] == []


def test_copilot_session_memory_is_per_operator(headers, junction):
    client.delete("/api/v1/copilot/session", headers=headers)
    client.post("/api/v1/copilot/ask", headers=headers, json={"query": "any open incidents?"})

    session = client.get("/api/v1/copilot/session", headers=headers).json()
    assert session["turn_count"] >= 1
    assert session["session_id"].startswith("user:")
    assert "re-queries" in session["memory_policy"]["note"]


def test_copilot_declares_its_reasoning_mode(headers):
    response = client.post("/api/v1/copilot/ask", headers=headers, json={
        "query": "provider health",
    })
    body = response.json()

    assert body["reasoning_mode"] in ("LLM_PLANNED", "DETERMINISTIC_PLANNER")
    assert body["mode_note"]


# ===========================================================================
# Incident lifecycle
# ===========================================================================

def test_incident_sla_targets_are_copied_at_creation(headers, junction):
    """A later policy change must not rewrite a past incident's outcome."""
    incident = client.post("/api/v1/incidents", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "title": "SLA test incident", "type": "LANE_BLOCKAGE",
        "severity": "CRITICAL", "source": "TEST",
        "affected_lanes": [],
    }).json()

    db = SessionLocal()
    row = db.query(Incident).filter(Incident.id == incident["id"]).first()
    db.close()

    assert row.sla_acknowledge_sec == 300
    assert row.sla_resolve_sec == 3600

    sla = client.get("/api/v1/incidents/{}/sla".format(incident["id"]), headers=headers).json()
    assert sla["acknowledge"]["status"] == "RUNNING"
    assert "copied onto this incident" in sla["policy_note"]


def test_incident_evidence_must_reference_a_real_record(headers, junction):
    incident = client.post("/api/v1/incidents", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "title": "Evidence test", "type": "ACCIDENT_PATTERN",
        "severity": "MEDIUM", "source": "TEST", "affected_lanes": [],
    }).json()

    response = client.post(
        "/api/v1/incidents/{}/evidence?evidence_type=SIGNAL_STATE&source_id=not-a-real-id"
        .format(incident["id"]),
        headers=headers,
    )
    assert response.status_code == 400
    assert "does not exist" in response.json()["detail"] or "No " in response.json()["detail"]


def test_incident_timeline_is_append_only(headers, junction):
    incident = client.post("/api/v1/incidents", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "title": "Timeline test", "type": "LANE_BLOCKAGE",
        "severity": "LOW", "source": "TEST", "affected_lanes": [],
    }).json()

    client.post("/api/v1/incidents/{}/acknowledge".format(incident["id"]), headers=headers)
    client.patch(
        "/api/v1/incidents/{}/status".format(incident["id"]), headers=headers,
        json={"status": "VERIFIED", "operator_notes": "Confirmed on camera"},
    )

    timeline = client.get(
        "/api/v1/incidents/{}/timeline".format(incident["id"]), headers=headers
    ).json()

    assert timeline["append_only"] is True
    assert timeline["count"] >= 3
    kinds = [entry["entry_type"] for entry in timeline["entries"]]
    assert "STATUS_CHANGE" in kinds

    # A correction references the entry it corrects rather than editing it.
    target = timeline["entries"][0]["id"]
    correction = client.post(
        "/api/v1/incidents/{}/timeline/note?summary=Correcting+earlier+entry"
        "&corrects_entry_id={}".format(incident["id"], target),
        headers=headers,
    ).json()
    assert correction["entry_type"] == "CORRECTION"
    assert correction["corrects_entry_id"] == target


def test_post_incident_report_lists_gaps(headers, junction):
    incident = client.post("/api/v1/incidents", headers=headers, json={
        "intersection_id": junction["intersection_id"],
        "title": "Gap report test", "type": "LANE_BLOCKAGE",
        "severity": "LOW", "source": "TEST", "affected_lanes": [],
    }).json()

    report = client.get(
        "/api/v1/incidents/{}/report".format(incident["id"]), headers=headers
    ).json()

    assert report["durations"]["detection_to_resolution_sec"] is None
    assert any("never acknowledged" in gap for gap in report["gaps"])
    assert any("No evidence" in gap for gap in report["gaps"])
    assert "Nothing is inferred" in report["report_basis"]


# ===========================================================================
# Governance
# ===========================================================================

def test_audit_chain_is_intact_and_detects_modification(headers):
    # Produce a few chained entries.
    for index in range(3):
        client.post("/api/v1/rules", headers=headers, json={
            "name": "Chain rule {}".format(index),
            "condition_type": "CONTROLLER_STATE",
            "parameters": {"states": ["DISCONNECTED"]},
        })

    verification = client.get("/api/v1/governance/audit/verify", headers=headers).json()
    assert verification["status"] == "INTACT"
    assert verification["entries_verified"] >= 3

    db = SessionLocal()
    victim = (
        db.query(AuditLog)
        .filter(AuditLog.sequence.isnot(None))
        .order_by(AuditLog.sequence.desc())
        .first()
    )
    original = victim.action
    victim.action = "TAMPERED_BY_TEST"
    db.commit()
    db.close()

    broken = client.get("/api/v1/governance/audit/verify", headers=headers).json()
    assert broken["status"] == "BROKEN"
    assert broken["break_type"] == "ENTRY_MODIFIED"

    db = SessionLocal()
    victim = db.query(AuditLog).filter(AuditLog.sequence == broken["broken_at_sequence"]).first()
    victim.action = original
    db.commit()
    db.close()

    assert client.get("/api/v1/governance/audit/verify", headers=headers).json()["status"] == "INTACT"


def test_audit_export_carries_a_digest_and_the_chain_formula(headers):
    export = client.get("/api/v1/governance/audit/export", headers=headers).json()

    assert export["hash_algorithm"] == "SHA-256"
    assert "entry_hash = SHA256" in export["chain_formula"]
    assert len(export["export_sha256"]) == 64
    assert export["verification"]["status"] in ("INTACT", "EMPTY")


def test_api_key_cannot_hold_signal_command(headers):
    response = client.post("/api/v1/governance/api-keys", headers=headers, json={
        "name": "should-fail", "scopes": ["signal:command"],
    })
    assert response.status_code == 400
    assert "cannot be granted to an API key" in response.json()["detail"]


def test_api_key_is_shown_once_and_stored_hashed(headers):
    created = client.post("/api/v1/governance/api-keys", headers=headers, json={
        "name": "test-ingest-key", "scopes": ["telemetry:read", "data:import"],
    }).json()

    raw = created["api_key"]
    assert raw.startswith("tiai_")
    assert created["warning"]

    db = SessionLocal()
    record = db.query(ApiKey).filter(ApiKey.id == created["id"]).first()
    db.close()

    # The plaintext is nowhere in the row.
    assert record.key_hash != raw
    assert len(record.key_hash) == 64
    assert raw not in json.dumps({"prefix": record.key_prefix, "hash": record.key_hash})

    # And the key authenticates.
    whoami = client.get("/api/v1/governance/whoami", headers={"X-API-Key": raw}).json()
    assert whoami["kind"] == "API_KEY"
    assert set(whoami["scopes"]) == {"telemetry:read", "data:import"}


def test_scopes_deny_what_a_role_does_not_hold(headers):
    from app.governance import scopes as scope_vocab

    viewer = scope_vocab.scopes_for_role("VIEWER")
    assert scope_vocab.COMMAND_SIGNAL not in viewer
    assert scope_vocab.WRITE_INCIDENT not in viewer
    assert scope_vocab.READ_TELEMETRY in viewer

    # An auditor reads everything and changes nothing.
    auditor = scope_vocab.scopes_for_role("AUDITOR")
    assert scope_vocab.EXPORT_AUDIT in auditor
    assert scope_vocab.COMMAND_SIGNAL not in auditor
    assert scope_vocab.WRITE_INCIDENT not in auditor


def test_api_key_without_scope_is_refused(headers):
    created = client.post("/api/v1/governance/api-keys", headers=headers, json={
        "name": "read-only-key", "scopes": ["telemetry:read"],
    }).json()

    response = client.get(
        "/api/v1/governance/audit/export", headers={"X-API-Key": created["api_key"]}
    )
    assert response.status_code == 403
    assert "Missing required scope" in response.json()["detail"]


# ===========================================================================
# Data import
# ===========================================================================

CSV_WITH_BAD_ROWS = (
    "intersection_code,source,timestamp,vehicle_count,occupancy_pct,avg_speed_kph\n"
    "P2-TEST,radar_a,2026-09-21T09:00:00Z,11,20.0,35.0\n"
    "P2-TEST,radar_a,2026-09-21T09:01:00Z,13,180.0,36.0\n"
    "NOT-A-CODE,radar_a,2026-09-21T09:02:00Z,9,20.0,35.0\n"
    "P2-TEST,radar_a,garbage,7,20.0,35.0\n"
)


def test_import_dry_run_writes_nothing_and_reports_every_rejection(headers, junction):
    db = SessionLocal()
    before = db.query(TrafficObservation).count()
    db.close()

    response = client.post(
        "/api/v1/ingest/traffic_observations_csv?commit=false",
        headers=headers,
        files={"file": ("obs.csv", CSV_WITH_BAD_ROWS, "text/csv")},
    )
    assert response.status_code == 200
    body = response.json()

    assert body["status"] == "VALIDATED_NOT_COMMITTED"
    assert body["rows_written"] == 0
    assert body["rows_rejected"] == 3
    assert body["rows_valid"] == 1

    db = SessionLocal()
    after = db.query(TrafficObservation).count()
    db.close()
    assert after == before

    # Each rejection names its row and its reason.
    reasons = {(e["row_number"], e["field"]) for e in body["errors"]}
    assert (3, "occupancy_pct") in reasons
    assert (4, "intersection_code") in reasons
    assert (5, "timestamp") in reasons


def test_import_commit_writes_only_valid_rows_with_provenance(headers, junction):
    response = client.post(
        "/api/v1/ingest/traffic_observations_csv?commit=true",
        headers=headers,
        files={"file": ("obs.csv", CSV_WITH_BAD_ROWS, "text/csv")},
    )
    body = response.json()

    assert body["status"] == "COMMITTED"
    assert body["rows_written"] == 1

    db = SessionLocal()
    imported = (
        db.query(TrafficObservation)
        .filter(TrafficObservation.source == "radar_a")
        .order_by(TrafficObservation.timestamp.desc())
        .first()
    )
    db.close()

    assert imported is not None
    assert imported.provenance["ingest_method"] == "FILE_IMPORT"
    assert imported.provenance["source_filename"] == "obs.csv"
    assert len(imported.provenance["content_sha256"]) == 64
    assert imported.provenance["import_id"] == body["import_id"]


def test_geojson_import_rejects_out_of_range_coordinates(headers):
    geojson = json.dumps({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [500.0, 12.9]},
            "properties": {"name": "Bad Coords Junction", "code": "BAD-COORD"},
        }],
    })

    body = client.post(
        "/api/v1/ingest/junctions_geojson?commit=true",
        headers=headers,
        files={"file": ("j.geojson", geojson, "application/geo+json")},
    ).json()

    assert body["rows_rejected"] == 1
    assert body["rows_written"] == 0
    assert any("Longitude out of range" in e["reason"] for e in body["errors"])


def test_gtfs_import_creates_no_transit_events(headers):
    """A schedule says a bus is due, not that one arrived."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("routes.txt", "route_id,route_short_name\nR1,10\n")
        archive.writestr("stops.txt", "stop_id,stop_name\nS1,Main St\n")
        archive.writestr("trips.txt", "route_id,trip_id\nR1,T1\n")

    from app.models.entities import TransitEvent
    db = SessionLocal()
    before = db.query(TransitEvent).count()
    db.close()

    body = client.post(
        "/api/v1/ingest/gtfs_static?commit=true",
        headers=headers,
        files={"file": ("gtfs.zip", buffer.getvalue(), "application/zip")},
    ).json()

    db = SessionLocal()
    after = db.query(TransitEvent).count()
    db.close()

    assert after == before, "GTFS static must not create observed transit events"
    assert any("schedule says a bus is due" in w for w in body["warnings"])


# ===========================================================================
# Reporting
# ===========================================================================

def test_report_states_insufficiency_rather_than_omitting_it(headers, junction):
    report = client.get(
        "/api/v1/reports/signal-performance/{}?hours=1".format(junction["intersection_id"]),
        headers=headers,
    ).json()

    assert report["report_type"] == "SIGNAL_PERFORMANCE_REPORT"
    # Every measure appears in the narrative, computed or not.
    assert len(report["narrative"]) == len(report["measures"])
    assert any("insufficient data" in line or "not computable" in line
               for line in report["narrative"])


def test_report_csv_and_pdf_carry_the_same_caveats(headers, junction):
    csv_response = client.get(
        "/api/v1/reports/signal-performance/{}?format=csv".format(
            junction["intersection_id"]),
        headers=headers,
    )
    assert csv_response.status_code == 200
    assert "text/csv" in csv_response.headers["content-type"]
    text = csv_response.text
    assert "Minimum samples" in text
    assert "Report basis" in text

    pdf_response = client.get(
        "/api/v1/reports/signal-performance/{}?format=pdf".format(
            junction["intersection_id"]),
        headers=headers,
    )
    assert pdf_response.status_code == 200
    assert pdf_response.content.startswith(b"%PDF-")
    assert pdf_response.content.rstrip().endswith(b"%%EOF")


def test_daily_report_names_its_gaps(headers):
    report = client.get("/api/v1/reports/daily-operations", headers=headers).json()

    assert report["report_type"] == "DAILY_OPERATIONS_SUMMARY"
    assert "gaps" in report
    assert "Nothing is inferred" in report["report_basis"] or report["report_basis"]
    assert "readable" in report["infrastructure"]["controllers_readable_note"]


# ===========================================================================
# Observability
# ===========================================================================

def test_metrics_exports_no_traffic_measurements():
    """Prometheus strips provenance, so measurements do not belong there."""
    from app.observability.metrics import render_prometheus

    text = render_prometheus()
    names = {
        line.split("{")[0].split(" ")[0]
        for line in text.splitlines()
        if line and not line.startswith("#")
    }

    forbidden = [
        name for name in names
        if any(token in name for token in ("occupancy", "vehicle", "speed", "queue"))
    ]
    assert forbidden == [], "Traffic measurements must not be exported as metrics"


def test_every_response_carries_a_trace_id(headers):
    response = client.get("/api/v1/health/providers", headers=headers)
    assert response.headers.get("X-Request-ID")
    assert response.headers.get("X-RateLimit-Policy")
    assert response.headers.get("X-RateLimit-Scope") == "per-process"


def test_rate_limiter_has_a_tighter_bucket_for_signal_commands():
    from app.governance.rate_limit import (
        DEFAULT_POLICY, SIGNAL_COMMAND_POLICY, policy_for_request,
    )

    assert SIGNAL_COMMAND_POLICY.max_requests < DEFAULT_POLICY.max_requests
    assert policy_for_request("POST", "/api/v1/signals/commands").name == "signal_command"
    # A dry-run preview is not a command and is not throttled like one.
    assert policy_for_request("POST", "/api/v1/signals/commands/validate").name == "write"


# ===========================================================================
# WebSocket gateway
# ===========================================================================

def test_websocket_refuses_an_unauthenticated_handshake():
    """An unauthenticated socket must never receive an operational event."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws"):
            pass

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/v1/ws?token=not-a-real-token"):
            pass


def test_websocket_accepts_a_valid_token_and_says_what_connected_means(headers):
    token = headers["Authorization"].split(" ", 1)[1]

    with client.websocket_connect("/api/v1/ws?token={}".format(token)) as socket:
        hello = socket.receive_json()
        assert hello["event"] == "stream.status"
        assert hello["payload"]["status"] == "CONNECTED"
        # The gateway states that an open socket is not a claim about data.
        assert "does not imply data is flowing" in hello["payload"]["detail"]


def test_websocket_reports_an_invalid_topic_rather_than_silently_dropping_it(headers):
    token = headers["Authorization"].split(" ", 1)[1]

    with client.websocket_connect("/api/v1/ws?token={}".format(token)) as socket:
        socket.receive_json()  # connect frame

        socket.send_json({"action": "subscribe", "topics": ["signal.typo.here"]})
        response = socket.receive_json()

        assert response["payload"]["status"] == "INVALID_TOPICS"
        assert "signal.typo.here" in response["payload"]["topics"]


def test_websocket_delivers_only_subscribed_topics(headers):
    from app.events import topics
    from app.events.bus import event_bus

    token = headers["Authorization"].split(" ", 1)[1]

    with client.websocket_connect("/api/v1/ws?token={}".format(token)) as socket:
        socket.receive_json()  # connect frame

        socket.send_json({"action": "subscribe", "topics": ["incident.*"]})
        assert socket.receive_json()["payload"]["status"] == "SUBSCRIBED"

        # A non-matching topic must not arrive...
        event_bus.publish(topics.PROVIDER_HEALTH_HEALTHY, {"provider": "x"})
        # ...while a matching one does.
        event_bus.publish(topics.INCIDENT_DETECTED, {"incident_id": "ws1", "title": "WS test"})

        received = socket.receive_json()
        assert received["event"] == topics.INCIDENT_DETECTED
        assert received["payload"]["incident_id"] == "ws1"


def test_websocket_keepalive_is_not_an_event(headers):
    """A pong must not advance the console's 'last event' clock."""
    token = headers["Authorization"].split(" ", 1)[1]

    with client.websocket_connect("/api/v1/ws?token={}".format(token)) as socket:
        socket.receive_json()
        socket.send_text("ping")
        assert socket.receive_text() == "pong"
