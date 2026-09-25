"""Generates render-check fixtures for the grounded-intelligence panels.

    python -m tools.generate_intelligence_render_fixtures

Provenance, stated plainly: these responses are produced by the REAL anomaly
detector, forecaster, fusion detector, green-wave planner, TSP evaluator and preemption service
(against an in-process NTCIP emulator), run over TEST TELEMETRY written to a
throwaway SQLite database that is deleted afterwards. The telemetry is
deterministic (SHA-256-derived variation, the same scheme the pytest suite
uses) so the fixtures are reproducible. They are not recordings from a field
deployment, and nothing here touches the operational database.

They exist so `npm run check:render` can assert that each state these panels
must handle - measured anomaly, refusal with a fitted model, corroborated and
uncorroborated incidents - renders truthfully.
"""

import hashlib
import json
import math
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

_DB = pathlib.Path(tempfile.gettempdir()) / "trafficintel_render_fixtures.db"
if _DB.exists():
    _DB.unlink()
os.environ["DATABASE_URL"] = "sqlite:///{}".format(_DB.as_posix())
os.environ["ENVIRONMENT"] = "development"

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, engine  # noqa: E402
from app.core.migrations import upgrade_to_head  # noqa: E402
from app.analytics.anomaly import AnomalyDetector  # noqa: E402
from app.analytics.forecasting import ShortHorizonForecaster  # noqa: E402
from app.incidents.fusion import IncidentFusionDetector  # noqa: E402
from app.models.entities import (  # noqa: E402
    Approach, Corridor, Intersection, Lane, SignalController, SignalPhase,
    SignalStateLog, TrafficMetric, TrafficObservation,
)
from app.coordination.green_wave import GreenWavePlanner  # noqa: E402
from app.providers.gtfs_rt import decode_feed, encode_feed  # noqa: E402
from app.transit.tsp import TransitSignalPriority  # noqa: E402
from app.emergency.preemption import PreemptionService  # noqa: E402
from tools.ntcip_emulator import ConcurrentGroup, NtcipEmulatorServer, SignalControllerEmulator  # noqa: E402

AS_OF = datetime(2026, 3, 10, 14, 0, 0)
OUT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "scripts" / "render-check" / "fixtures"


def jitter(key, index, amplitude):
    digest = hashlib.sha256("{}:{}".format(key, index).encode()).digest()
    return (int.from_bytes(digest[:8], "big") / 2 ** 64 - 0.5) * 2 * amplitude


def junction(db, code):
    inter = Intersection(name="Fixture {}".format(code), code=code, latitude=12.0,
                         longitude=77.0, operational_status="HEALTHY")
    db.add(inter)
    db.commit()
    return inter.id


def metric(db, jid, ts, **values):
    db.add(TrafficMetric(intersection_id=jid, timestamp=ts, sample_window_sec=60.0,
                         data_quality="FRESH", calculation_method="TEST_TELEMETRY", **values))


def binned(db, jid, values):
    last = AS_OF - timedelta(minutes=15)
    for i, v in enumerate(values):
        metric(db, jid, last - timedelta(minutes=15 * (len(values) - 1 - i)) + timedelta(minutes=7),
               flow_rate_vph=v)
    db.commit()


def stream(db, jid, lane, source_id, kind, occupancy=None, speed=None):
    for i in range(70):
        minute = -69 + i
        recent = minute > -10
        occ = (occupancy[1] if recent else occupancy[0]) + jitter(source_id + "o", i, 3) if occupancy else None
        spd = (speed[1] if recent else speed[0]) + jitter(source_id + "s", i, 3) if speed else None
        db.add(TrafficObservation(intersection_id=jid, lane_id=lane, source=kind, source_id=source_id,
                                  timestamp=AS_OF + timedelta(minutes=minute), vehicle_count=10,
                                  occupancy_pct=occ, avg_speed_kph=spd, quality="FRESH"))
    db.commit()


def segmented(db, code):
    jid = junction(db, code)
    nb = Approach(intersection_id=jid, direction="NORTHBOUND", road_name="Fixture Rd")
    sb = Approach(intersection_id=jid, direction="SOUTHBOUND", road_name="Fixture Rd")
    db.add_all([nb, sb])
    db.flush()
    lanes = [Lane(approach_id=nb.id, lane_number=1, movement_type="THRU"),
             Lane(approach_id=nb.id, lane_number=2, movement_type="THRU"),
             Lane(approach_id=sb.id, lane_number=1, movement_type="THRU")]
    db.add_all(lanes)
    db.commit()
    return jid, [lane.id for lane in lanes]


def controller(db, jid, protocol="NTCIP_1202", status="CONNECTED", conflict_override=None):
    unit = SignalController(intersection_id=jid, name="Fixture cabinet", vendor="Emulator",
                            model="NTCIP-1202", protocol=protocol, ip_address="127.0.0.1",
                            port=9, connection_status=status)
    db.add(unit)
    db.flush()
    for number, ring, barrier, conflicts in ((2, 1, 1, [4, 8]), (6, 2, 1, [4, 8]),
                                             (4, 1, 2, [2, 6]), (8, 2, 2, [2, 6])):
        if conflict_override and number in conflict_override:
            conflicts = conflict_override[number]
        db.add(SignalPhase(controller_id=unit.id, phase_number=number, ring=ring, barrier=barrier,
                           name="P{}".format(number), min_green=7, max_green=60, yellow_change=4,
                           red_clearance=2, ped_walk=0, ped_clearance=0, conflicting_phases=conflicts))
    db.flush()
    return unit


def corridor_with(db, name, specs):
    """specs: per junction, None (no controller) or controller kwargs."""
    corridor = Corridor(name=name, coordination_mode="UNCOORDINATED")
    db.add(corridor)
    db.flush()
    ids = []
    for index, spec in enumerate(specs):
        inter = Intersection(name="{} J{}".format(name, index + 1), code="{}{}".format(name[:6], index),
                             latitude=13.0 + index * 0.004, longitude=78.5, corridor_id=corridor.id)
        db.add(inter)
        db.flush()
        db.add(Approach(intersection_id=inter.id, direction="NORTHBOUND", road_name="Fixture Ave",
                        speed_limit_kph=50))
        if spec is not None:
            controller(db, inter.id, **spec)
        ids.append(inter.id)
    db.commit()
    return corridor.id, ids


def main():
    upgrade_to_head()
    db = SessionLocal()
    fixtures = {}
    try:
        jid = junction(db, "AN-MEASURED")
        for i in range(135):
            ts = AS_OF - timedelta(minutes=134 - i)
            metric(db, jid, ts, flow_rate_vph=1500.0 if i == 130 else 600 + jitter("f", i, 40),
                   occupancy_pct=20 + jitter("o", i, 3))
        db.commit()
        fixtures["anomaly_measured"] = AnomalyDetector.detect(db, jid, as_of=AS_OF)

        jid = junction(db, "AN-SMALL")
        for i in range(10):
            metric(db, jid, AS_OF - timedelta(minutes=60 - i * 3), flow_rate_vph=600 + jitter("s", i, 30))
        metric(db, jid, AS_OF - timedelta(minutes=2), flow_rate_vph=5000)
        db.commit()
        fixtures["anomaly_insufficient"] = AnomalyDetector.detect(db, jid, as_of=AS_OF)

        jid = junction(db, "FC-GOOD")
        binned(db, jid, [600 + 250 * math.sin(2 * math.pi * i / 24) + jitter("g", i, 5) for i in range(120)])
        fixtures["forecast_available"] = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)

        jid = junction(db, "FC-WALK")
        level, walk = 600.0, []
        for i in range(120):
            level += jitter("walk", i, 30)
            walk.append(level)
        binned(db, jid, walk)
        fixtures["forecast_no_skill"] = ShortHorizonForecaster.forecast(db, jid, as_of=AS_OF)

        jid = junction(db, "FC-NONE")
        fixtures["forecast_not_computable"] = ShortHorizonForecaster.forecast(
            db, jid, metric="avg_speed_kph", as_of=AS_OF)

        jid, (nb1, nb2, sb1) = segmented(db, "FU-PROBABLE")
        stream(db, jid, nb1, "nb-loop-1", "INDUCTIVE_LOOP", occupancy=(12, 45))
        stream(db, jid, nb2, "nb-radar-2", "RADAR", speed=(48, 18))
        stream(db, jid, sb1, "sb-dual-1", "DUAL_LOOP", occupancy=(12, 12), speed=(48, 48))
        stream(db, jid, None, "roaming-probe", "PROBE", speed=(48, 48))
        fixtures["fusion_probable"] = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)

        jid, (nb1, nb2, _sb1) = segmented(db, "FU-SINGLE")
        stream(db, jid, nb1, "nb-dual-1", "DUAL_LOOP", occupancy=(12, 45), speed=(48, 18))
        stream(db, jid, nb2, "nb-radar-2", "RADAR", occupancy=(12, 12), speed=(48, 48))
        fixtures["fusion_uncorroborated"] = IncidentFusionDetector.evaluate(db, jid, as_of=AS_OF)

        # --- Phase 2: coordination refusals -------------------------------
        cid, ids = corridor_with(db, "CoordNC", [{}, None, {"protocol": "ASC3_ETHERNET"}])
        fixtures["coordination_not_computable"] = GreenWavePlanner.propose(
            db, cid, actor="fixture", design_speed_kph=50)

        cid, ids = corridor_with(db, "CoordSafe", [
            {"conflict_override": {2: [4, 6, 8]}}, {"conflict_override": {2: [4, 6, 8]}}])
        volumes = {i: [{"phase_number": 2, "volume_vph": 900, "lanes": 2},
                       {"phase_number": 4, "volume_vph": 350, "lanes": 1}] for i in ids}
        fixtures["coordination_rejected_by_safety"] = GreenWavePlanner.propose(
            db, cid, actor="fixture", design_speed_kph=50, movements=volumes)

        # --- Phase 2: conditional TSP (dry run over a test feed) -------------
        inter = Intersection(name="Fixture TSP Junction", code="FXTSP", latitude=14.0, longitude=79.0)
        db.add(inter)
        db.flush()
        approach = Approach(intersection_id=inter.id, direction="NORTHBOUND", road_name="Fixture Ave")
        db.add(approach)
        db.flush()
        db.add(Lane(approach_id=approach.id, lane_number=1, movement_type="THRU", assigned_phase=2))
        unit = controller(db, inter.id)
        now = datetime.now(timezone.utc)
        db.add(SignalStateLog(controller_id=unit.id, intersection_id=inter.id,
                              timestamp=now.replace(tzinfo=None) - timedelta(seconds=1),
                              green_phases=[2, 6], yellow_phases=[], red_phases=[], source="NTCIP_1202_POLL"))
        db.commit()
        stamp = int(now.timestamp()) - 2

        def bus(vehicle, trip, metres, bearing=0.0):
            return {"trip_id": trip, "route_id": "R12", "latitude": 14.0 - metres / 111320.0,
                    "longitude": 79.0, "bearing_deg": bearing, "speed_mps": 8.0,
                    "timestamp": stamp, "vehicle_id": vehicle}

        feed = decode_feed(encode_feed(stamp, vehicles=[
            bus("BUS-LATE", "T-LATE", 150), bus("BUS-ONTIME", "T-ONTIME", 160),
            bus("BUS-NODATA", "T-NODATA", 170), bus("BUS-FAR", "T-FAR", 900),
        ]))
        updates = decode_feed(encode_feed(stamp, trip_updates=[
            {"trip_id": "T-LATE", "delay_sec": 150}, {"trip_id": "T-ONTIME", "delay_sec": 15},
            {"trip_id": "T-FAR", "delay_sec": 200},
        ]))["trip_updates"]
        fixtures["tsp_dry_run"] = TransitSignalPriority.evaluate(
            db, feed, updates, dry_run=True, actor_id=None, actor_name="fixture", now=now)

        # --- Phase 2: preemption verdicts, through the real dispatcher ------
        def verdict(outcome):
            event = outcome["event"]
            return {
                "event_id": event.id, "status": event.status,
                "requested_phase": event.requested_phase,
                "safety_clearance_passed": event.safety_clearance_passed,
                "safety_report": outcome["safety"], "trigger": event.trigger,
                "command_id": event.command_id, "command_status": event.command_status,
            }

        server = NtcipEmulatorServer(host="127.0.0.1", port=0, emulator=SignalControllerEmulator(
            groups=[ConcurrentGroup(phases=g) for g in ([2, 6], [4, 8])])).start()
        try:
            inter = Intersection(name="Fixture EVP Junction", code="FXEVP", latitude=15.0, longitude=80.0)
            db.add(inter)
            db.flush()
            unit = controller(db, inter.id)
            unit.port, unit.active_phase = server.port, 2
            unit.current_phase_start = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(seconds=30)
            db.commit()
            fixtures["preemption_active"] = verdict(PreemptionService.preempt(
                db, inter, 2, "FX-MED-1", "AMBULANCE", actor_id=None, actor_name="fixture"))
            fixtures["preemption_rejected"] = verdict(PreemptionService.preempt(
                db, inter, 4, "FX-MED-2", "AMBULANCE", actor_id=None, actor_name="fixture"))
        finally:
            server.stop()
        fixtures["preemption_failed"] = verdict(PreemptionService.preempt(
            db, inter, 2, "FX-MED-3", "AMBULANCE", actor_id=None, actor_name="fixture"))
    finally:
        db.close()
        engine.dispose()
        _DB.unlink(missing_ok=True)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, payload in fixtures.items():
        (OUT / "{}.json".format(name)).write_text(json.dumps(payload, indent=1, default=str), encoding="utf-8")
        status = payload.get("status") or payload.get("forecast_status")
        print("  {:<26} {}".format(name, status))


if __name__ == "__main__":
    main()
