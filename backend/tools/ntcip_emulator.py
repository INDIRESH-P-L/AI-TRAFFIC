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
from typing import Dict, List, Optional, Tuple

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

    def state(self) -> Dict[str, object]:
        """Current interval and the phases in each colour."""
        with self._lock:
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
            }

    def apply_hold(self, bitmap: int) -> None:
        with self._lock:
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

    def write_oid(self, oid: str, value: int) -> bool:
        """Applies a SetRequest. Returns False for read-only or unknown objects."""
        control_prefix = ntcip.PHASE_CONTROL_GROUP_ENTRY + "."
        if oid.startswith(control_prefix):
            try:
                column_str, group_str = oid[len(control_prefix):].split(".")
                column, group = int(column_str), int(group_str)
            except ValueError:
                return False
            if column == ntcip.COL_CONTROL_GROUP_HOLD and group == self.status_group:
                self.apply_hold(int(value))
                return True
        return False


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
                if not isinstance(vb.value, int):
                    return snmp.build_response(
                        message.community, message.request_id, [],
                        error_status=3, error_index=index,  # badValue
                    )
                if not self.emulator.write_oid(vb.oid, vb.value):
                    return snmp.build_response(
                        message.community, message.request_id, [],
                        error_status=4, error_index=index,  # readOnly
                    )
                out.append(snmp.VarBind(oid=vb.oid, value=vb.value))

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
                "  {:<14} green={:<8} yellow={:<8} held={}".format(
                    state["interval"],
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
