"""TRAFFICINTEL AI - Corridor / Network Scale Tests

Arterial coordination (green waves), transit signal priority, and emergency
vehicle preemption from an AVL feed.

All three change what a signal controller does, so the tests pin two things
before anything else:

* every path to hardware goes through the Deterministic Safety Engine and the
  single SignalCommandDispatcher, and a rejection sends nothing;
* the record of what happened is what happened - an acknowledged plan whose
  read-back differs is FAILED, a half-applied green wave says so, and a
  preemption that never reached the controller is not audited as executed.
"""

import math
import time
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.coordination.green_wave import GreenWavePlanner, _band
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.main import app
from app.models.entities import (
    Approach, AuditLog, CoordinationPlan, Corridor, Intersection, Lane,
    SignalCommand, SignalController, SignalPhase, SignalStateLog, User,
)
from app.providers import ntcip_objects as ntcip
from app.providers import snmp_codec as snmp
from app.providers.controller_provider import Ntcip1202Adapter
from app.safety.safety_engine import DeterministicSafetyEngine
from tools.ntcip_emulator import ConcurrentGroup, NtcipEmulatorServer, SignalControllerEmulator

client = TestClient(app)


def _utcnow():
    return datetime.now(timezone.utc)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


@pytest.fixture(scope="module")
def headers():
    db = SessionLocal()
    try:
        for username, role in (("cn_admin", "ADMIN"), ("cn_operator", "OPERATOR"),
                               ("cn_engineer", "ENGINEER"), ("cn_viewer", "VIEWER")):
            if not db.query(User).filter(User.username == username).first():
                db.add(User(username=username, email="{}@trafficintel.gov".format(username),
                            hashed_password=get_password_hash("SecretPass123!"),
                            full_name=username, role=role))
        db.commit()
    finally:
        db.close()
    tokens = {}
    for username in ("cn_admin", "cn_operator", "cn_engineer", "cn_viewer"):
        response = client.post("/api/v1/auth/login",
                               data={"username": username, "password": "SecretPass123!"})
        assert response.status_code == 200, response.text
        tokens[username] = {"Authorization": "Bearer " + response.json()["access_token"]}
    return tokens


def _emulator(clock=None):
    groups = [ConcurrentGroup(phases=phases) for phases in ([2, 6], [4, 8])]
    emulator = SignalControllerEmulator(groups=groups, **({"clock": clock} if clock else {}))
    return NtcipEmulatorServer(host="127.0.0.1", port=0, emulator=emulator).start()


PHASES = [
    # (number, ring, barrier, conflicting)
    (2, 1, 1, [4, 8]), (6, 2, 1, [4, 8]),
    (4, 1, 2, [2, 6]), (8, 2, 2, [2, 6]),
]


def _controller(db, jid, port, protocol="NTCIP_1202", status="CONNECTED", ped=(0, 0)):
    controller = SignalController(
        intersection_id=jid, name="Cabinet {}".format(jid[:6]), vendor="Emulator",
        model="NTCIP-1202", protocol=protocol, ip_address="127.0.0.1", port=port,
        connection_status=status,
    )
    db.add(controller)
    db.flush()
    for number, ring, barrier, conflicts in PHASES:
        db.add(SignalPhase(
            controller_id=controller.id, phase_number=number, ring=ring, barrier=barrier,
            name="P{}".format(number), min_green=7, max_green=60,
            yellow_change=4, red_clearance=2, ped_walk=ped[0], ped_clearance=ped[1],
            conflicting_phases=conflicts,
        ))
    db.flush()
    return controller


def _corridor(db, name, count=3, spacing_deg=0.004, ports=None, **controller_kwargs):
    """A north-south corridor; ~445 m between junctions at spacing 0.004 deg."""
    corridor = Corridor(name=name, coordination_mode="UNCOORDINATED")
    db.add(corridor)
    db.flush()
    junctions = []
    for index in range(count):
        inter = Intersection(
            name="{} J{}".format(name, index + 1), code="{}-{}".format(name, index + 1)[:32],
            latitude=11.0 + index * spacing_deg, longitude=77.0, corridor_id=corridor.id,
            operational_status="HEALTHY",
        )
        db.add(inter)
        db.flush()
        db.add(Approach(intersection_id=inter.id, direction="NORTHBOUND",
                        road_name="Test Arterial", speed_limit_kph=50))
        if ports is not None:
            port = ports[index]
            if port is not False:
                _controller(db, inter.id, port, **controller_kwargs)
        junctions.append(inter.id)
    db.commit()
    return corridor.id, junctions


def _volumes(junctions, main=900, cross=350):
    return {
        jid: [{"phase_number": 2, "volume_vph": main, "lanes": 2},
              {"phase_number": 4, "volume_vph": cross, "lanes": 1}]
        for jid in junctions
    }


# ===========================================================================
# Safety Engine: timing plans
# ===========================================================================

class _Phase:
    def __init__(self, number, ring, barrier, conflicts, min_green=7, max_green=60,
                 yellow=4, red=2, walk=0, ped_clear=0):
        self.phase_number, self.ring, self.barrier = number, ring, barrier
        self.conflicting_phases = conflicts
        self.min_green, self.max_green = min_green, max_green
        self.yellow_change, self.red_clearance = yellow, red
        self.ped_walk, self.ped_clearance = walk, ped_clear
        self.name = "P{}".format(number)


class _Controller:
    def __init__(self, protocol="NTCIP_1202", status="CONNECTED", phases=None):
        self.name, self.protocol, self.connection_status = "Unit", protocol, status
        self.phases = phases or [_Phase(n, r, b, c) for n, r, b, c in PHASES]


def _validate(controller=None, splits=None, cycle=90, offset=20, coord=2):
    return DeterministicSafetyEngine.validate_timing_plan(
        controller=controller or _Controller(), cycle_sec=cycle, offset_sec=offset,
        splits=splits if splits is not None else {2: 50, 6: 50, 4: 40, 8: 40},
        coord_phase=coord, issued_at=_utcnow(), idempotency_key=str(uuid.uuid4()),
    )


def _failed(result):
    return {c.code for c in result.checks if not c.passed}


def test_a_well_formed_plan_passes_every_check():
    result = _validate()
    assert result.is_safe, result.violations
    for code in ("BARRIER_ALIGNMENT_CHECK", "RING_SUM_CHECK", "SPLIT_CLEARANCE_CHECK",
                 "CONTROLLER_CAPABILITY_CHECK", "OFFSET_RANGE_CHECK"):
        assert code in result.checks_performed


def test_rings_crossing_a_barrier_at_different_times_is_rejected():
    """Ring 1 would enter the cross-street group while ring 2 is still green on
    the main street: two conflicting movements green together."""
    result = _validate(splits={2: 55, 6: 45, 4: 35, 8: 45})
    assert "BARRIER_ALIGNMENT_CHECK" in _failed(result)
    assert not result.is_safe


def test_a_ring_that_does_not_sum_to_the_cycle_is_rejected():
    result = _validate(splits={2: 50, 6: 50, 4: 30, 8: 30})
    assert "RING_SUM_CHECK" in _failed(result)


def test_a_split_too_short_for_clearance_is_rejected():
    result = _validate(splits={2: 80, 6: 80, 4: 10, 8: 10})
    assert "SPLIT_CLEARANCE_CHECK" in _failed(result)
    assert any("min green" in v for v in result.violations)


def test_pedestrian_intervals_must_fit_inside_the_green():
    phases = [_Phase(n, r, b, c, walk=7, ped_clear=15) for n, r, b, c in PHASES]
    # 25 s split - 6 s clearance = 19 s of green, short of 7 s walk + 15 s ped clearance.
    result = _validate(controller=_Controller(phases=phases), splits={2: 65, 6: 65, 4: 25, 8: 25})
    assert "PEDESTRIAN_CLEARANCE_CHECK" in _failed(result)


def test_an_unserved_configured_phase_is_rejected():
    result = _validate(splits={2: 50, 6: 50, 4: 40})
    assert "PHASE_CONFIGURATION_LOOKUP" in _failed(result)
    assert any("never be served" in v for v in result.violations)


def test_phases_declared_conflicting_cannot_be_timed_concurrently():
    phases = [_Phase(n, r, b, c) for n, r, b, c in PHASES]
    phases[0].conflicting_phases = [4, 6, 8]  # phase 2 "conflicts" with 6, which shares its barrier
    result = _validate(controller=_Controller(phases=phases))
    assert "PHASE_CONFLICT_MATRIX_VALIDATION" in _failed(result)


def test_an_unreadable_or_non_ntcip_controller_cannot_receive_a_plan():
    assert "CONTROLLER_STATE_VALIDATION" in _failed(_validate(controller=_Controller(status="REACHABLE")))
    assert "CONTROLLER_CAPABILITY_CHECK" in _failed(_validate(controller=_Controller(protocol="ASC3_ETHERNET")))


def test_offset_outside_the_cycle_is_rejected():
    assert "OFFSET_RANGE_CHECK" in _failed(_validate(offset=90))


# ===========================================================================
# Emulator: coordination is real, and SNMP sets are atomic
# ===========================================================================

def test_emulator_runs_a_pattern_with_green_starting_at_the_offset():
    now = [1_000_000.0]
    emulator = SignalControllerEmulator(
        groups=[ConcurrentGroup(phases=p) for p in ([2, 6], [4, 8])], clock=lambda: now[0]
    )
    for oid, value in ntcip.timing_plan_varbinds(1, 60, 17, {2: 30, 6: 30, 4: 30, 8: 30}, 2):
        assert emulator.write_oid(oid, value)

    # Coordinated green starts whenever (t - offset) mod cycle == 0.
    now[0] = 1_000_000.0 + (17 - 1_000_000.0 % 60) % 60
    start = emulator.state()
    assert start["coordinated"] is True and start["greens"] == [2, 6]
    assert start["cycle_position_sec"] == 0.0

    now[0] += 24.5          # green is 30 - 4 - 2 = 24 s, so this is yellow
    assert emulator.state()["yellows"] == [2, 6]
    now[0] += 6.0           # into the cross-street group
    assert emulator.state()["greens"] == [4, 8]


def test_emulator_refuses_to_run_an_inconsistent_pattern():
    """A controller told to run an impossible plan stays free - and says so."""
    emulator = SignalControllerEmulator(groups=[ConcurrentGroup(phases=p) for p in ([2, 6], [4, 8])])
    for oid, value in ntcip.timing_plan_varbinds(1, 90, 0, {2: 55, 6: 45, 4: 35, 8: 45}, 2):
        emulator.write_oid(oid, value)
    assert emulator.state()["coordinated"] is False
    assert emulator.read_oid(ntcip.COORD_PATTERN_STATUS_OID) == ntcip.PATTERN_STATUS_FREE


def test_a_set_with_one_bad_varbind_applies_nothing():
    """RFC 1157 4.1.5: all or nothing."""
    server = _emulator()
    try:
        adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=server.port, timeout=1.0, retries=0)
        pairs = [(ntcip.pattern_oid(ntcip.COL_PATTERN_CYCLE_TIME, 1), 90),
                 (ntcip.MAX_PHASES_OID, 4)]  # read-only: must sink the whole PDU
        request_id = adapter._request_id()
        with pytest.raises(snmp.SnmpError):
            adapter._request(snmp.build_set_request("private", request_id, pairs), request_id)
        assert server.emulator.read_oid(ntcip.pattern_oid(ntcip.COL_PATTERN_CYCLE_TIME, 1)) == 0
    finally:
        server.stop()


def test_adapter_reads_back_the_plan_it_wrote():
    server = _emulator()
    try:
        adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=server.port, timeout=1.0)
        ok, _message, payload = adapter.write_timing_plan(1, 90, 25, {2: 50, 6: 50, 4: 40, 8: 40}, 2)
        assert ok is True
        readback = payload["readback"]
        assert readback["matches_request"] is True
        assert readback["active_pattern"] == 1
        assert readback["offset_sec"] == 25
    finally:
        server.stop()


def test_an_acknowledged_plan_the_controller_does_not_run_is_not_a_match():
    """The SET succeeds; the read-back shows the controller stayed free."""
    server = _emulator()
    try:
        adapter = Ntcip1202Adapter(ip_address="127.0.0.1", port=server.port, timeout=1.0)
        ok, _message, payload = adapter.write_timing_plan(1, 90, 0, {2: 55, 6: 45, 4: 35, 8: 45}, 2)
        assert ok is True, "the agent accepted every varbind"
        assert payload["readback"]["matches_request"] is False
        assert payload["readback"]["active_pattern"] == ntcip.PATTERN_STATUS_FREE
    finally:
        server.stop()


# ===========================================================================
# Green-wave planning
# ===========================================================================

def test_fewer_than_two_coordinatable_controllers_is_not_computable(headers):
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-INELIGIBLE", count=3, ports=[1, False, 2])
        # Second junction has no controller; make the third a non-NTCIP cabinet.
        third = db.query(SignalController).filter(SignalController.intersection_id == junctions[2]).first()
        third.protocol = "ASC3_ETHERNET"
        db.commit()
    finally:
        db.close()

    body = client.post("/api/v1/coordination/corridors/{}/propose".format(corridor_id),
                       json={"design_speed_kph": 50}, headers=headers["cn_admin"]).json()
    assert body["status"] == "NOT_COMPUTABLE"
    assert body["reason"] == "FEWER_THAN_TWO_COORDINATABLE_CONTROLLERS"
    reasons = {u["reason"] for u in body["uncoordinated"]}
    assert reasons == {"NO_CONTROLLER", "PROTOCOL_HAS_NO_TIMING_PLAN_CHANNEL"}


def test_a_disconnected_controller_is_not_coordinated():
    db = SessionLocal()
    try:
        corridor_id, _j = _corridor(db, "CN-DISCONNECTED", count=2, ports=[1, 2], status="DISCONNECTED")
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50)
    finally:
        db.close()
    assert result["status"] == "NOT_COMPUTABLE"
    assert {u["reason"] for u in result["uncoordinated"]} == {"CONTROLLER_DISCONNECTED"}


def test_a_green_wave_offsets_by_travel_time_and_reports_both_directions():
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-PLAN", count=3, ports=[1, 2, 3])
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                          movements=_volumes(junctions))
    finally:
        db.close()

    assert result["status"] == "PROPOSED", result.get("safety")
    assert result["speed_basis"] == "OPERATOR_ENTERED"
    assert result["safety"]["all_passed"] is True

    cycle = result["cycle_sec"]
    plans = result["junction_plans"]
    assert plans[0]["offset_sec"] == 0, "the origin junction anchors the wave"
    for plan in plans:
        expected = int(round(plan["position_m"] / (50 / 3.6))) % cycle
        assert plan["offset_sec"] == expected
        rings = {1: plan["splits"]["2"] + plan["splits"]["4"], 2: plan["splits"]["6"] + plan["splits"]["8"]}
        assert rings == {1: cycle, 2: cycle}

    band = result["bandwidth"]
    assert band["design_direction_sec"] > 0
    assert "opposite_direction_sec" in band, "the cost to the other direction is reported"
    assert band["design_direction_sec"] <= band["narrowest_coordinated_green_sec"]
    assert "cannot verify controller clock sync" in result["time_reference_note"]


def test_the_common_cycle_is_set_by_the_critical_junction():
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-CRITICAL", count=2, ports=[1, 2])
        volumes = _volumes(junctions)
        volumes[junctions[1]][0]["volume_vph"] = 1500  # busier junction needs a longer cycle
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50, movements=volumes)
    finally:
        db.close()
    optima = [p["own_optimum_cycle_sec"] for p in result["junction_plans"]]
    assert result["cycle_sec"] == max(optima)
    assert result["cycle_basis"].startswith("CRITICAL_JUNCTION_WEBSTER_OPTIMUM")


def test_without_entered_or_measured_demand_the_junction_is_refused():
    """No volumes and no lane mapping: the planner does not split evenly as a guess."""
    db = SessionLocal()
    try:
        corridor_id, _j = _corridor(db, "CN-NODEMAND", count=2, ports=[1, 2])
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50)
    finally:
        db.close()
    assert result["status"] == "REFUSED"
    assert result["reason"] == "NO_LANE_TO_PHASE_ASSIGNMENTS"


def test_over_capacity_demand_is_refused_not_timed():
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-OVERCAP", count=2, ports=[1, 2])
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                          movements=_volumes(junctions, main=4000, cross=2500))
    finally:
        db.close()
    assert result["status"] == "REFUSED"
    assert result["reason"] == "DEMAND_AT_OR_ABOVE_CAPACITY"


def test_design_speed_is_never_assumed():
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-NOSPEED", count=2, ports=[1, 2])
        for jid in junctions:
            db.query(Approach).filter(Approach.intersection_id == jid).delete()
        db.commit()
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", movements=_volumes(junctions))
    finally:
        db.close()
    assert result["status"] == "NOT_COMPUTABLE"
    assert result["reason"] == "NO_DESIGN_SPEED"


def test_a_configured_speed_limit_is_labelled_as_configured():
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-LIMIT", count=2, ports=[1, 2])
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", movements=_volumes(junctions))
    finally:
        db.close()
    assert result["design_speed_kph"] == 50
    assert result["speed_basis"] == "CONFIGURED_SPEED_LIMIT"


def test_a_cycle_too_short_for_pedestrians_is_refused_before_any_plan_exists():
    """Webster's optimum ignores pedestrian intervals; the planner does not."""
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-PEDCYCLE", count=2, ports=[1, 2], ped=(7, 15))
        refused = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                           cycle_sec=40, movements=_volumes(junctions))
        automatic = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                             movements=_volumes(junctions))
    finally:
        db.close()
    assert refused["status"] == "REFUSED"
    assert refused["reason"] == "CYCLE_BELOW_MINIMUM_FEASIBLE"
    assert refused["minimum_feasible_cycle_sec"] == 60  # 2 x (22 s ped + 6 s clearance) -> 56, up to 60

    # Found on a live corridor: the 40 s Webster optimum produced a 6 s main-street
    # green. With the floor, the plan uses the feasible cycle and passes.
    assert automatic["status"] == "PROPOSED", automatic.get("safety")
    assert automatic["cycle_sec"] >= 60
    assert automatic["cycle_basis"].startswith(("MINIMUM_FEASIBLE", "CRITICAL_JUNCTION"))
    for plan in automatic["junction_plans"]:
        assert plan["splits"]["2"] >= plan["splits"]["4"], "the busier movement is not starved"


def test_a_plan_the_safety_engine_rejects_is_stored_but_cannot_be_applied(headers):
    """Phases 2 and 6 share a barrier in opposite rings but are configured as
    conflicting: the planner times them together, the Safety Engine refuses."""
    db = SessionLocal()
    try:
        corridor_id, junctions = _corridor(db, "CN-UNSAFE", count=2, ports=[1, 2])
        for jid in junctions:
            controller = db.query(SignalController).filter(SignalController.intersection_id == jid).first()
            phase_two = next(p for p in controller.phases if p.phase_number == 2)
            phase_two.conflicting_phases = [4, 6, 8]
        db.commit()
        result = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                          movements=_volumes(junctions))
    finally:
        db.close()
    assert result["status"] == "REJECTED_BY_SAFETY"
    assert result["safety"]["all_passed"] is False

    response = client.post("/api/v1/coordination/plans/{}/apply".format(result["plan_id"]),
                           headers=headers["cn_admin"])
    assert response.status_code == 409


def test_bandwidth_is_the_intersection_of_every_green_window():
    # Two junctions, identical greens, perfect offsets: the band equals the green.
    assert _band([(0.0, 0, 30.0), (20.0, 20, 30.0)], 90) == 30.0
    # Offset wrong by 10 s: the band shrinks by 10 s.
    assert _band([(0.0, 0, 30.0), (20.0, 30, 30.0)], 90) == 20.0


# ===========================================================================
# Applying a plan to real controllers
# ===========================================================================

@pytest.fixture
def coordinated_corridor():
    servers = [_emulator(), _emulator()]
    db = SessionLocal()
    try:
        name = "CN-APPLY-{}".format(uuid.uuid4().hex[:6])
        corridor_id, junctions = _corridor(db, name, count=2, ports=[s.port for s in servers])
        plan = GreenWavePlanner.propose(db, corridor_id, actor="t", design_speed_kph=50,
                                        movements=_volumes(junctions))
        assert plan["status"] == "PROPOSED", plan
    finally:
        db.close()
    yield {"servers": servers, "plan": plan, "corridor_id": corridor_id, "junctions": junctions}
    for server in servers:
        try:
            server.stop()
        except OSError:
            pass


def test_applying_writes_each_controller_through_the_dispatcher_and_reads_it_back(headers, coordinated_corridor):
    plan = coordinated_corridor["plan"]
    body = client.post("/api/v1/coordination/plans/{}/apply".format(plan["plan_id"]),
                       headers=headers["cn_engineer"]).json()

    assert body["status"] == "APPLIED"
    dispatched = body["apply_results"]["dispatched"]
    assert len(dispatched) == 2
    for outcome in dispatched:
        assert outcome["status"] == "EXECUTED"
        assert outcome["readback_matches"] is True

    for server, junction in zip(coordinated_corridor["servers"], plan["junction_plans"]):
        state = server.emulator.state()
        assert state["coordinated"] is True and state["active_pattern"] == 1
        assert server.emulator.read_oid(ntcip.pattern_oid(ntcip.COL_PATTERN_OFFSET_TIME, 1)) == junction["offset_sec"]

    db = SessionLocal()
    try:
        commands = db.query(SignalCommand).filter(
            SignalCommand.id.in_([d["command_id"] for d in dispatched])
        ).all()
        assert {c.command_type for c in commands} == {"TIMING_PLAN"}
        assert all(c.safety_check_passed for c in commands)
        audits = db.query(AuditLog).filter(AuditLog.resource_id.in_([c.id for c in commands])).all()
        assert {a.action for a in audits} == {"TIMING_PLAN_WRITTEN"}
        assert {a.result for a in audits} == {"EXECUTED"}
    finally:
        db.close()

    again = client.post("/api/v1/coordination/plans/{}/apply".format(plan["plan_id"]),
                        headers=headers["cn_engineer"])
    assert again.status_code == 409, "an applied plan is not re-applied"


def test_a_controller_that_changed_state_since_proposal_blocks_the_whole_plan(headers, coordinated_corridor):
    """A half-applied green wave is worse than none, so nothing is sent."""
    plan = coordinated_corridor["plan"]
    db = SessionLocal()
    try:
        controller = db.query(SignalController).filter(
            SignalController.id == plan["junction_plans"][1]["controller_id"]
        ).first()
        controller.connection_status = "DISCONNECTED"
        db.commit()
    finally:
        db.close()

    body = client.post("/api/v1/coordination/plans/{}/apply".format(plan["plan_id"]),
                       headers=headers["cn_engineer"]).json()
    assert body["status"] == "REJECTED_AT_APPLY"
    assert body["apply_results"]["dispatched"] == []
    for server in coordinated_corridor["servers"]:
        assert server.emulator.state()["coordinated"] is False, "nothing reached any controller"


def test_a_controller_that_stops_answering_leaves_the_plan_partially_applied(headers, coordinated_corridor):
    plan = coordinated_corridor["plan"]
    coordinated_corridor["servers"][1].stop()   # still CONNECTED in the database

    body = client.post("/api/v1/coordination/plans/{}/apply".format(plan["plan_id"]),
                       headers=headers["cn_engineer"]).json()
    assert body["status"] == "PARTIALLY_APPLIED"
    statuses = [d["status"] for d in body["apply_results"]["dispatched"]]
    assert statuses == ["EXECUTED", "FAILED"]


def test_applying_a_timing_plan_needs_signal_configure(headers, coordinated_corridor):
    """Operators hold phases; changing how a controller runs every cycle is engineering."""
    plan = coordinated_corridor["plan"]
    for user in ("cn_operator", "cn_viewer"):
        response = client.post("/api/v1/coordination/plans/{}/apply".format(plan["plan_id"]),
                               headers=headers[user])
        assert response.status_code == 403, user


# ===========================================================================
# Verifying a plan against what the stringline observes
# ===========================================================================

def _observed_greens(db, controller_id, intersection_id, offset, cycle=90, green=40, cycles=6):
    """Test fixture: SignalStateLog rows as a controller running `offset` would produce."""
    base = _naive(_utcnow()) - timedelta(seconds=cycles * cycle + 30)
    anchor = base - timedelta(seconds=(base.timestamp() - offset) % cycle)
    t = anchor
    end = _naive(_utcnow())
    while t < end:
        position = ((t - anchor).total_seconds()) % cycle
        greens = [2, 6] if position < green else [4, 8]
        db.add(SignalStateLog(controller_id=controller_id, intersection_id=intersection_id,
                              timestamp=t, green_phases=greens, yellow_phases=[], red_phases=[],
                              source="NTCIP_1202_POLL"))
        t += timedelta(seconds=2)
    db.commit()


def _applied_plan(db, name, offsets):
    corridor_id, junctions = _corridor(db, name, count=2, ports=[1, 2])
    controllers = [db.query(SignalController).filter(SignalController.intersection_id == j).first()
                   for j in junctions]
    names = [db.query(Intersection).filter(Intersection.id == j).first().name for j in junctions]
    plan = CoordinationPlan(
        corridor_id=corridor_id, status="APPLIED", direction="ASCENDING",
        design_speed_kph=50, speed_basis="OPERATOR_ENTERED", cycle_sec=90,
        cycle_basis="OPERATOR_ENTERED", coord_phase=2, created_by="t",
        junction_plans=[
            {"intersection_id": j, "name": n, "controller_id": c.id, "offset_sec": o,
             "cycle_sec": 90, "coord_phase": 2, "splits": {"2": 46, "6": 46, "4": 44, "8": 44}}
            for j, n, c, o in zip(junctions, names, controllers, offsets)
        ],
    )
    db.add(plan)
    db.commit()
    return plan.id, junctions, controllers


def test_verify_confirms_offsets_the_stringline_actually_observes():
    db = SessionLocal()
    try:
        plan_id, junctions, controllers = _applied_plan(db, "CN-VERIFY-OK", [0, 32])
        for jid, controller, offset in zip(junctions, controllers, [0, 32]):
            _observed_greens(db, controller.id, jid, offset)
        result = GreenWavePlanner.verify(db, plan_id, minutes=15)
    finally:
        db.close()
    assert result["status"] == "OBSERVED_AS_PLANNED", result
    assert result["segments"][0]["planned_offset_sec"] == 32


def test_verify_reports_a_controller_observed_off_plan():
    """E.g. unsynchronised clocks: the plan was written, but not what runs."""
    db = SessionLocal()
    try:
        plan_id, junctions, controllers = _applied_plan(db, "CN-VERIFY-OFF", [0, 32])
        for jid, controller, offset in zip(junctions, controllers, [0, 60]):
            _observed_greens(db, controller.id, jid, offset)
        result = GreenWavePlanner.verify(db, plan_id, minutes=15)
    finally:
        db.close()
    assert result["status"] == "DIVERGES_FROM_PLAN"
    assert "time reference" in result["detail"]


def test_verify_before_applying_is_not_applicable():
    db = SessionLocal()
    try:
        plan_id, *_ = _applied_plan(db, "CN-VERIFY-NA", [0, 32])
        db.query(CoordinationPlan).filter(CoordinationPlan.id == plan_id).update({"status": "PROPOSED"})
        db.commit()
        result = GreenWavePlanner.verify(db, plan_id)
    finally:
        db.close()
    assert result["status"] == "NOT_APPLICABLE"


# ===========================================================================
# The single path to hardware
# ===========================================================================

def test_only_the_dispatcher_calls_an_adapter_to_change_a_controller():
    """Structural, not behavioural: a second call site would be a second path
    around the Safety Engine, and this test fails the moment one appears."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parents[1] / "app"
    pattern = re.compile(r"\.(send_command|write_timing_plan)\(")
    callers = set()
    for path in root.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if pattern.search(line) and not line.strip().startswith("def "):
                callers.add(path.relative_to(root).as_posix())
    assert callers == {"signals/dispatch.py"}, callers


# ===========================================================================
# Emergency vehicle preemption: manual and AVL
# ===========================================================================

from app.emergency.nmea import build_rmc  # noqa: E402
from app.emergency.preemption import MAX_POSITION_AGE_SEC  # noqa: E402
from app.models.entities import EmergencyEvent, TransitEvent  # noqa: E402

JUNCTION_LAT, JUNCTION_LON = 12.5, 78.0
METRES_PER_DEG_LAT = 111_320.0


def _signalised_junction(db, code, port, active_phase=2, status="CONNECTED"):
    """A junction with NB (phase 2) and SB (phase 6) mapped; no EB/WB lanes."""
    inter = Intersection(name="EVP {}".format(code), code=code, latitude=JUNCTION_LAT,
                         longitude=JUNCTION_LON, operational_status="HEALTHY")
    db.add(inter)
    db.flush()
    for direction, phase in (("NORTHBOUND", 2), ("SOUTHBOUND", 6)):
        approach = Approach(intersection_id=inter.id, direction=direction, road_name="Main St")
        db.add(approach)
        db.flush()
        db.add(Lane(approach_id=approach.id, lane_number=1, movement_type="THRU", assigned_phase=phase))
    controller = _controller(db, inter.id, port, status=status)
    controller.active_phase = active_phase
    controller.current_phase_start = _naive(_utcnow()) - timedelta(seconds=30)
    db.commit()
    return inter.id, controller.id


@pytest.fixture
def evp_site():
    """Each test gets its own junction and emulator, isolated by location."""
    server = _emulator()
    db = SessionLocal()
    try:
        # Remove any earlier EVP junction sharing these coordinates.
        for old in db.query(Intersection).filter(Intersection.latitude == JUNCTION_LAT,
                                                 Intersection.longitude == JUNCTION_LON).all():
            old.latitude, old.longitude = -45.0, -45.0
        db.commit()
        jid, cid = _signalised_junction(db, "EVP-{}".format(uuid.uuid4().hex[:6]), server.port)
    finally:
        db.close()
    yield {"server": server, "intersection_id": jid, "controller_id": cid}
    try:
        server.stop()
    except OSError:
        pass


def _south_of_junction(metres):
    return JUNCTION_LAT - metres / METRES_PER_DEG_LAT, JUNCTION_LON


def _avl(headers, user="cn_operator", **fields):
    return client.post("/api/v1/emergency/avl", json=fields, headers=headers[user])


def test_manual_preemption_now_actually_reaches_the_controller(headers, evp_site):
    """The replaced endpoint audited EXECUTED without sending anything."""
    body = client.post("/api/v1/emergency", headers=headers["cn_operator"], json={
        "intersection_id": evp_site["intersection_id"], "vehicle_id": "MED-1",
        "vehicle_type": "AMBULANCE", "requested_phase": 2,
    }).json()

    assert body["status"] == "ACTIVE"
    assert body["command_status"] == "EXECUTED"
    assert evp_site["server"].emulator.read_oid(
        ntcip.control_group_oid(ntcip.COL_CONTROL_GROUP_HOLD, 1)) == 0b10, "the hold is on the wire"

    db = SessionLocal()
    try:
        command = db.query(SignalCommand).filter(SignalCommand.id == body["command_id"]).first()
        assert command.command_type == "PREEMPTION" and command.status == "EXECUTED"
        audit = db.query(AuditLog).filter(AuditLog.resource_id == body["event_id"]).first()
        assert audit.action == "EMERGENCY_PREEMPTION_REQUESTED" and audit.result == "EXECUTED"
    finally:
        db.close()


def test_a_preemption_the_controller_never_acknowledged_is_failed_not_active(headers, evp_site):
    evp_site["server"].stop()
    body = client.post("/api/v1/emergency", headers=headers["cn_operator"], json={
        "intersection_id": evp_site["intersection_id"], "vehicle_id": "MED-2",
        "vehicle_type": "AMBULANCE", "requested_phase": 2,
    }).json()
    assert body["safety_clearance_passed"] is True
    assert body["status"] == "FAILED"

    db = SessionLocal()
    try:
        audit = db.query(AuditLog).filter(AuditLog.resource_id == body["event_id"]).first()
        assert audit.result == "FAILED", "the audit records what happened, not what was asked"
    finally:
        db.close()


def test_an_approaching_ambulance_preempts_the_phase_serving_its_approach(headers, evp_site):
    lat, lon = _south_of_junction(300)
    sentence = build_rmc(lat, lon, speed_kph=50, heading_deg=0.0, when=_utcnow())
    body = _avl(headers, vehicle_id="MED-3", vehicle_type="AMBULANCE", nmea=sentence).json()

    assert body["decision"] == "PREEMPTION_ACTIVE", body
    assert body["target"]["intersection_id"] == evp_site["intersection_id"]
    assert body["target"]["approach"] == "NORTHBOUND"
    assert body["requested_phase"] == 2
    assert 18 <= body["target"]["eta_sec"] <= 25
    assert body["hold_sec"] == math.ceil(body["target"]["eta_sec"]) + 5

    db = SessionLocal()
    try:
        event = db.query(EmergencyEvent).filter(EmergencyEvent.id == body["event"]["event_id"]).first()
        assert event.trigger == "AVL" and event.status == "ACTIVE"
        assert event.latitude == pytest.approx(lat, abs=1e-4)
        command = db.query(SignalCommand).filter(SignalCommand.id == event.command_id).first()
        assert command.command_type == "PREEMPTION", "same command path as a manual call"
    finally:
        db.close()


def test_the_same_vehicle_is_not_preempted_twice_within_the_rearm_window(headers, evp_site):
    lat, lon = _south_of_junction(300)
    for expected in ("PREEMPTION_ACTIVE", "ALREADY_PREEMPTED"):
        sentence = build_rmc(lat, lon, speed_kph=50, heading_deg=0.0, when=_utcnow())
        assert _avl(headers, vehicle_id="MED-4", vehicle_type="AMBULANCE",
                    nmea=sentence).json()["decision"] == expected


def test_preemption_that_would_conflict_is_rejected_and_nothing_is_sent(headers, evp_site):
    """Priority, never permission: the cross street is green."""
    db = SessionLocal()
    try:
        controller = db.query(SignalController).filter(SignalController.id == evp_site["controller_id"]).first()
        controller.active_phase = 4
        db.commit()
    finally:
        db.close()

    lat, lon = _south_of_junction(300)
    body = _avl(headers, vehicle_id="MED-5", vehicle_type="AMBULANCE",
                nmea=build_rmc(lat, lon, 50, 0.0, _utcnow())).json()
    assert body["decision"] == "REJECTED_BY_SAFETY_ENGINE"
    assert any("conflicts with active Phase" in v for v in body["event"]["violations"])
    assert evp_site["server"].emulator.read_oid(
        ntcip.control_group_oid(ntcip.COL_CONTROL_GROUP_HOLD, 1)) == 0, "nothing reached the wire"


def test_a_stale_position_is_not_acted_on_and_the_refusal_is_audited(headers, evp_site):
    lat, lon = _south_of_junction(300)
    old = _utcnow() - timedelta(seconds=MAX_POSITION_AGE_SEC + 20)
    body = _avl(headers, vehicle_id="MED-6", vehicle_type="AMBULANCE",
                nmea=build_rmc(lat, lon, 50, 0.0, old)).json()
    assert body["decision"] == "POSITION_TOO_OLD"
    assert body["event"] is None

    db = SessionLocal()
    try:
        audit = (db.query(AuditLog).filter(AuditLog.action == "AVL_REPORT_NOT_ACTED_ON",
                                           AuditLog.resource_id == "MED-6").first())
        assert audit is not None and audit.result == "POSITION_TOO_OLD"
    finally:
        db.close()


def test_a_corrupted_or_fixless_sentence_is_refused(headers, evp_site):
    lat, lon = _south_of_junction(300)
    good = build_rmc(lat, lon, 50, 0.0, _utcnow())
    corrupted = good[:20] + ("9" if good[20] != "9" else "8") + good[21:]
    response = _avl(headers, vehicle_id="MED-7", vehicle_type="AMBULANCE", nmea=corrupted)
    assert response.status_code == 422
    assert response.json()["detail"]["decision"] == "CHECKSUM_MISMATCH"

    void = build_rmc(lat, lon, 50, 0.0, _utcnow(), status="V")
    response = _avl(headers, vehicle_id="MED-7", vehicle_type="AMBULANCE", nmea=void)
    assert response.json()["detail"]["decision"] == "NO_GPS_FIX"


def test_a_vehicle_heading_away_or_too_far_triggers_nothing(headers, evp_site):
    lat, lon = _south_of_junction(300)
    away = _avl(headers, vehicle_id="MED-8", vehicle_type="AMBULANCE",
                nmea=build_rmc(lat, lon, 50, 180.0, _utcnow())).json()
    assert away["decision"] == "NO_JUNCTION_APPROACHED"

    lat, lon = _south_of_junction(550)
    slow = _avl(headers, vehicle_id="MED-8", vehicle_type="AMBULANCE",
                nmea=build_rmc(lat, lon, 20, 0.0, _utcnow())).json()
    assert slow["decision"] == "NO_JUNCTION_APPROACHED", "ETA beyond the window"


def test_an_unmapped_approach_is_rejected_with_the_gap_named(headers, evp_site):
    """Travelling east: the eastbound approach has no phase-mapped lane."""
    lat, lon = JUNCTION_LAT, JUNCTION_LON - 300 / (METRES_PER_DEG_LAT * math.cos(math.radians(JUNCTION_LAT)))
    body = _avl(headers, vehicle_id="MED-9", vehicle_type="FIRE_TRUCK",
                nmea=build_rmc(lat, lon, 50, 90.0, _utcnow())).json()
    assert body["decision"] == "NO_PHASE_SERVES_APPROACH"
    assert body["event"]["status"] == "REJECTED"
    assert "guessed phase" in body["detail"]


def test_only_authorised_vehicle_types_can_preempt(headers, evp_site):
    lat, lon = _south_of_junction(300)
    body = _avl(headers, vehicle_id="TAXI-1", vehicle_type="TAXI",
                nmea=build_rmc(lat, lon, 50, 0.0, _utcnow())).json()
    assert body["decision"] == "UNAUTHORIZED_VEHICLE_TYPE"


def test_avl_preemption_requires_signal_command(headers, evp_site):
    lat, lon = _south_of_junction(300)
    for user in ("cn_viewer",):
        response = _avl(headers, user=user, vehicle_id="MED-10", vehicle_type="AMBULANCE",
                        nmea=build_rmc(lat, lon, 50, 0.0, _utcnow()))
        assert response.status_code == 403


# ===========================================================================
# Conditional transit signal priority
# ===========================================================================

import base64  # noqa: E402

from app.providers.gtfs_rt import encode_feed  # noqa: E402


@pytest.fixture
def tsp_site():
    server = _emulator()
    db = SessionLocal()
    try:
        for old in db.query(Intersection).filter(Intersection.latitude == JUNCTION_LAT,
                                                 Intersection.longitude == JUNCTION_LON).all():
            old.latitude, old.longitude = -45.0, -45.0
        db.commit()
        jid, cid = _signalised_junction(db, "TSP-{}".format(uuid.uuid4().hex[:6]), server.port)
    finally:
        db.close()
    yield {"server": server, "intersection_id": jid, "controller_id": cid}
    try:
        server.stop()
    except OSError:
        pass


def _signal_state(controller_id, intersection_id, greens, age_sec=1.0):
    db = SessionLocal()
    try:
        db.add(SignalStateLog(controller_id=controller_id, intersection_id=intersection_id,
                              timestamp=_naive(_utcnow()) - timedelta(seconds=age_sec),
                              green_phases=greens, yellow_phases=[], red_phases=[],
                              source="NTCIP_1202_POLL"))
        db.commit()
    finally:
        db.close()


def _bus_feed(delay=None, stop_delay=None, age=2, bearing=0.0, metres=150, vehicle="BUS-7", trip="T-7"):
    lat, lon = _south_of_junction(metres)
    stamp = int(_utcnow().timestamp()) - age
    vehicles = [{"trip_id": trip, "route_id": "R12", "latitude": lat, "longitude": lon,
                 "bearing_deg": bearing, "speed_mps": 8.0, "timestamp": stamp, "vehicle_id": vehicle}]
    updates = []
    if delay is not None or stop_delay is not None:
        updates.append({"trip_id": trip, "delay_sec": delay, "stop_delay_sec": stop_delay})
    return {
        "vehicle_positions_b64": base64.b64encode(encode_feed(stamp, vehicles=vehicles)).decode(),
        "trip_updates_b64": base64.b64encode(encode_feed(stamp, trip_updates=updates)).decode(),
    }


def _tsp(headers, feed, dry_run=True, user="cn_operator"):
    return client.post("/api/v1/transit/tsp/evaluate-feed?dry_run={}".format(str(dry_run).lower()),
                       json=feed, headers=headers[user])


def test_without_a_configured_feed_no_bus_is_invented(headers):
    body = client.post("/api/v1/transit/tsp/evaluate", headers=headers["cn_operator"]).json()
    assert body["status"] == "TRANSIT_FEED_NOT_CONFIGURED"
    assert body["decisions"] == []
    listing = client.get("/api/v1/transit", headers=headers["cn_operator"]).json()
    assert listing["feed_configured"] is False
    assert "Connected" not in listing["message"]


def test_a_dry_run_describes_the_request_and_writes_nothing(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    db = SessionLocal()
    before = (db.query(TransitEvent).count(), db.query(SignalCommand).count())
    db.close()

    body = _tsp(headers, _bus_feed(delay=150)).json()
    decision = body["decisions"][0]
    assert decision["decision"] == "WOULD_REQUEST_GREEN_EXTENSION"
    assert decision["requested_phase"] == 2

    db = SessionLocal()
    after = (db.query(TransitEvent).count(), db.query(SignalCommand).count())
    db.close()
    assert after == before


def test_a_late_bus_on_a_green_approach_gets_an_extension_through_the_dispatcher(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    decision = _tsp(headers, _bus_feed(delay=150), dry_run=False).json()["decisions"][0]
    assert decision["decision"] == "GRANTED_GREEN_EXTENSION", decision

    db = SessionLocal()
    try:
        event = db.query(TransitEvent).filter(TransitEvent.vehicle_id == "BUS-7",
                                              TransitEvent.intersection_id == tsp_site["intersection_id"]).first()
        assert event.priority_granted is True and event.delay_seconds == 150
        command = db.query(SignalCommand).filter(SignalCommand.id == event.command_id).first()
        assert command.command_type == "TSP_GREEN_EXTENSION" and command.status == "EXECUTED"
    finally:
        db.close()
    assert tsp_site["server"].emulator.read_oid(
        ntcip.control_group_oid(ntcip.COL_CONTROL_GROUP_HOLD, 1)) == 0b10


def test_an_on_time_or_early_bus_gets_no_priority(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    on_time = _tsp(headers, _bus_feed(delay=20), dry_run=False).json()["decisions"][0]
    assert on_time["decision"] == "NOT_LATE_ENOUGH"
    early = _tsp(headers, _bus_feed(delay=-90, vehicle="BUS-8", trip="T-8"), dry_run=False).json()["decisions"][0]
    assert early["decision"] == "NOT_LATE_ENOUGH" and "ahead of" in early["detail"]


def test_lateness_from_the_next_stop_is_used_when_the_trip_has_none(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    decision = _tsp(headers, _bus_feed(stop_delay=200)).json()["decisions"][0]
    assert decision["decision"] == "WOULD_REQUEST_GREEN_EXTENSION"
    assert decision["delay_sec"] == 200


def test_unknown_lateness_is_not_treated_as_late(headers, tsp_site):
    """Conditional TSP grants on lateness; unknown is not late."""
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    decision = _tsp(headers, _bus_feed(), dry_run=False).json()["decisions"][0]
    assert decision["decision"] == "NO_SCHEDULE_ADHERENCE_DATA"


def test_a_bus_arriving_on_red_is_not_given_a_hold_that_would_do_nothing(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [4, 8])
    decision = _tsp(headers, _bus_feed(delay=150), dry_run=False).json()["decisions"][0]
    assert decision["decision"] == "EARLY_GREEN_NOT_SUPPORTED"
    assert "force-off" in decision["detail"]


def test_priority_is_never_requested_blind(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6], age_sec=60)
    decision = _tsp(headers, _bus_feed(delay=150), dry_run=False).json()["decisions"][0]
    assert decision["decision"] == "SIGNAL_STATE_UNKNOWN"


def test_a_junction_recovers_between_grants(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    first = _tsp(headers, _bus_feed(delay=150), dry_run=False).json()["decisions"][0]
    second = _tsp(headers, _bus_feed(delay=150, vehicle="BUS-9", trip="T-9"), dry_run=False).json()["decisions"][0]
    assert first["decision"] == "GRANTED_GREEN_EXTENSION"
    assert second["decision"] == "LOCKOUT_ACTIVE"


def test_stale_or_headingless_positions_are_refused(headers, tsp_site):
    stale = _tsp(headers, _bus_feed(delay=150, age=120)).json()["decisions"][0]
    assert stale["decision"] == "POSITION_TOO_OLD"
    feed = _bus_feed(delay=150, bearing=None)
    assert _tsp(headers, feed).json()["decisions"][0]["decision"] == "NO_HEADING"


def test_the_safety_engine_still_decides(headers, tsp_site):
    db = SessionLocal()
    try:
        controller = db.query(SignalController).filter(SignalController.id == tsp_site["controller_id"]).first()
        controller.connection_status = "REACHABLE"
        db.commit()
    finally:
        db.close()
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    decision = _tsp(headers, _bus_feed(delay=150), dry_run=False).json()["decisions"][0]
    assert decision["decision"] == "REJECTED_BY_SAFETY_ENGINE"
    assert tsp_site["server"].emulator.read_oid(
        ntcip.control_group_oid(ntcip.COL_CONTROL_GROUP_HOLD, 1)) == 0


def test_dispatching_priority_needs_signal_command_but_a_dry_run_does_not(headers, tsp_site):
    _signal_state(tsp_site["controller_id"], tsp_site["intersection_id"], [2, 6])
    assert _tsp(headers, _bus_feed(delay=150), dry_run=False, user="cn_viewer").status_code == 403
    assert _tsp(headers, _bus_feed(delay=150), dry_run=True, user="cn_viewer").status_code == 200


def test_a_malformed_feed_is_rejected(headers):
    response = client.post("/api/v1/transit/tsp/evaluate-feed", headers=headers["cn_operator"],
                           json={"vehicle_positions_b64": base64.b64encode(b"\x0a\xff\xff").decode()})
    assert response.status_code == 422


def test_avl_position_reports_are_not_throttled_at_the_signal_command_rate(headers, evp_site):
    """An AVL unit at 1 Hz must not be cut off after twelve reports."""
    from app.governance.rate_limit import policy_for_request, SIGNAL_COMMAND_POLICY

    assert policy_for_request("POST", "/api/v1/emergency/avl").name == "avl_report"
    assert policy_for_request("POST", "/api/v1/emergency") is SIGNAL_COMMAND_POLICY

    lat, lon = _south_of_junction(300)
    statuses = []
    for _ in range(SIGNAL_COMMAND_POLICY.max_requests + 8):
        response = _avl(headers, vehicle_id="MED-RATE", vehicle_type="AMBULANCE",
                        nmea=build_rmc(lat, lon, 50, 180.0, _utcnow()))
        statuses.append(response.status_code)
    assert set(statuses) == {200}, statuses
