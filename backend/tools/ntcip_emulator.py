"""TRAFFICINTEL AI - NTCIP 1202 Signal Controller Emulator

A UDP SNMPv1 agent that speaks the NTCIP 1202 phase status and phase control
objects, backed by a real NEMA dual-ring barrier sequencer.

What this emulates and what it deliberately does not:

* It DOES emulate controller behaviour: a dual-ring sequence with real minimum
  green, yellow change and all-red clearance intervals, driven by a monotonic
  clock, and real phaseControlGroupHold handling. The phase state a client
  reads back is the genuine output of that state machine.

* It DOES NOT emulate traffic. It reports no vehicle counts, no occupancies, no
  speeds and no detector actuations, because inventing those would put
  fabricated measurements into the platform through the front door. The
  console will correctly show NO SENSOR DATA AVAILABLE while this emulator is
  the only thing connected. That is the intended demonstration.

Run it standalone:

    python -m tools.ntcip_emulator --host 127.0.0.1 --port 1610

then register a controller with protocol NTCIP_1202 pointing at that port.
"""

from __future__ import annotations

import argparse
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from app.providers import ntcip_objects as ntcip
from app.providers import snmp_codec as snmp

logger = logging.getLogger("trafficintel.ntcip_emulator")

# Interval names used by the sequencer.
GREEN = "GREEN"
YELLOW = "YELLOW"
RED_CLEARANCE = "RED_CLEARANCE"


@dataclass
class ConcurrentGroup:
    """One barrier group: the phases that may display green together."""

    phases: List[int]
    min_green_sec: float = 7.0
    max_green_sec: float = 45.0
    yellow_sec: float = 4.0
    red_clearance_sec: float = 2.0


@dataclass
class SignalControllerEmulator:
    """A deterministic NEMA dual-ring barrier sequencer.

    Phase state is a pure function of the monotonic clock and the hold register,
    so two reads inside the same interval agree, and the intervals advance in
    real time exactly as a fixed-time controller would.
    """

    groups: List[ConcurrentGroup] = field(
        default_factory=lambda: [
            ConcurrentGroup(phases=[2, 6]),  # main street through, ring 1 + ring 2
            ConcurrentGroup(phases=[4, 8]),  # cross street through
        ]
    )
    max_phases: int = 8
    status_group: int = 1

    _group_index: int = 0
    _interval: str = GREEN
    _interval_started: float = field(default_factory=time.monotonic)
    _hold_bitmap: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # -- coordination (NTCIP 1202 pattern and split tables) -----------------
    #: Wall clock shared by every emulator on the host - the stand-in for the
    #: GPS/NTP time reference field controllers synchronise offsets against.
    #: Injectable so tests can drive coordination deterministically.
    clock: Callable[[], float] = time.time
    max_patterns: int = 16
    max_splits: int = 16
    #: pattern -> {"cycle": s, "offset": s, "split_number": n}
    _patterns: Dict[int, Dict[str, int]] = field(default_factory=dict)
    #: (split_number, phase) -> seconds / coord flag
    _split_times: Dict[Tuple[int, int], int] = field(default_factory=dict)
    _split_coord: Dict[Tuple[int, int], int] = field(default_factory=dict)
    #: systemPatternControl: 0 = no pattern selected, i.e. free running.
    _system_pattern: int = 0
    #: A green extension granted under coordination: (cycle_index, group_pos, seconds)
    _extension: Optional[Tuple[int, int, float]] = None

    # -- sequencer ---------------------------------------------------------

    @property
    def _group(self) -> ConcurrentGroup:
        return self.groups[self._group_index]

    def _interval_length(self) -> float:
        group = self._group
        if self._interval == GREEN:
            return group.min_green_sec
        if self._interval == YELLOW:
            return group.yellow_sec
        return group.red_clearance_sec

    def _held_phases(self) -> List[int]:
        return ntcip.phase_bitmap_to_numbers(self._hold_bitmap, self.status_group)

    def _advance(self) -> None:
        """Advances the state machine up to the current clock reading."""
        now = time.monotonic()
        # Bounded loop: an idle emulator can be many intervals behind.
        for _ in range(1000):
            elapsed = now - self._interval_started
            limit = self._interval_length()

            if self._interval == GREEN:
                group = self._group
                held = set(self._held_phases()) & set(group.phases)
                # A hold extends green past its minimum, but never past max green.
                # This is the controller's own safety envelope, independent of
                # anything the central system asks for.
                if held and elapsed < group.max_green_sec:
                    return
                if elapsed < limit:
                    return
                self._interval = YELLOW
                self._interval_started = now - (elapsed - limit)
                continue

            if elapsed < limit:
                return

            if self._interval == YELLOW:
                self._interval = RED_CLEARANCE
            else:
                self._interval = GREEN
                self._group_index = (self._group_index + 1) % len(self.groups)
                # A hold does not survive the barrier crossing.
                self._hold_bitmap = 0
            self._interval_started = now - (elapsed - limit)

    # -- coordination ------------------------------------------------------

    def _coordinated_plan(self) -> Optional[Dict[str, object]]:
        """The active plan, if it forms a runnable schedule; else None (free).

        A real controller that is told to run an inconsistent pattern does not
        run it; neither does this one. It stays free, and coordPatternStatus
        reports FREE, so a read-back shows the plan did not take.
        """
        pattern = self._patterns.get(self._system_pattern)
        if not self._system_pattern or not pattern:
            return None
        cycle, offset = pattern.get("cycle", 0), pattern.get("offset", 0)
        split_number = pattern.get("split_number", self._system_pattern)
        if cycle <= 0 or not (0 <= offset < cycle):
            return None

        coord_phase = next(
            (phase for (sn, phase), flag in self._split_coord.items() if sn == split_number and flag),
            None,
        )
        durations = []
        for group in self.groups:
            times = [self._split_times.get((split_number, phase)) for phase in group.phases]
            if any(t is None or t <= 0 for t in times) or len(set(times)) != 1:
                # Both rings must spend the same time in a barrier group.
                return None
            durations.append(times[0])
        if sum(durations) != cycle:
            return None
        for group, seconds in zip(self.groups, durations):
            if seconds < group.min_green_sec + group.yellow_sec + group.red_clearance_sec:
                return None

        # The coordinated phase's group starts the cycle: offsets reference the
        # start of coordinated-phase green.
        order = list(range(len(self.groups)))
        if coord_phase is not None:
            first = next((i for i, g in enumerate(self.groups) if coord_phase in g.phases), 0)
            order = order[first:] + order[:first]
        return {
            "cycle": cycle, "offset": offset, "order": order,
            "durations": {i: durations[i] for i in range(len(self.groups))},
        }

    def _coordinated_position(self, plan: Dict[str, object]) -> Tuple[int, float]:
        since = self.clock() - plan["offset"]
        cycle = plan["cycle"]
        return int(since // cycle), since % cycle

    def _coordinated_state(self, plan: Dict[str, object]) -> Dict[str, object]:
        cycle_index, position = self._coordinated_position(plan)
        order = plan["order"]
        durations = [plan["durations"][i] for i in order]

        if self._extension and self._extension[0] != cycle_index:
            # The extension belonged to an earlier cycle; its hold is released.
            self._extension = None
            self._hold_bitmap = 0
        if self._extension:
            _cycle, group_pos, seconds = self._extension
            durations[group_pos] += seconds
            durations[group_pos + 1] -= seconds

        start = 0.0
        for pos, length in enumerate(durations):
            if position < start + length:
                group = self.groups[order[pos]]
                into = position - start
                green_len = length - group.yellow_sec - group.red_clearance_sec
                if into < green_len:
                    interval, greens, yellows = GREEN, list(group.phases), []
                elif into < green_len + group.yellow_sec:
                    interval, greens, yellows = YELLOW, [], list(group.phases)
                else:
                    interval, greens, yellows = RED_CLEARANCE, [], []
                next_group = self.groups[order[(pos + 1) % len(order)]]
                all_phases = [p for g in self.groups for p in g.phases]
                return {
                    "interval": interval,
                    "greens": greens,
                    "yellows": yellows,
                    "reds": sorted(p for p in all_phases if p not in greens and p not in yellows),
                    "phase_nexts": list(next_group.phases),
                    "held_phases": self._held_phases(),
                    "elapsed_in_interval_sec": round(into, 2),
                    "coordinated": True,
                    "active_pattern": self._system_pattern,
                    "cycle_position_sec": round(position, 2),
                    "_group_pos": pos,
                    "_cycle_index": cycle_index,
                    "_green_len": green_len,
                }
            start += length
        # Floating-point edge at the very end of the cycle.
        return self._coordinated_state_at_start(plan)

    def _coordinated_state_at_start(self, plan):
        group = self.groups[plan["order"][0]]
        return {"interval": GREEN, "greens": list(group.phases), "yellows": [],
                "reds": [], "phase_nexts": [], "held_phases": self._held_phases(),
                "elapsed_in_interval_sec": 0.0, "coordinated": True,
                "active_pattern": self._system_pattern, "cycle_position_sec": 0.0,
                "_group_pos": 0, "_cycle_index": 0, "_green_len": 0.0}

    def _grant_extension(self, plan: Dict[str, object], held: List[int]) -> None:
        """Green extension under coordination - the TSP and preemption case.

        Extends the currently green barrier group, borrowing the time from the
        next group within the same cycle so the cycle length - and so the
        coordination - is preserved. Bounded by the group's max green and by
        the next group's minimum green plus clearance. A hold for phases not
        currently green is accepted but has no effect until their own time,
        which the post-command read-back reports truthfully.
        """
        current = self._coordinated_state(plan)
        pos = current["_group_pos"]
        order = plan["order"]
        group = self.groups[order[pos]]
        if current["interval"] != GREEN or not (set(held) & set(group.phases)):
            return
        if pos + 1 >= len(order):
            return  # cannot borrow across the cycle boundary without losing sync
        next_group = self.groups[order[pos + 1]]
        next_len = plan["durations"][order[pos + 1]]
        headroom_here = group.max_green_sec - current["_green_len"]
        slack_next = next_len - next_group.yellow_sec - next_group.red_clearance_sec - next_group.min_green_sec
        seconds = max(0.0, min(headroom_here, slack_next))
        if seconds > 0:
            self._extension = (current["_cycle_index"], pos, seconds)

    def state(self) -> Dict[str, object]:
        """Current interval and the phases in each colour."""
        with self._lock:
            plan = self._coordinated_plan()
            if plan is not None:
                state = self._coordinated_state(plan)
                return {k: v for k, v in state.items() if not k.startswith("_")}
            self._advance()
            group = self._group
            all_phases = [p for g in self.groups for p in g.phases]

            if self._interval == GREEN:
                greens = list(group.phases)
                yellows: List[int] = []
            elif self._interval == YELLOW:
                greens = []
                yellows = list(group.phases)
            else:
                greens = []
                yellows = []

            reds = [p for p in all_phases if p not in greens and p not in yellows]
            next_group = self.groups[(self._group_index + 1) % len(self.groups)]

            return {
                "interval": self._interval,
                "greens": greens,
                "yellows": yellows,
                "reds": sorted(reds),
                "phase_nexts": list(next_group.phases),
                "held_phases": self._held_phases(),
                "elapsed_in_interval_sec": round(time.monotonic() - self._interval_started, 2),
                "coordinated": False,
                "active_pattern": ntcip.PATTERN_STATUS_FREE,
                "cycle_position_sec": None,
            }

    def apply_hold(self, bitmap: int) -> None:
        with self._lock:
            plan = self._coordinated_plan()
            if plan is not None:
                self._hold_bitmap = bitmap
                if bitmap:
                    self._grant_extension(
                        plan, ntcip.phase_bitmap_to_numbers(bitmap, self.status_group)
                    )
                return
            self._advance()
            self._hold_bitmap = bitmap

    # -- NTCIP object access ----------------------------------------------

    def read_oid(self, oid: str) -> Optional[int]:
        """Resolves a supported NTCIP OID to its current value, else None."""
        if oid == ntcip.MAX_PHASES_OID:
            return self.max_phases

        prefix = ntcip.PHASE_STATUS_GROUP_ENTRY + "."
        if oid.startswith(prefix):
            try:
                column_str, group_str = oid[len(prefix):].split(".")
                column, group = int(column_str), int(group_str)
            except ValueError:
                return None
            if group != self.status_group:
                # Only one status group is emulated; other groups read as all-red,
                # which is the truthful state for phases this cabinet does not run.
                return 0
            return self._status_column(column)

        control_prefix = ntcip.PHASE_CONTROL_GROUP_ENTRY + "."
        if oid.startswith(control_prefix):
            try:
                column_str, group_str = oid[len(control_prefix):].split(".")
                column, group = int(column_str), int(group_str)
            except ValueError:
                return None
            if column == ntcip.COL_CONTROL_GROUP_HOLD and group == self.status_group:
                return self._hold_bitmap
            return 0

        return self._read_coordination(oid)

    def _read_coordination(self, oid: str) -> Optional[int]:
        if oid == ntcip.MAX_PATTERNS_OID:
            return self.max_patterns
        if oid == ntcip.MAX_SPLITS_OID:
            return self.max_splits
        if oid == ntcip.SYSTEM_PATTERN_CONTROL_OID:
            return self._system_pattern
        if oid in (ntcip.COORD_PATTERN_STATUS_OID, ntcip.COORD_CYCLE_STATUS_OID):
            with self._lock:
                plan = self._coordinated_plan()
                if oid == ntcip.COORD_PATTERN_STATUS_OID:
                    return self._system_pattern if plan else ntcip.PATTERN_STATUS_FREE
                if plan is None:
                    return 0
                return int(self._coordinated_position(plan)[1])

        parsed = self._parse_table_oid(oid)
        if parsed is None:
            return None
        table, column, index = parsed
        if table == "pattern":
            entry = self._patterns.get(index[0], {})
            if column == ntcip.COL_PATTERN_NUMBER:
                return index[0]
            if column == ntcip.COL_PATTERN_CYCLE_TIME:
                return entry.get("cycle", 0)
            if column == ntcip.COL_PATTERN_OFFSET_TIME:
                return entry.get("offset", 0)
            if column == ntcip.COL_PATTERN_SPLIT_NUMBER:
                return entry.get("split_number", 0)
            return 0
        if column == ntcip.COL_SPLIT_TIME:
            return self._split_times.get(index, 0)
        if column == ntcip.COL_SPLIT_COORD_PHASE:
            return self._split_coord.get(index, 0)
        if column in (ntcip.COL_SPLIT_NUMBER, ntcip.COL_SPLIT_PHASE):
            return index[0] if column == ntcip.COL_SPLIT_NUMBER else index[1]
        return 0

    def _parse_table_oid(self, oid: str):
        for table, prefix, width in (
            ("pattern", ntcip.PATTERN_ENTRY + ".", 1),
            ("split", ntcip.SPLIT_ENTRY + ".", 2),
        ):
            if oid.startswith(prefix):
                try:
                    parts = [int(x) for x in oid[len(prefix):].split(".")]
                except ValueError:
                    return None
                if len(parts) != 1 + width:
                    return None
                column, index = parts[0], tuple(parts[1:])
                limit = self.max_patterns if table == "pattern" else self.max_splits
                if not (1 <= index[0] <= limit):
                    return None
                if table == "split" and not (1 <= index[1] <= self.max_phases):
                    return None
                return table, column, index
        return None

    def _status_column(self, column: int) -> Optional[int]:
        state = self.state()
        to_bitmap = lambda phases: ntcip.phase_numbers_to_bitmap(phases, self.status_group)  # noqa: E731

        if column == ntcip.COL_STATUS_GROUP_NUMBER:
            return self.status_group
        if column == ntcip.COL_STATUS_GROUP_GREENS:
            return to_bitmap(state["greens"])
        if column == ntcip.COL_STATUS_GROUP_YELLOWS:
            return to_bitmap(state["yellows"])
        if column == ntcip.COL_STATUS_GROUP_REDS:
            return to_bitmap(state["reds"])
        if column == ntcip.COL_STATUS_GROUP_PHASE_ONS:
            return to_bitmap(list(state["greens"]) + list(state["yellows"]))
        if column == ntcip.COL_STATUS_GROUP_PHASE_NEXTS:
            return to_bitmap(state["phase_nexts"])
        if column in (
            ntcip.COL_STATUS_GROUP_VEH_CALLS,
            ntcip.COL_STATUS_GROUP_PED_CALLS,
            ntcip.COL_STATUS_GROUP_WALKS,
            ntcip.COL_STATUS_GROUP_DONT_WALKS,
            ntcip.COL_STATUS_GROUP_PED_CLEARS,
        ):
            # No detectors and no pedestrian pushbuttons are emulated, so these
            # read as zero: a truthful "no call registered", not invented demand.
            return 0
        return None

    def can_write(self, oid: str, value: int) -> bool:
        """Whether a SetRequest varbind is acceptable, without applying it."""
        if not isinstance(value, int) or not (0 <= value <= 255):
            return False
        control_prefix = ntcip.PHASE_CONTROL_GROUP_ENTRY + "."
        if oid.startswith(control_prefix):
            try:
                column_str, group_str = oid[len(control_prefix):].split(".")
                column, group = int(column_str), int(group_str)
            except ValueError:
                return False
            return column == ntcip.COL_CONTROL_GROUP_HOLD and group == self.status_group
        if oid == ntcip.SYSTEM_PATTERN_CONTROL_OID:
            return value <= self.max_patterns
        parsed = self._parse_table_oid(oid)
        if parsed is None:
            return False
        table, column, _index = parsed
        if table == "pattern":
            return column in (ntcip.COL_PATTERN_CYCLE_TIME, ntcip.COL_PATTERN_OFFSET_TIME,
                              ntcip.COL_PATTERN_SPLIT_NUMBER)
        return column in (ntcip.COL_SPLIT_TIME, ntcip.COL_SPLIT_COORD_PHASE)

    def write_oid(self, oid: str, value: int) -> bool:
        """Applies one validated SetRequest varbind."""
        if not self.can_write(oid, value):
            return False
        control_prefix = ntcip.PHASE_CONTROL_GROUP_ENTRY + "."
        if oid.startswith(control_prefix):
            self.apply_hold(int(value))
            return True
        with self._lock:
            if oid == ntcip.SYSTEM_PATTERN_CONTROL_OID:
                self._system_pattern = int(value)
                self._extension = None
                return True
            table, column, index = self._parse_table_oid(oid)
            if table == "pattern":
                entry = self._patterns.setdefault(index[0], {})
                key = {ntcip.COL_PATTERN_CYCLE_TIME: "cycle",
                       ntcip.COL_PATTERN_OFFSET_TIME: "offset",
                       ntcip.COL_PATTERN_SPLIT_NUMBER: "split_number"}[column]
                entry[key] = int(value)
            elif column == ntcip.COL_SPLIT_TIME:
                self._split_times[index] = int(value)
            else:
                self._split_coord[index] = int(value)
        return True


class NtcipEmulatorServer:
    """UDP SNMPv1 front end for `SignalControllerEmulator`."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 1610,
        emulator: Optional[SignalControllerEmulator] = None,
        read_community: str = "public",
        write_community: str = "private",
    ):
        self.host = host
        self.emulator = emulator or SignalControllerEmulator()
        self.read_community = read_community
        self.write_community = write_community
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.settimeout(0.5)
        self.port = self._sock.getsockname()[1]
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self) -> "NtcipEmulatorServer":
        self._running.set()
        self._thread = threading.Thread(target=self._serve, name="ntcip-emulator", daemon=True)
        self._thread.start()
        logger.info("NTCIP 1202 emulator listening on %s:%s", self.host, self.port)
        return self

    def stop(self) -> None:
        self._running.clear()
        if self._thread:
            self._thread.join(timeout=2.0)
        self._sock.close()

    def __enter__(self) -> "NtcipEmulatorServer":
        return self.start()

    def __exit__(self, *exc_info) -> None:
        self.stop()

    def _serve(self) -> None:
        while self._running.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                reply = self._handle(data)
            except Exception as exc:  # noqa: BLE001 - an agent must not die on a bad PDU
                logger.warning("Discarding malformed SNMP datagram: %s", exc)
                continue
            if reply:
                try:
                    self._sock.sendto(reply, addr)
                except OSError:
                    pass

    def _handle(self, data: bytes) -> Optional[bytes]:
        message = snmp.parse_message(data)

        if message.pdu_tag == snmp.TAG_GET_REQUEST:
            expected_community = self.read_community
        elif message.pdu_tag == snmp.TAG_SET_REQUEST:
            expected_community = self.write_community
        else:
            return None

        if message.community != expected_community:
            # RFC 1157 authentication failure: a real agent stays silent.
            logger.warning("Rejected SNMP request with community '%s'", message.community)
            return None

        out: List[snmp.VarBind] = []
        for index, vb in enumerate(message.varbinds, start=1):
            if message.pdu_tag == snmp.TAG_GET_REQUEST:
                value = self.emulator.read_oid(vb.oid)
                if value is None:
                    return snmp.build_response(
                        message.community, message.request_id, [],
                        error_status=2, error_index=index,  # noSuchName
                    )
                out.append(snmp.VarBind(oid=vb.oid, value=value))
            else:
                # Validation pass only; nothing is applied until every varbind
                # in the PDU has been accepted.
                if not isinstance(vb.value, int):
                    return snmp.build_response(
                        message.community, message.request_id, [],
                        error_status=3, error_index=index,  # badValue
                    )
                if not self.emulator.can_write(vb.oid, vb.value):
                    return snmp.build_response(
                        message.community, message.request_id, [],
                        error_status=4, error_index=index,  # readOnly / not writable
                    )
                out.append(snmp.VarBind(oid=vb.oid, value=vb.value))

        if message.pdu_tag == snmp.TAG_SET_REQUEST:
            # RFC 1157 4.1.5: a SetRequest is applied as if simultaneously, all
            # or nothing. Every varbind passed validation above, so apply them.
            for vb in message.varbinds:
                self.emulator.write_oid(vb.oid, vb.value)

        return snmp.build_response(message.community, message.request_id, out)


def main() -> None:
    parser = argparse.ArgumentParser(description="NTCIP 1202 signal controller emulator")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1610)
    parser.add_argument("--read-community", default="public")
    parser.add_argument("--write-community", default="private")
    parser.add_argument("--min-green", type=float, default=7.0)
    parser.add_argument("--max-green", type=float, default=45.0)
    parser.add_argument("--yellow", type=float, default=4.0)
    parser.add_argument("--red-clearance", type=float, default=2.0)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    groups = [
        ConcurrentGroup(
            phases=phases,
            min_green_sec=args.min_green,
            max_green_sec=args.max_green,
            yellow_sec=args.yellow,
            red_clearance_sec=args.red_clearance,
        )
        for phases in ([2, 6], [4, 8])
    ]

    server = NtcipEmulatorServer(
        host=args.host,
        port=args.port,
        emulator=SignalControllerEmulator(groups=groups),
        read_community=args.read_community,
        write_community=args.write_community,
    ).start()

    print("NTCIP 1202 emulator on {}:{}".format(args.host, server.port))
    print("Reports signal phase state only. No vehicle counts, no detector calls.")
    try:
        while True:
            state = server.emulator.state()
            print(
                "  {:<14} {:<10} green={:<8} yellow={:<8} held={}".format(
                    state["interval"],
                    "coord p{} @{}s".format(state["active_pattern"], int(state["cycle_position_sec"]))
                    if state.get("coordinated") else "free",
                    ",".join(str(p) for p in state["greens"]) or "-",
                    ",".join(str(p) for p in state["yellows"]) or "-",
                    ",".join(str(p) for p in state["held_phases"]) or "-",
                )
            )
            time.sleep(2.0)
    except KeyboardInterrupt:
        print("\nStopping emulator.")
    finally:
        server.stop()


if __name__ == "__main__":
    main()
