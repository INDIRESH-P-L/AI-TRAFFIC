"""TRAFFICINTEL AI - Grounded Intelligence Tests

Anomaly detection, short-horizon forecasting and fusion-based incident
detection.

Each feature produces a number an operator would act on, and each has a
specific way of producing a confident-looking number from nothing:

* an anomaly flag measured against a baseline too small to support it;
* a forecast line from a model nobody checked was better than guessing
  "same as last time";
* an incident raised by one faulty detector agreeing with itself.

These tests pin the refusals first and the positive cases second.

Test telemetry
--------------
The rows written here are TEST FIXTURES, created only inside the throwaway
test database. Their variation comes from `_jitter`, a SHA-256 of the key and
index mapped to a bounded range: deterministic, reproducible across runs and
platforms, and uncorrelated from one index to the next (unlike a sinusoid,
which an autoregressive model would simply learn).
"""

import hashlib
import math
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.analytics.anomaly import (
    MIN_BASELINE_SAMPLES, AnomalyDetector,
)
from app.analytics.forecasting import (
    MIN_SKILL_OVER_PERSISTENCE, ShortHorizonForecaster,
)
from app.analytics.stats import student_t_two_sided_p
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.incidents.fusion import IncidentFusionDetector
from app.main import app
from app.models.entities import (
    Approach, Incident, IncidentEvidence, IncidentTimelineEntry, Intersection,
    Lane, Sensor, SignalCommand, TrafficMetric, TrafficObservation, User,
)

client = TestClient(app)

#: A fixed evaluation instant, so no test depends on the wall clock. It sits on
#: a 15-minute boundary, which makes the forecaster's in-progress bin empty.
AS_OF = datetime(2026, 3, 10, 14, 0, 0)


def _jitter(key: str, index: int, amplitude: float) -> float:
    """Deterministic, index-uncorrelated variation in [-amplitude, amplitude)."""
    digest = hashlib.sha256("{}:{}".format(key, index).encode()).digest()
    unit = int.from_bytes(digest[:8], "big") / 2 ** 64
    return (unit - 0.5) * 2.0 * amplitude


def _junction(db, code: str) -> str:
    inter = Intersection(
        name="GI {}".format(code), code=code,
        latitude=12.0, longitude=77.0, operational_status="HEALTHY",
    )
    db.add(inter)
    db.commit()
    db.refresh(inter)
    return inter.id


def _metric(db, intersection_id, ts, flow=None, occupancy=None, speed=None, quality="FRESH"):
    db.add(TrafficMetric(
        intersection_id=intersection_id, timestamp=ts,
        flow_rate_vph=flow, occupancy_pct=occupancy, avg_speed_kph=speed,
        sample_window_sec=60.0, data_quality=quality,
        calculation_method="TEST_TELEMETRY",
    ))


def _samples(values, start: datetime, spacing: timedelta):
    return [
        (start + spacing * i, float(v), "row-{}".format(i), "FRESH")
        for i, v in enumerate(values)
    ]


@pytest.fixture(scope="module")
def headers():
    db = SessionLocal()
    try:
        for username, role in (("gi_admin", "ADMIN"), ("gi_viewer", "VIEWER"), ("gi_auditor", "AUDITOR")):
            if not db.query(User).filter(User.username == username).first():
                db.add(User(
                    username=username, email="{}@trafficintel.gov".format(username),
                    hashed_password=get_password_hash("SecretPass123!"),
                    full_name=username, role=role,
                ))
        db.commit()
    finally:
        db.close()

    tokens = {}
    for username in ("gi_admin", "gi_viewer", "gi_auditor"):
        response = client.post(
            "/api/v1/auth/login",
            data={"username": username, "password": "SecretPass123!"},
        )
        assert response.status_code == 200
        tokens[username] = {"Authorization": "Bearer " + response.json()["access_token"]}
    return tokens


# ===========================================================================
# Shared statistics
# ===========================================================================

def test_student_t_p_values_match_published_tables():
    """Anomaly confidence is 1 - p, so p must be a real p-value."""
    for t, df, expected in [(2.228, 10, 0.05), (12.706, 1, 0.05), (3.169, 10, 0.01), (2.042, 30, 0.05)]:
        assert abs(student_t_two_sided_p(t, df) - expected) < 5e-4


# ===========================================================================
# 1. Anomaly detection
# ===========================================================================

def test_a_metric_never_recorded_is_not_computable():
    """No speed sensor means no speed anomaly - and waiting will not change that."""
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-NOSPEED")
        for i in range(150):
            ts = AS_OF - timedelta(minutes=150 - i)
            _metric(db, jid, ts, flow=600 + _jitter("f", i, 40), occupancy=20 + _jitter("o", i, 3))
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    speed = next(m for m in result["metrics"] if m["metric"] == "avg_speed_kph")
    assert speed["status"] == "NOT_COMPUTABLE"
    assert speed["reason"] == "NO_STORED_VALUES_FOR_METRIC"
    assert "Waiting will not help" in speed["explanation"]
    # The overall verdict names what was not evaluated rather than implying calm.
    assert any("Average speed" in m for m in result["metrics_not_evaluated"])


def test_a_junction_with_no_telemetry_is_not_computable_overall():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-EMPTY")
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["status"] == "NOT_COMPUTABLE"
    assert all(m["status"] == "NOT_COMPUTABLE" for m in result["metrics"])


def test_a_small_baseline_is_insufficient_data_never_a_false_confident_flag():
    """An enormous reading against ten baseline samples is still not reported."""
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-SMALLBASE")
        for i in range(10):
            _metric(db, jid, AS_OF - timedelta(minutes=60 - i * 3), flow=600 + _jitter("s", i, 30))
        _metric(db, jid, AS_OF - timedelta(minutes=2), flow=5000)  # would be a huge outlier
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
    assert flow["status"] == "INSUFFICIENT_DATA"
    assert flow["reason"] == "BASELINE_TOO_SMALL"
    assert flow["minimum_baseline_samples"] == MIN_BASELINE_SAMPLES
    assert "flagged_points" not in flow
    assert result["status"] != "MEASURED_ANOMALY"


def test_nothing_recent_is_insufficient_data_not_normal():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-NORECENT")
        for i in range(100):
            _metric(db, jid, AS_OF - timedelta(hours=3) + timedelta(minutes=i), flow=600 + _jitter("r", i, 30))
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
    assert flow["status"] == "INSUFFICIENT_DATA"
    assert flow["reason"] == "NO_SAMPLES_IN_TEST_WINDOW"
    assert "not a finding that conditions are normal" in flow["explanation"]


def test_a_clear_spike_is_a_measured_anomaly_traceable_to_its_row():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-SPIKE")
        for i in range(135):  # 120 baseline + 15 in the test window
            ts = AS_OF - timedelta(minutes=134 - i)
            flow = 1500.0 if i == 130 else 600 + _jitter("spike", i, 40)
            _metric(db, jid, ts, flow=flow)
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)

        flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
        assert result["status"] == "MEASURED_ANOMALY"
        assert flow["status"] == "MEASURED_ANOMALY"
        assert len(flow["flagged_points"]) == 1

        point = flow["flagged_points"][0]
        assert point["direction"] == "HIGH"
        assert point["value"] == 1500.0
        assert point["confidence"] > 0.99
        # Provenance: the flag points at a row the platform actually stored.
        assert point["source_table"] == "traffic_metrics"
        assert db.query(TrafficMetric).filter(TrafficMetric.id == point["source_row_id"]).first()
    finally:
        db.close()

    assert result["data_kind"] == "MEASURED"


def test_ordinary_variation_raises_no_flag():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-CALM")
        for i in range(135):
            _metric(db, jid, AS_OF - timedelta(minutes=134 - i), flow=600 + _jitter("calm", i, 40))
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
    assert flow["status"] == "NO_ANOMALY"
    assert flow["flagged_points"] == []


def test_without_same_time_of_day_history_the_baseline_says_it_ignores_the_daily_pattern():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-RECENTMODE")
        for i in range(135):
            _metric(db, jid, AS_OF - timedelta(minutes=134 - i), flow=600 + _jitter("rm", i, 40))
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
    assert flow["baseline"]["mode"] == "RECENT_WINDOW"
    assert "does not account for the daily pattern" in flow["baseline"]["caveat"]


def test_same_time_of_day_history_is_preferred_when_it_exists():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-TOD")
        # Three previous days, twenty readings each around the test window's time of day.
        for day in range(1, 4):
            for i in range(20):
                ts = AS_OF - timedelta(days=day) - timedelta(minutes=25) + timedelta(minutes=i * 2.5)
                _metric(db, jid, ts, flow=600 + _jitter("tod{}".format(day), i, 40))
        for i in range(15):
            _metric(db, jid, AS_OF - timedelta(minutes=14 - i), flow=600 + _jitter("todnow", i, 40))
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()

    flow = next(m for m in result["metrics"] if m["metric"] == "flow_rate_vph")
    assert flow["baseline"]["mode"] == "SAME_TIME_OF_DAY"
    assert flow["baseline"]["sample_size"] == 60


def test_confidence_is_lower_when_the_baseline_is_smaller():
    """The same deviation earns less confidence from less history."""
    test_start = AS_OF - timedelta(minutes=15)

    def run(n):
        pattern = [10.0, 14.0] * (n // 2)                       # mean 12, sd ~2
        spacing = timedelta(minutes=90) / n
        baseline = _samples(pattern, test_start - spacing * n, spacing)
        test = [(AS_OF - timedelta(minutes=5), 20.0, "test-row", "FRESH")]
        return AnomalyDetector._evaluate_metric("flow_rate_vph", baseline + test, AS_OF, test_start)

    small, large = run(30), run(300)
    assert small["status"] == large["status"] == "MEASURED_ANOMALY"
    assert small["confidence"] < large["confidence"]
    assert small["flagged_points"][0]["degrees_of_freedom"] == 29
    assert large["flagged_points"][0]["degrees_of_freedom"] == 299


def test_bonferroni_stops_ordinary_extremes_being_flagged_in_a_busy_window():
    """A 1-in-300 reading is notable alone and expected among fifteen."""
    test_start = AS_OF - timedelta(minutes=15)
    spacing = timedelta(seconds=20)
    baseline = _samples([10.0, 14.0] * 150, test_start - spacing * 300, spacing)
    unusual = 12.0 + 3.0 * 2.003 * math.sqrt(1 + 1 / 300)          # p ~ 0.003

    alone = AnomalyDetector._evaluate_metric(
        "flow_rate_vph", baseline + [(AS_OF - timedelta(minutes=1), unusual, "x", "FRESH")],
        AS_OF, test_start,
    )
    crowded = AnomalyDetector._evaluate_metric(
        "flow_rate_vph",
        baseline
        + [(test_start + timedelta(minutes=i + 0.5), 12.0, "n{}".format(i), "FRESH") for i in range(14)]
        + [(AS_OF - timedelta(seconds=10), unusual, "x", "FRESH")],
        AS_OF, test_start,
    )

    assert alone["status"] == "MEASURED_ANOMALY"
    assert crowded["status"] == "NO_ANOMALY"
    assert crowded["per_reading_alpha"] < alone["per_reading_alpha"]


def test_a_constant_baseline_is_not_computable():
    """A stuck feed has no variance, and a deviation in sigmas does not exist."""
    test_start = AS_OF - timedelta(minutes=15)
    baseline = _samples([50.0] * 40, test_start - timedelta(minutes=80), timedelta(minutes=2))
    result = AnomalyDetector._evaluate_metric(
        "occupancy_pct", baseline + [(AS_OF, 90.0, "t", "FRESH")], AS_OF, test_start,
    )
    assert result["status"] == "NOT_COMPUTABLE"
    assert result["reason"] == "BASELINE_HAS_ZERO_VARIANCE"
    assert "stuck" in result["explanation"]


def _shift_case(test_readings: int):
    test_start = AS_OF - timedelta(minutes=15)
    spacing = timedelta(seconds=40)
    baseline = _samples([10.0, 14.0] * 60, test_start - spacing * 120, spacing)
    shifted = [15.8, 16.2] * test_readings
    test = [
        (test_start + timedelta(seconds=30 + 55 * i), shifted[i], "s{}".format(i), "FRESH")
        for i in range(test_readings)
    ]
    return AnomalyDetector._evaluate_metric("flow_rate_vph", baseline + test, AS_OF, test_start)


def test_a_sustained_shift_is_reported_only_once_welch_confirms_it():
    """No single reading is extreme; the persistence of the shift is."""
    result = _shift_case(15)
    assert result["flagged_points"] == [], "each reading alone is within ordinary range"
    assert result["sustained_shift"]["status"] == "CONFIRMED"
    assert result["sustained_shift"]["direction"] == "HIGH"
    assert result["status"] == "MEASURED_ANOMALY"
    assert result["sustained_shift"]["confidence"] > 0.99


def test_a_cusum_alarm_with_too_few_readings_is_only_suspected():
    result = _shift_case(5)
    assert result["sustained_shift"]["status"] == "SUSPECTED_TOO_FEW_SAMPLES_TO_CONFIRM"
    assert result["sustained_shift"]["confidence"] is None
    assert result["status"] == "NO_ANOMALY", "a suspicion is not an anomaly"


def test_invalid_rows_are_excluded_as_not_measurements():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-INVALID")
        for i in range(135):
            _metric(db, jid, AS_OF - timedelta(minutes=134 - i), flow=600 + _jitter("inv", i, 40))
        _metric(db, jid, AS_OF - timedelta(minutes=1), flow=99999, quality="INVALID")
        db.commit()
        result = AnomalyDetector.detect(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["rows_excluded_as_not_measurements"] == 1
    assert result["status"] == "NO_ANOMALY"


def test_anomaly_endpoint(headers):
    missing = client.get("/api/v1/intelligence/anomalies/no-such-junction", headers=headers["gi_admin"])
    assert missing.status_code == 404

    db = SessionLocal()
    try:
        jid = _junction(db, "GI-AN-API")
    finally:
        db.close()
    response = client.get(
        "/api/v1/intelligence/anomalies/{}".format(jid),
        params={"as_of": AS_OF.isoformat()}, headers=headers["gi_viewer"],
    )
    assert response.status_code == 200, "reading anomalies needs only read access"
    assert response.json()["status"] == "NOT_COMPUTABLE"


# ===========================================================================
# 2. Forecasting
# ===========================================================================

def _binned_history(db, jid, values, end_bin_start: datetime, bin_minutes=15, skip=()):
    """Writes one metric row inside each bin, ending with the bin at end_bin_start."""
    count = len(values)
    for i, value in enumerate(values):
        if i in skip:
            continue
        bin_start = end_bin_start - timedelta(minutes=bin_minutes * (count - 1 - i))
        _metric(db, jid, bin_start + timedelta(minutes=7), flow=value)
    db.commit()


LAST_COMPLETE_BIN = AS_OF - timedelta(minutes=15)


def test_forecast_of_a_metric_never_recorded_is_not_computable():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-NONE")
        result = ShortHorizonForecaster.forecast(db, jid, metric="avg_speed_kph", as_of=AS_OF)
    finally:
        db.close()
    assert result["forecast_status"] == "NOT_COMPUTABLE"
    assert result["refusal_reason"] == "NO_STORED_VALUES_FOR_METRIC"
    assert result["forecast_points"] == []


def test_short_history_is_refused_with_its_counts():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-SHORT")
        _binned_history(db, jid, [600 + _jitter("short", i, 20) for i in range(20)], LAST_COMPLETE_BIN)
        result = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["forecast_status"] == "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST"
    assert result["refusal_reason"] == "INSUFFICIENT_HISTORY"
    assert result["history"]["gap_free_run_bins"] == 20
    assert result["history"]["bins_required"] > 20
    assert result["forecast_points"] == [] and result["model"] is None


def test_gaps_are_never_interpolated():
    """Plenty of history, broken by a gap: the model will not draw through it."""
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-GAP")
        values = [600 + 200 * math.sin(2 * math.pi * i / 24) for i in range(100)]
        _binned_history(db, jid, values, LAST_COMPLETE_BIN, skip={90})
        result = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["refusal_reason"] == "GAPS_BREAK_HISTORY"
    assert result["history"]["gap_free_run_bins"] == 9
    assert result["history"]["missing_bins_in_history"] == 1
    assert "never interpolated" in result["message"]


def test_a_stale_series_is_not_a_forecast_origin():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-STALE")
        values = [600 + 200 * math.sin(2 * math.pi * i / 24) for i in range(100)]
        _binned_history(db, jid, values, AS_OF - timedelta(hours=3))
        result = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["refusal_reason"] == "LATEST_DATA_TOO_OLD"
    assert "already happened" in result["message"]


def test_a_predictable_series_gets_a_labelled_forecast_with_intervals():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-GOOD")
        values = [
            600 + 250 * math.sin(2 * math.pi * i / 24) + _jitter("good", i, 5)
            for i in range(120)
        ]
        _binned_history(db, jid, values, LAST_COMPLETE_BIN)
        result = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF, horizon_bins=4)
    finally:
        db.close()

    assert result["forecast_status"] == "FORECAST_AVAILABLE", result.get("message")
    assert result["stamp"] == "SCENARIO / HYPOTHETICAL"
    assert result["data_kind"] == "MODEL_FORECAST"
    assert result["backtest"]["skill_vs_persistence"] >= MIN_SKILL_OVER_PERSISTENCE
    assert result["backtest"]["selected_interval_coverage_95"] is not None
    assert result["model"]["family"].startswith("ARIMA(p,d,0)")
    assert "no moving-average terms" in result["model"]["family"]

    points = result["forecast_points"]
    assert len(points) == 4
    first_bin = datetime.fromisoformat(points[0]["bin_start"])
    assert first_bin == AS_OF, "the first forecast bin follows the last complete one"
    for point in points:
        assert point["kind"] == "MODEL_FORECAST"
        assert point["lower_95"] <= point["value"] <= point["upper_95"]
        assert point["lower_95"] >= 0.0, "throughput cannot be negative"


def test_a_model_without_skill_is_refused_and_the_refusal_shows_that_model():
    """This is the case the old endpoint could never state honestly.

    A random walk is best predicted by its last value. A model fitted to one
    cannot beat persistence, so no forecast is offered - but the model was
    fitted and measured, and the response says so.
    """
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-WALK")
        level, values = 600.0, []
        for i in range(120):
            level += _jitter("walk", i, 30)
            values.append(level)
        _binned_history(db, jid, values, LAST_COMPLETE_BIN)
        result = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)
    finally:
        db.close()

    assert result["forecast_status"] == "INSUFFICIENT_DATA_FOR_RELIABLE_FORECAST"
    assert result["refusal_reason"] == "NO_SKILL_OVER_PERSISTENCE"
    assert result["model"] is not None, "the refusal has a fitted model behind it"
    assert result["backtest"]["skill_vs_persistence"] < MIN_SKILL_OVER_PERSISTENCE
    assert result["backtest"]["persistence_mae"] > 0
    assert result["forecast_points"] == []


def test_forecast_endpoint_validates_inputs(headers):
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FC-API")
    finally:
        db.close()
    bad = client.get(
        "/api/v1/predictions/forecast/{}".format(jid),
        params={"metric": "made_up_metric"}, headers=headers["gi_admin"],
    )
    assert bad.status_code == 400
    assert client.get(
        "/api/v1/predictions/forecast/no-such-junction", headers=headers["gi_admin"]
    ).status_code == 404


# ===========================================================================
# 3. Fusion-based incident detection
# ===========================================================================

def _segmented_junction(db, code: str, silent_second_sensor: bool = False):
    """NB approach with two lanes, SB approach with one."""
    jid = _junction(db, code)
    nb = Approach(intersection_id=jid, direction="NORTHBOUND", road_name="Test Rd")
    sb = Approach(intersection_id=jid, direction="SOUTHBOUND", road_name="Test Rd")
    db.add_all([nb, sb])
    db.flush()
    nb1 = Lane(approach_id=nb.id, lane_number=1, movement_type="THRU", assigned_phase=2)
    nb2 = Lane(approach_id=nb.id, lane_number=2, movement_type="THRU", assigned_phase=2)
    sb1 = Lane(approach_id=sb.id, lane_number=1, movement_type="THRU", assigned_phase=6)
    db.add_all([nb1, nb2, sb1])
    db.flush()
    if silent_second_sensor:
        db.add_all([
            Sensor(intersection_id=jid, lane_id=sb1.id, sensor_type="INDUCTIVE_LOOP", name="SB loop"),
            Sensor(intersection_id=jid, lane_id=sb1.id, sensor_type="RADAR", name="SB radar"),
        ])
    db.commit()
    return jid, {"nb": nb.id, "sb": sb.id, "nb1": nb1.id, "nb2": nb2.id, "sb1": sb1.id}


def _stream(db, jid, lane_id, source_id, sensor_kind, occupancy=None, speed=None):
    """70 one-minute observations: 60 baseline, then 10 in the recent window.

    `occupancy` / `speed` are (baseline_level, recent_level) or None for a
    channel this source does not report.
    """
    for i in range(70):
        minute = -69 + i
        recent = minute > -10
        occ = spd = None
        if occupancy is not None:
            occ = (occupancy[1] if recent else occupancy[0]) + _jitter(source_id + "o", i, 3)
        if speed is not None:
            spd = (speed[1] if recent else speed[0]) + _jitter(source_id + "s", i, 3)
        db.add(TrafficObservation(
            intersection_id=jid, lane_id=lane_id, source=sensor_kind, source_id=source_id,
            timestamp=AS_OF + timedelta(minutes=minute), vehicle_count=10,
            occupancy_pct=occ, avg_speed_kph=spd, quality="FRESH",
        ))
    db.commit()


def _segment(result, approach_id):
    return next(s for s in result["segments"] if s["approach_id"] == approach_id)


def test_a_corroborated_signature_is_a_probable_incident_naming_its_sources():
    """Loop sees occupancy rise; radar sees speed fall; together, two sources."""
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-PROBABLE")
        _stream(db, jid, ids["nb1"], "nb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 45))
        _stream(db, jid, ids["nb2"], "nb-radar-2", "RADAR", speed=(48, 18))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    nb = _segment(result, ids["nb"])
    assert result["status"] == "PROBABLE_INCIDENT"
    assert nb["status"] == "PROBABLE_INCIDENT"
    assert nb["occupancy_spike_sources"] == ["nb-loop-1"]
    assert nb["speed_drop_sources"] == ["nb-radar-2"]
    assert nb["corroborating_sources"] == ["nb-loop-1", "nb-radar-2"]
    assert nb["corroboration_ratio"] == 1.0
    assert "not a probability" in nb["corroboration_ratio_basis"]


def test_one_detector_with_both_symptoms_is_not_corroborated():
    """The phantom-incident case: one bad loop agreeing with itself."""
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-SINGLE")
        _stream(db, jid, ids["nb1"], "nb-dual-1", "DUAL_LOOP", occupancy=(12, 45), speed=(48, 18))
        _stream(db, jid, ids["nb2"], "nb-radar-2", "RADAR", occupancy=(12, 12), speed=(48, 48))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    nb = _segment(result, ids["nb"])
    assert nb["status"] == "UNCORROBORATED_SINGLE_SOURCE"
    assert nb["corroborating_sources"] == ["nb-dual-1"]
    assert nb["evaluated_but_not_corroborating"] == ["nb-radar-2"]
    assert result["status"] != "PROBABLE_INCIDENT"


def test_a_segment_with_one_sensor_cannot_corroborate_at_all():
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-ONESENSOR")
        _stream(db, jid, ids["sb1"], "sb-dual-1", "DUAL_LOOP", occupancy=(12, 60), speed=(48, 10))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    sb = _segment(result, ids["sb"])
    assert sb["status"] == "NOT_COMPUTABLE"
    assert sb["reason"] == "FEWER_THAN_TWO_INDEPENDENT_SOURCES"
    assert "cannot corroborate itself" in sb["explanation"]


def test_a_configured_but_silent_second_sensor_is_insufficient_data():
    """Fix the silent sensor - which is different from installing a new one."""
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-SILENT", silent_second_sensor=True)
        _stream(db, jid, ids["sb1"], "sb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 60))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    sb = _segment(result, ids["sb"])
    assert sb["status"] == "INSUFFICIENT_DATA"
    assert sb["reason"] == "CONFIGURED_SOURCES_SILENT"


def test_one_symptom_alone_is_partial_not_an_incident():
    """High occupancy at normal speed is ordinary heavy traffic."""
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-PARTIAL")
        _stream(db, jid, ids["nb1"], "nb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 45))
        _stream(db, jid, ids["nb2"], "nb-radar-2", "RADAR", speed=(48, 47))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    nb = _segment(result, ids["nb"])
    assert nb["status"] == "PARTIAL_SYMPTOMS"
    assert nb["reason"] == "ONE_SYMPTOM_ONLY"


def test_a_statistically_real_but_small_change_is_not_a_symptom():
    """Significance is not relevance: +5 points of occupancy is not a spike."""
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-SMALL")
        _stream(db, jid, ids["nb1"], "nb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 17))
        _stream(db, jid, ids["nb2"], "nb-radar-2", "RADAR", speed=(48, 18))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    nb = _segment(result, ids["nb"])
    loop = next(a for a in nb["source_assessments"] if a["source"] == "nb-loop-1")
    assert loop["occupancy"]["ci_low"] > 0, "the rise is statistically real"
    assert loop["occupancy_spike"] is False, "but below the practical threshold"
    assert nb["status"] == "PARTIAL_SYMPTOMS"


def test_observations_without_a_lane_are_reported_never_guessed_onto_a_segment():
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, "GI-FU-NOLANE")
        _stream(db, jid, None, "roaming-probe", "PROBE", occupancy=(12, 45), speed=(48, 18))
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()

    assert result["unattributed_sources"][0]["source"] == "roaming-probe"
    assert result["unattributed_sources"][0]["reason"] == "NO_LANE_ASSIGNMENT"
    assert all(s["sources_reporting"] == 0 for s in result["segments"])
    assert result["status"] == "NOT_COMPUTABLE"


def test_a_junction_with_no_approaches_is_not_computable():
    db = SessionLocal()
    try:
        jid = _junction(db, "GI-FU-NOAPPROACH")
        result = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)
    finally:
        db.close()
    assert result["status"] == "NOT_COMPUTABLE"
    assert "Configure approaches and lanes" in result["detail"]


def _probable_junction(code):
    db = SessionLocal()
    try:
        jid, ids = _segmented_junction(db, code)
        _stream(db, jid, ids["nb1"], "nb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 45))
        _stream(db, jid, ids["nb2"], "nb-radar-2", "RADAR", speed=(48, 18))
        return jid, ids
    finally:
        db.close()


def test_evaluating_writes_nothing(headers):
    jid, _ids = _probable_junction("GI-FU-DRYRUN")
    db = SessionLocal()
    before = db.query(Incident).count()
    db.close()

    response = client.get(
        "/api/v1/intelligence/incident-fusion/{}".format(jid),
        params={"as_of": AS_OF.isoformat()}, headers=headers["gi_admin"],
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PROBABLE_INCIDENT"

    db = SessionLocal()
    after = db.query(Incident).count()
    db.close()
    assert after == before


def test_recording_creates_detected_never_verified_with_traceable_evidence(headers):
    jid, _ids = _probable_junction("GI-FU-RECORD")
    response = client.post(
        "/api/v1/intelligence/incident-fusion/{}/record".format(jid),
        params={"as_of": AS_OF.isoformat()}, headers=headers["gi_admin"],
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["recorded"]) == 1
    recorded = body["recorded"][0]

    db = SessionLocal()
    try:
        incident = db.query(Incident).filter(Incident.id == recorded["incident_id"]).first()
        assert incident.status == "DETECTED", "a machine never verifies an incident"
        assert incident.source == "FUSION_DETECTOR"
        assert incident.evidence["corroborating_sources"] == ["nb-loop-1", "nb-radar-2"]

        evidence = db.query(IncidentEvidence).filter(IncidentEvidence.incident_id == incident.id).all()
        assert len(evidence) == 2
        for item in evidence:
            assert item.source_table == "traffic_observations"
            assert db.query(TrafficObservation).filter(TrafficObservation.id == item.source_id).first()

        timeline = (
            db.query(IncidentTimelineEntry)
            .filter(IncidentTimelineEntry.incident_id == incident.id)
            .all()
        )
        detected = next(t for t in timeline if t.entry_type == "STATUS_CHANGE")
        assert detected.context["requires_human_verification"] is True
    finally:
        db.close()


def test_recording_twice_does_not_open_a_duplicate(headers):
    jid, _ids = _probable_junction("GI-FU-DEDUPE")
    url = "/api/v1/intelligence/incident-fusion/{}/record".format(jid)
    first = client.post(url, params={"as_of": AS_OF.isoformat()}, headers=headers["gi_admin"]).json()
    second = client.post(url, params={"as_of": AS_OF.isoformat()}, headers=headers["gi_admin"]).json()

    assert len(first["recorded"]) == 1
    assert second["recorded"] == []
    assert second["skipped"][0]["reason"] == "OPEN_INCIDENT_ALREADY_EXISTS"
    assert second["skipped"][0]["incident_id"] == first["recorded"][0]["incident_id"]


def test_recording_requires_the_incident_write_scope(headers):
    """Viewers and auditors can see a probable incident; they cannot file one."""
    jid, _ids = _probable_junction("GI-FU-SCOPE")
    url = "/api/v1/intelligence/incident-fusion/{}/record".format(jid)
    for user in ("gi_viewer", "gi_auditor"):
        response = client.post(url, params={"as_of": AS_OF.isoformat()}, headers=headers[user])
        assert response.status_code == 403, user
    assert client.get(
        "/api/v1/intelligence/incident-fusion/{}".format(jid),
        params={"as_of": AS_OF.isoformat()}, headers=headers["gi_viewer"],
    ).status_code == 200


# ===========================================================================
# Safety invariant
# ===========================================================================

def test_no_intelligence_endpoint_touches_a_signal_controller(headers):
    """Anomalies, forecasts and incidents inform an operator; they never command.

    The Deterministic Signal Safety Engine is the only path to a controller.
    None of these features may create a signal command, even indirectly.
    """
    jid, _ids = _probable_junction("GI-SAFETY")
    db = SessionLocal()
    commands_before = db.query(SignalCommand).count()
    db.close()

    admin = headers["gi_admin"]
    params = {"as_of": AS_OF.isoformat()}
    client.get("/api/v1/intelligence/anomalies/{}".format(jid), params=params, headers=admin)
    client.get("/api/v1/predictions/forecast/{}".format(jid), params=params, headers=admin)
    client.get("/api/v1/intelligence/incident-fusion/{}".format(jid), params=params, headers=admin)
    client.post("/api/v1/intelligence/incident-fusion/{}/record".format(jid), params=params, headers=admin)

    db = SessionLocal()
    commands_after = db.query(SignalCommand).count()
    db.close()
    assert commands_after == commands_before
