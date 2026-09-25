"""TRAFFICINTEL AI - Arterial Coordination (Green-Wave) Planner

Extends the single-junction Webster optimiser to a corridor: one common cycle,
Webster splits at every junction within it, and offsets that let a platoon
travelling at the design speed meet successive greens.

Truthfulness rules this module keeps
------------------------------------
* **Only real, readable controllers are coordinated.** A junction counts only
  when its controller speaks NTCIP 1202 (the one protocol with a timing-plan
  channel) and is CONNECTED. Fewer than two such junctions is NOT_COMPUTABLE -
  the same refusal pattern as the stringline, for the same reason: a green wave
  needs at least two signals whose timing can actually be set.
* **Design speed is never measured and says so.** It is either entered by the
  operator or taken from the configured speed limit, and labelled accordingly.
* **Splits come from demand, not from a default.** Volumes are operator-entered
  or measured (subject to the same trust gate as the single-junction
  optimiser). With neither, the junction is refused rather than split evenly.
* **Bandwidth is computed, both directions.** Optimising one direction usually
  costs the other; the plan reports both instead of only the flattering one.
* **Every plan passes the Safety Engine before it is stored as applicable,
  and again at the moment of application.** Nothing here writes to hardware;
  application goes through SignalCommandDispatcher.
* **Offsets assume a shared time reference.** Controllers must be synchronised
  (GPS/NTP) for offsets to mean anything. The platform cannot verify that from
  here, so after applying, `verify` compares planned offsets with the offsets
  the stringline actually observes.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.analytics.stringline import Stringline, haversine_m
from app.analytics.trust import TrustScore
from app.models.entities import (
    Approach, CoordinationPlan, Corridor, SignalController, utc_now,
)
from app.optimization.webster import MovementDemand, WebsterOptimizer
from app.safety.safety_engine import DeterministicSafetyEngine
from app.signals.dispatch import SignalCommandDispatcher

METHOD_VERSION = "green-wave-webster-v1"
TIMING_PROTOCOLS = DeterministicSafetyEngine.TIMING_PLAN_PROTOCOLS
BANDWIDTH_STEP_SEC = 0.1
PATTERN_NUMBER = 1
#: Planned vs observed offset agreement tolerance, beyond the measurement
#: resolution the stringline reports.
VERIFY_TOLERANCE_SEC = 3.0


def _coordination_key(plan_id: str, controller_id: str) -> str:
    """Idempotency key for one controller's part of one plan.

    Deterministic, so re-applying the same plan to the same controller is caught
    as a duplicate; hashed, so it fits signal_commands.idempotency_key (64).
    Two UUIDs concatenated do not - SQLite stored them silently, PostgreSQL
    rejected them, which is how this was found.
    """
    digest = hashlib.sha256("{}:{}".format(plan_id, controller_id).encode()).hexdigest()
    return "coord-" + digest[:48]


def _junction_order(corridor: Corridor) -> Tuple[List[Any], Dict[str, float]]:
    """Corridor junctions and their positions - identical to the stringline's,
    so the offsets planned here are the offsets the stringline measures."""
    junctions = sorted(corridor.intersections, key=lambda i: (i.latitude, i.longitude))
    positions: Dict[str, float] = {}
    cumulative = 0.0
    for index, junction in enumerate(junctions):
        if index:
            previous = junctions[index - 1]
            cumulative += haversine_m(previous.latitude, previous.longitude,
                                      junction.latitude, junction.longitude)
        positions[junction.id] = round(cumulative, 1)
    return junctions, positions


def _controller_for(db: Session, intersection_id: str) -> Optional[SignalController]:
    return db.query(SignalController).filter(
        SignalController.intersection_id == intersection_id
    ).first()


def _band(windows: List[Tuple[float, float, float]], cycle: int) -> float:
    """Bandwidth in seconds: departure times t in [0, C) that meet every green.

    `windows` holds (travel_time_from_origin, green_start_offset, green_length)
    per junction. Evaluated numerically at BANDWIDTH_STEP_SEC resolution, which
    is finer than any controller's timing unit.
    """
    steps = int(cycle / BANDWIDTH_STEP_SEC)
    inside = 0
    for k in range(steps):
        t = k * BANDWIDTH_STEP_SEC
        if all(((t + travel - offset) % cycle) < green for travel, offset, green in windows):
            inside += 1
    return round(inside * BANDWIDTH_STEP_SEC, 1)


class GreenWavePlanner:
    """Proposes, applies and verifies corridor coordination plans."""

    # ------------------------------------------------------------------
    # Propose
    # ------------------------------------------------------------------

    @classmethod
    def propose(
        cls,
        db: Session,
        corridor_id: str,
        actor: str,
        direction: str = "ASCENDING",
        design_speed_kph: Optional[float] = None,
        cycle_sec: Optional[int] = None,
        coord_phase: int = 2,
        movements: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        measured_window_minutes: int = 60,
    ) -> Dict[str, Any]:
        corridor = db.query(Corridor).filter(Corridor.id == corridor_id).first()
        if corridor is None:
            return {"status": "NOT_FOUND", "detail": "No such corridor."}
        direction = (direction or "ASCENDING").upper()
        if direction not in ("ASCENDING", "DESCENDING"):
            raise ValueError("direction must be ASCENDING or DESCENDING")
        movements = movements or {}

        junctions, positions = _junction_order(corridor)
        base = {
            "corridor_id": corridor.id,
            "corridor_name": corridor.name,
            "method_version": METHOD_VERSION,
            "direction": direction,
            "coord_phase": coord_phase,
        }

        # --- eligibility --------------------------------------------------
        eligible, uncoordinated = [], []
        for junction in junctions:
            controller = _controller_for(db, junction.id)
            reason = None
            if controller is None:
                reason = "NO_CONTROLLER"
            elif (controller.protocol or "").upper() not in TIMING_PROTOCOLS:
                reason = "PROTOCOL_HAS_NO_TIMING_PLAN_CHANNEL"
            elif controller.connection_status != "CONNECTED":
                reason = "CONTROLLER_{}".format(controller.connection_status or "UNKNOWN")
            elif coord_phase not in {p.phase_number for p in controller.phases}:
                reason = "COORDINATED_PHASE_NOT_CONFIGURED"
            entry = {
                "intersection_id": junction.id,
                "name": junction.name,
                "position_m": positions[junction.id],
                "controller_id": controller.id if controller else None,
            }
            if reason:
                uncoordinated.append({**entry, "reason": reason})
            else:
                eligible.append({**entry, "controller": controller})

        if len(eligible) < 2:
            return {
                **base,
                "status": "NOT_COMPUTABLE",
                "reason": "FEWER_THAN_TWO_COORDINATABLE_CONTROLLERS",
                "detail": (
                    "A green wave needs at least two junctions whose controllers speak "
                    "NTCIP 1202 and are CONNECTED, so that their timing can actually be "
                    "set and read back. This corridor has {}.".format(len(eligible))
                ),
                "junction_count": len(junctions),
                "uncoordinated": uncoordinated,
            }

        # --- design speed ---------------------------------------------------
        if design_speed_kph is not None:
            speed, speed_basis = float(design_speed_kph), "OPERATOR_ENTERED"
        else:
            limits = [
                a.speed_limit_kph for j in eligible
                for a in db.query(Approach).filter(Approach.intersection_id == j["intersection_id"]).all()
                if a.speed_limit_kph
            ]
            if not limits:
                return {
                    **base,
                    "status": "NOT_COMPUTABLE",
                    "reason": "NO_DESIGN_SPEED",
                    "detail": (
                        "No design speed was entered and no approach on the coordinated "
                        "junctions has a configured speed limit. Enter a design speed; "
                        "the platform does not assume one."
                    ),
                    "uncoordinated": uncoordinated,
                }
            speed, speed_basis = float(min(limits)), "CONFIGURED_SPEED_LIMIT"
        if not (5.0 <= speed <= 130.0):
            raise ValueError("design_speed_kph must be between 5 and 130")

        # --- demand and each junction's own optimum -------------------------
        per_junction = []
        for junction in eligible:
            demand = cls._demand_for(db, junction, movements.get(junction["intersection_id"]),
                                     measured_window_minutes)
            if demand["status"] != "READY":
                return {
                    **base,
                    "status": "REFUSED",
                    "reason": demand["reason"],
                    "detail": "{}: {}".format(junction["name"], demand["detail"]),
                    "junction": junction["name"],
                    "uncoordinated": uncoordinated,
                }
            free = WebsterOptimizer.optimize(demand["critical"], lost_time_per_phase_sec=demand["lost_time"])
            if free.status != "COMPUTED":
                return {
                    **base,
                    "status": "REFUSED",
                    "reason": free.reason,
                    "detail": "{} cannot be timed: {}".format(junction["name"], free.reason),
                    "junction": junction["name"],
                    "trace": free.trace,
                    "uncoordinated": uncoordinated,
                }
            per_junction.append({
                **junction, "demand": demand, "optimum_cycle": free.cycle_length_sec,
                "minimum_feasible_cycle": cls._minimum_feasible_cycle(demand),
            })

        # --- common cycle -----------------------------------------------------
        # Webster's optimum ignores minimum greens and pedestrian intervals, so
        # on its own it can name a cycle no junction can physically run - found
        # on a live corridor, where a 40 s optimum met a 56 s pedestrian minimum
        # and the plan came out with a 6 s main-street green. The common cycle is
        # therefore never below the largest minimum feasible cycle.
        feasible_floor = max(j["minimum_feasible_cycle"] for j in per_junction)
        binding = max(per_junction, key=lambda j: j["minimum_feasible_cycle"])
        if cycle_sec is not None:
            if int(cycle_sec) < feasible_floor:
                return {
                    **base,
                    "status": "REFUSED",
                    "reason": "CYCLE_BELOW_MINIMUM_FEASIBLE",
                    "detail": (
                        "A {}s cycle cannot fit minimum green, pedestrian walk and clearance "
                        "at {}: its barrier groups need at least {}s. Enter {}s or more."
                        .format(cycle_sec, binding["name"], feasible_floor, feasible_floor)
                    ),
                    "minimum_feasible_cycle_sec": feasible_floor,
                    "uncoordinated": uncoordinated,
                }
            common, cycle_basis = int(cycle_sec), "OPERATOR_ENTERED"
        else:
            critical = max(per_junction, key=lambda j: j["optimum_cycle"])
            if critical["optimum_cycle"] >= feasible_floor:
                common = critical["optimum_cycle"]
                cycle_basis = "CRITICAL_JUNCTION_WEBSTER_OPTIMUM ({})".format(critical["name"])[:48]
            else:
                common = feasible_floor
                cycle_basis = "MINIMUM_FEASIBLE ({})".format(binding["name"])[:48]

        # --- splits at the common cycle, and offsets -------------------------
        ordered = per_junction if direction == "ASCENDING" else list(reversed(per_junction))
        origin_position = ordered[0]["position_m"]
        speed_mps = speed / 3.6

        junction_plans = []
        for junction in ordered:
            demand = junction["demand"]
            result = WebsterOptimizer.optimize(
                demand["critical"], lost_time_per_phase_sec=demand["lost_time"],
                fixed_cycle_sec=common,
            )
            if result.status != "COMPUTED":
                return {
                    **base, "status": "REFUSED", "reason": result.reason,
                    "detail": "{} cannot run a {}s cycle: {}".format(junction["name"], common, result.reason),
                    "uncoordinated": uncoordinated,
                }
            splits = cls._phase_splits(junction["controller"], result, demand, common, coord_phase)
            travel = abs(junction["position_m"] - origin_position) / speed_mps
            offset = int(round(travel)) % common
            coord = next(p for p in junction["controller"].phases if p.phase_number == coord_phase)
            green = splits[coord_phase] - (coord.yellow_change or 0) - (coord.red_clearance or 0)
            junction_plans.append({
                "intersection_id": junction["intersection_id"],
                "name": junction["name"],
                "controller_id": junction["controller"].id,
                "position_m": junction["position_m"],
                "travel_time_from_origin_sec": round(travel, 1),
                "offset_sec": offset,
                "cycle_sec": common,
                "coord_phase": coord_phase,
                "coordinated_green_sec": green,
                "splits": {str(k): v for k, v in sorted(splits.items())},
                "own_optimum_cycle_sec": junction["optimum_cycle"],
                "minimum_feasible_cycle_sec": junction["minimum_feasible_cycle"],
                "demand_source": demand["source"],
                "webster_trace": result.trace,
            })

        bandwidth = cls._bandwidth(junction_plans, common, speed_mps)

        # --- Safety Engine, before the plan is stored as applicable ----------
        safety, all_pass = [], True
        for plan in junction_plans:
            controller = db.query(SignalController).filter(SignalController.id == plan["controller_id"]).first()
            verdict = DeterministicSafetyEngine.validate_timing_plan(
                controller=controller,
                cycle_sec=plan["cycle_sec"], offset_sec=plan["offset_sec"],
                splits=plan["splits"], coord_phase=plan["coord_phase"],
                issued_at=utc_now(),
                idempotency_key="preview-{}".format(uuid.uuid4()),
            )
            all_pass = all_pass and verdict.is_safe
            safety.append({
                "intersection_id": plan["intersection_id"], "name": plan["name"],
                "is_safe": verdict.is_safe, "violations": verdict.violations,
                "checks": [c.model_dump() for c in verdict.checks],
            })

        record = CoordinationPlan(
            corridor_id=corridor.id,
            status="PROPOSED" if all_pass else "REJECTED_BY_SAFETY",
            direction=direction,
            design_speed_kph=speed, speed_basis=speed_basis,
            cycle_sec=common, cycle_basis=cycle_basis, coord_phase=coord_phase,
            junction_plans=junction_plans, bandwidth=bandwidth,
            safety_summary={"all_passed": all_pass, "per_junction": safety},
            uncoordinated=uncoordinated, created_by=actor,
        )
        db.add(record)
        db.commit()
        return cls.serialize(record)

    @classmethod
    def _demand_for(cls, db, junction, supplied, window_minutes) -> Dict[str, Any]:
        """Critical movement per barrier group, from entered or measured volumes."""
        controller: SignalController = junction["controller"]
        phases = {p.phase_number: p for p in controller.phases}

        if supplied:
            rows, source = supplied, "OPERATOR_ENTERED"
        else:
            from app.api.v1.endpoints.optimizer import _measured_demand
            measured = _measured_demand(db, junction["intersection_id"], controller, window_minutes)
            if measured["status"] != "COMPUTED":
                return {"status": "REFUSED", "reason": measured["reason"], "detail": measured["detail"]}
            trust = TrustScore.for_intersection(db, junction["intersection_id"])
            if not trust["ai_gate"]["allowed"]:
                return {
                    "status": "REFUSED", "reason": "TRUST_SCORE_BELOW_AI_GATE",
                    "detail": (trust["ai_gate"]["reason"] or "Data quality is below the AI gate.")
                    + " Enter volumes for this junction to override: an operator-entered "
                    "volume is not gated.",
                }
            rows, source = measured["movements"], "MEASURED_DETECTOR"

        by_barrier: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            number = int(row["phase_number"])
            if number not in phases:
                return {"status": "REFUSED", "reason": "UNKNOWN_PHASE",
                        "detail": "Phase {} is not configured on this controller.".format(number)}
            by_barrier.setdefault(phases[number].barrier, []).append(row)

        barriers = sorted({p.barrier for p in phases.values()})
        missing = [b for b in barriers if b not in by_barrier]
        if missing:
            return {
                "status": "REFUSED", "reason": "NO_DEMAND_FOR_BARRIER_GROUP",
                "detail": (
                    "No volume for any phase in barrier group(s) {}. Every group needs a "
                    "demand to be split; the planner does not assume one.".format(missing)
                ),
            }

        critical, clearances = [], []
        for barrier in barriers:
            group_phases = [p for p in phases.values() if p.barrier == barrier]
            row = max(by_barrier[barrier],
                      key=lambda r: float(r["volume_vph"]) / max(1, int(r.get("lanes") or 1)))
            clearance = max((p.yellow_change or 0) + (p.red_clearance or 0) for p in group_phases)
            ped = max((p.ped_walk or 0) + (p.ped_clearance or 0) for p in group_phases)
            clearances.append(clearance)
            critical.append(MovementDemand(
                phase_number=int(row["phase_number"]),
                name=row.get("name") or "Barrier {} critical".format(barrier),
                volume_vph=float(row["volume_vph"]),
                lanes=int(row.get("lanes") or 1),
                min_green_sec=max(max(p.min_green or 0 for p in group_phases), ped),
                max_green_sec=min(p.max_green or 999 for p in group_phases),
                source=source,
                sample_size=int(row.get("sample_size") or 0),
            ))
        return {"status": "READY", "critical": critical, "lost_time": float(max(clearances)),
                "source": source}

    @classmethod
    def _phase_splits(cls, controller, result, demand, cycle, coord_phase) -> Dict[int, int]:
        """Integer per-phase splits that sum to the cycle in every ring.

        Each barrier group's split is its critical movement's effective green
        plus the group's clearance, and every phase in the group gets it - so
        both rings reach each barrier together by construction. Rounding
        remainder goes to the coordinated group.
        """
        phases = {p.phase_number: p for p in controller.phases}
        green_by_phase = {s["phase"]: s["effective_green_sec"] for s in result.splits}
        clearance = demand["lost_time"]
        barrier_of = {m.phase_number: phases[m.phase_number].barrier for m in demand["critical"]}
        barrier_split = {barrier_of[n]: int(round(g + clearance)) for n, g in green_by_phase.items()}

        coord_barrier = phases[coord_phase].barrier
        remainder = cycle - sum(barrier_split.values())
        # Only rounding error belongs here. A larger remainder means the greens
        # did not fit the cycle; absorbing it would silently shorten the
        # coordinated split below its minimum, which is what the feasibility
        # floor above exists to prevent.
        if abs(remainder) > len(barrier_split):
            raise ValueError(
                "Splits {} do not fit the {}s cycle (remainder {}s); the cycle is below "
                "this junction's minimum feasible cycle.".format(barrier_split, cycle, remainder)
            )
        barrier_split[coord_barrier] += remainder
        return {n: barrier_split[p.barrier] for n, p in phases.items()}

    @classmethod
    def _minimum_feasible_cycle(cls, demand: Dict[str, Any]) -> int:
        """Shortest cycle that fits every barrier group's minimum green (or
        pedestrian interval, whichever is longer) plus its clearance, rounded up
        to the next 5 s."""
        seconds = sum(m.min_green_sec for m in demand["critical"]) + demand["lost_time"] * len(demand["critical"])
        return int(-(-seconds // 5) * 5)

    @classmethod
    def _bandwidth(cls, plans: List[Dict[str, Any]], cycle: int, speed_mps: float) -> Dict[str, Any]:
        origin = plans[0]["position_m"]
        far = plans[-1]["position_m"]
        design = [(abs(p["position_m"] - origin) / speed_mps, p["offset_sec"], p["coordinated_green_sec"])
                  for p in plans]
        opposite = [(abs(far - p["position_m"]) / speed_mps, p["offset_sec"], p["coordinated_green_sec"])
                    for p in plans]
        design_band, opposite_band = _band(design, cycle), _band(opposite, cycle)
        return {
            "design_direction_sec": design_band,
            "design_direction_efficiency": round(design_band / cycle, 3),
            "opposite_direction_sec": opposite_band,
            "opposite_direction_efficiency": round(opposite_band / cycle, 3),
            "narrowest_coordinated_green_sec": min(p["coordinated_green_sec"] for p in plans),
            "basis": (
                "Computed at {}s resolution from the planned offsets and coordinated-phase "
                "greens, assuming vehicles travel at the design speed. Optimising one "
                "direction usually narrows the other; both are reported.".format(BANDWIDTH_STEP_SEC)
            ),
        }

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    @classmethod
    def apply(cls, db: Session, plan_id: str, actor_id: Optional[str], actor_name: str) -> Dict[str, Any]:
        plan = db.query(CoordinationPlan).filter(CoordinationPlan.id == plan_id).first()
        if plan is None:
            return {"status": "NOT_FOUND"}
        if plan.status != "PROPOSED":
            return {"status": "CONFLICT", "detail": (
                "Plan is {}; only a PROPOSED plan can be applied. Propose a new plan "
                "rather than re-applying a settled one.".format(plan.status))}

        # Pre-flight: the Safety Engine again, now, for every controller. State
        # may have changed since the proposal; nothing is sent unless every
        # controller would accept its part - a half-applied green wave is worse
        # than none, because it moves some junctions off their old timing
        # without the progression that justified it.
        preflight = []
        for junction in plan.junction_plans:
            controller = db.query(SignalController).filter(SignalController.id == junction["controller_id"]).first()
            verdict = DeterministicSafetyEngine.validate_timing_plan(
                controller=controller, cycle_sec=junction["cycle_sec"],
                offset_sec=junction["offset_sec"], splits=junction["splits"],
                coord_phase=junction["coord_phase"], issued_at=utc_now(),
                idempotency_key="preflight-{}".format(uuid.uuid4()),
            )
            preflight.append({"name": junction["name"], "is_safe": verdict.is_safe,
                              "violations": verdict.violations})
        if not all(p["is_safe"] for p in preflight):
            plan.status = "REJECTED_AT_APPLY"
            plan.apply_results = {"preflight": preflight, "dispatched": []}
            db.commit()
            return cls.serialize(plan)

        results = []
        for junction in plan.junction_plans:
            controller = db.query(SignalController).filter(SignalController.id == junction["controller_id"]).first()
            outcome = SignalCommandDispatcher.dispatch_timing_plan(
                db, controller,
                plan={
                    "pattern_number": PATTERN_NUMBER,
                    "cycle_sec": junction["cycle_sec"], "offset_sec": junction["offset_sec"],
                    "splits": {int(k): v for k, v in junction["splits"].items()},
                    "coord_phase": junction["coord_phase"],
                },
                idempotency_key=_coordination_key(plan.id, controller.id),
                actor_id=actor_id, actor_name=actor_name,
                context={"coordination_plan_id": plan.id},
            )
            results.append({
                "intersection_id": junction["intersection_id"], "name": junction["name"],
                "command_id": outcome.command.id, "status": outcome.status,
                "acknowledgement": outcome.acknowledgement,
                "readback_matches": bool(outcome.readback and outcome.readback.get("matches_request")),
                "readback": outcome.readback,
                "violations": outcome.safety.violations,
            })

        executed = sum(1 for r in results if r["status"] == "EXECUTED")
        plan.status = (
            "APPLIED" if executed == len(results)
            else "APPLY_FAILED" if executed == 0
            else "PARTIALLY_APPLIED"
        )
        plan.applied_by, plan.applied_at = actor_name, utc_now()
        plan.apply_results = {"preflight": preflight, "dispatched": results}
        db.commit()
        return cls.serialize(plan)

    # ------------------------------------------------------------------
    # Verify: planned offsets against offsets the stringline measured
    # ------------------------------------------------------------------

    @classmethod
    def verify(cls, db: Session, plan_id: str, minutes: int = 15) -> Dict[str, Any]:
        plan = db.query(CoordinationPlan).filter(CoordinationPlan.id == plan_id).first()
        if plan is None:
            return {"status": "NOT_FOUND"}
        if plan.status not in ("APPLIED", "PARTIALLY_APPLIED"):
            return {"status": "NOT_APPLICABLE", "detail": (
                "Plan is {}. Only an applied plan can be checked against what the "
                "controllers are observed doing.".format(plan.status))}

        stringline = Stringline.build(db, plan.corridor_id, minutes=minutes, phases=[plan.coord_phase])
        planned = {j["name"]: j["offset_sec"] for j in plan.junction_plans}
        cycle = plan.cycle_sec
        segments = []
        for segment in (stringline.get("progression") or {}).get("segments", []):
            up, down = segment.get("from"), segment.get("to")
            if up not in planned or down not in planned:
                continue
            expected = (planned[down] - planned[up]) % cycle
            observed = segment.get("median_offset_sec")
            resolution = segment.get("measurement_resolution_sec") or 0.0
            if observed is None:
                segments.append({"from": up, "to": down, "planned_offset_sec": expected,
                                 "status": "NOT_OBSERVED", "detail": segment.get("detail")})
                continue
            error = min(abs(observed % cycle - expected), cycle - abs(observed % cycle - expected))
            tolerance = VERIFY_TOLERANCE_SEC + resolution
            segments.append({
                "from": up, "to": down,
                "planned_offset_sec": expected,
                "observed_median_offset_sec": observed,
                "difference_sec": round(error, 2),
                "tolerance_sec": round(tolerance, 2),
                "status": "OBSERVED_AS_PLANNED" if error <= tolerance else "DIVERGES_FROM_PLAN",
            })

        statuses = {s["status"] for s in segments}
        if not segments:
            overall = "INSUFFICIENT_DATA"
        elif statuses == {"OBSERVED_AS_PLANNED"}:
            overall = "OBSERVED_AS_PLANNED"
        elif "DIVERGES_FROM_PLAN" in statuses:
            overall = "DIVERGES_FROM_PLAN"
        else:
            overall = "INSUFFICIENT_DATA"
        return {
            "status": overall,
            "plan_id": plan.id,
            "segments": segments,
            "stringline_status": stringline.get("status"),
            "detail": {
                "OBSERVED_AS_PLANNED": "Every adjacent pair's observed offset matches the plan.",
                "DIVERGES_FROM_PLAN": (
                    "At least one pair's observed offset differs from the plan. Controller "
                    "clocks may not share a time reference, or a controller has left the pattern."
                ),
                "INSUFFICIENT_DATA": (
                    "The stringline has not yet observed enough green starts to measure "
                    "offsets. Wait several cycles and verify again; this is not a failure."
                ),
            }[overall],
            "basis": "Offsets measured by the stringline from polled signal state, not read from the plan.",
        }

    # ------------------------------------------------------------------

    @classmethod
    def serialize(cls, plan: CoordinationPlan) -> Dict[str, Any]:
        return {
            "plan_id": plan.id,
            "corridor_id": plan.corridor_id,
            "status": plan.status,
            "direction": plan.direction,
            "design_speed_kph": plan.design_speed_kph,
            "speed_basis": plan.speed_basis,
            "cycle_sec": plan.cycle_sec,
            "cycle_basis": plan.cycle_basis,
            "coord_phase": plan.coord_phase,
            "junction_plans": plan.junction_plans,
            "bandwidth": plan.bandwidth,
            "safety": plan.safety_summary,
            "uncoordinated": plan.uncoordinated or [],
            "created_by": plan.created_by,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
            "applied_by": plan.applied_by,
            "applied_at": plan.applied_at.isoformat() if plan.applied_at else None,
            "apply_results": plan.apply_results,
            "time_reference_note": (
                "Offsets assume the controllers share a synchronised time reference "
                "(GPS or NTP). The platform cannot verify controller clock sync; use "
                "/coordination/plans/{id}/verify after applying to compare planned "
                "offsets with those the stringline observes."
            ),
            "method_version": METHOD_VERSION,
        }
