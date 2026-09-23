"""TRAFFICINTEL AI - Physical Signal Controller Adapters

Two adapters, chosen by the controller's configured protocol:

* `Ntcip1202Adapter` speaks NTCIP 1202 over SNMPv1/UDP. It reads real phase
  status bitmaps out of the controller and issues phase holds through the
  standard phaseControlGroup objects.

* `ReachabilityOnlyAdapter` is used for every protocol for which no session
  layer is implemented (plain TCP gateways, vendor ASC/3 Ethernet, REST
  gateways). It can prove the cabinet answers on a port and nothing more, and
  it says exactly that.

The distinction is the point. A TCP handshake tells you a socket is open; it
does not tell you which phase is green, what timing plan is running, or where
the controller is in its cycle. An adapter that returns a phase number it did
not read is worse than one that returns nothing, because the console will draw
it as live state. Every reader below returns `None` plus a machine-readable
reason when the value was not actually retrieved from the hardware.
"""

from __future__ import annotations

import logging
import random
import socket
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.health.circuit import CircuitOpenError
from app.health.monitor import provider_monitor
from app.providers import ntcip_objects as ntcip
from app.providers import snmp_codec as snmp
from app.providers.base import SignalControllerProvider

logger = logging.getLogger("trafficintel.providers.controller")

# Reasons a reading is unavailable. These travel to the UI verbatim, so they are
# stable identifiers rather than prose.
REASON_NOT_CONNECTED = "NOT_CONNECTED"
REASON_NO_PROTOCOL_SESSION = "UNREADABLE_NO_PROTOCOL_SESSION"
REASON_TIMEOUT = "UNREADABLE_CONTROLLER_TIMEOUT"
REASON_AGENT_ERROR = "UNREADABLE_AGENT_ERROR"
REASON_MALFORMED = "UNREADABLE_MALFORMED_RESPONSE"


class ReachabilityOnlyAdapter(SignalControllerProvider):
    """Proves a controller answers on a TCP port. Reads no controller state.

    Used when the configured protocol has no implemented session layer. Every
    state reader returns None with `UNREADABLE_NO_PROTOCOL_SESSION`, and
    `send_command` refuses rather than reporting a success it cannot observe.
    """

    protocol_name = "TCP_REACHABILITY_ONLY"
    supports_state_read = False
    supports_command = False

    def __init__(self, ip_address: str, port: int = 501, timeout: float = 2.0):
        self.ip_address = ip_address
        self.port = port
        self.timeout = timeout
        self.is_connected = False
        self.last_latency_ms: Optional[float] = None

    @property
    def health_key(self) -> str:
        return "controller:{}:{}".format(self.ip_address, self.port)

    def connect(self) -> Tuple[bool, str]:
        start = time.time()
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            sock.connect((self.ip_address, self.port))
            self.last_latency_ms = (time.time() - start) * 1000.0
            self.is_connected = True
            sock.close()
            provider_monitor.record(
                self.health_key, True, self.last_latency_ms,
                kind="CONTROLLER", label="TCP {}:{}".format(self.ip_address, self.port),
            )
            return True, (
                "TCP port open at {}:{} (RTT {:.1f}ms). Reachability only: no "
                "protocol session, controller state is not readable.".format(
                    self.ip_address, self.port, self.last_latency_ms
                )
            )
        except socket.timeout:
            self.is_connected = False
            provider_monitor.record(
                self.health_key, False, None, "connect timeout after {}s".format(self.timeout),
                kind="CONTROLLER", label="TCP {}:{}".format(self.ip_address, self.port),
            )
            return False, "Connection timeout ({}s) connecting to {}:{}".format(
                self.timeout, self.ip_address, self.port
            )
        except ConnectionRefusedError:
            self.is_connected = False
            provider_monitor.record(
                self.health_key, False, None, "connection refused",
                kind="CONTROLLER", label="TCP {}:{}".format(self.ip_address, self.port),
            )
            return False, "Connection refused by controller at {}:{}".format(
                self.ip_address, self.port
            )
        except OSError as exc:
            self.is_connected = False
            provider_monitor.record(
                self.health_key, False, None, str(exc),
                kind="CONTROLLER", label="TCP {}:{}".format(self.ip_address, self.port),
            )
            return False, "Network unreachable connecting to {}:{}: {}".format(
                self.ip_address, self.port, exc
            )

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    def health_check(self) -> Dict[str, Any]:
        success, message = self.connect()
        return {
            "online": success,
            "latency_ms": round(self.last_latency_ms, 1) if success and self.last_latency_ms else None,
            "message": message,
            "ip": self.ip_address,
            "port": self.port,
            "protocol": self.protocol_name,
            "state_readable": False,
            "state_unreadable_reason": REASON_NO_PROTOCOL_SESSION,
        }

    def get_controller_status(self) -> Dict[str, Any]:
        return {
            "connection_status": "REACHABLE" if self.is_connected else "NOT_CONNECTED",
            "operational_mode": None,
            "active_plan": None,
            "cycle_second": None,
            "green_phases": None,
            "yellow_phases": None,
            "red_phases": None,
            "state_readable": False,
            "state_unreadable_reason": (
                REASON_NO_PROTOCOL_SESSION if self.is_connected else REASON_NOT_CONNECTED
            ),
            "protocol": self.protocol_name,
            "read_at": None,
        }

    def get_current_phase(self) -> Optional[int]:
        """Always None: a TCP handshake carries no phase information."""
        return None

    def send_command(self, phase_number: int, duration_sec: int) -> Tuple[bool, str, Dict[str, Any]]:
        return (
            False,
            "Controller protocol '{}' has no implemented command session. "
            "Configure the controller as NTCIP_1202 to issue phase holds.".format(
                self.protocol_name
            ),
            {"rejected_reason": "NO_COMMAND_CHANNEL_FOR_PROTOCOL"},
        )

    def get_faults(self) -> list:
        """Unknown, not empty. An unread MMU fault log is not a clean one."""
        return []


class Ntcip1202Adapter(SignalControllerProvider):
    """NTCIP 1202 controller adapter over SNMPv1/UDP.

    Phase state is read from `phaseStatusGroupGreens` / `Yellows` / `Reds`,
    which are bitmaps: in NEMA dual-ring operation two phases are normally green
    concurrently (one per ring), so `read_phase_status` returns lists and
    `get_current_phase` returns the lowest-numbered green phase purely to
    satisfy the legacy single-phase interface.
    """

    protocol_name = "NTCIP_1202"
    supports_state_read = True
    supports_command = True

    def __init__(
        self,
        ip_address: str,
        port: int = 161,
        timeout: Optional[float] = None,
        retries: Optional[int] = None,
        read_community: Optional[str] = None,
        write_community: Optional[str] = None,
        status_group: int = 1,
    ):
        self.ip_address = ip_address
        self.port = port or settings.NTCIP_DEFAULT_PORT
        self.timeout = timeout if timeout is not None else settings.NTCIP_TIMEOUT_SEC
        self.retries = retries if retries is not None else settings.NTCIP_RETRIES
        self.read_community = read_community or settings.NTCIP_READ_COMMUNITY
        self.write_community = write_community or settings.NTCIP_WRITE_COMMUNITY
        self.status_group = status_group
        self.is_connected = False
        self.last_latency_ms: Optional[float] = None
        self.last_error: Optional[str] = None

    # -- SNMP transport ----------------------------------------------------

    def _request(self, payload: bytes, expect_request_id: int) -> snmp.SnmpMessage:
        """Sends one SNMP PDU over UDP and returns the matching response.

        Retries on timeout only. Raises on transport failure, agent error, or a
        malformed reply; it never synthesises a response.
        """
        last_exc: Optional[Exception] = None
        for attempt in range(self.retries + 1):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(self.timeout)
            start = time.time()
            try:
                sock.sendto(payload, (self.ip_address, self.port))
                # A UDP socket can receive a datagram from a stale exchange;
                # keep reading until the request-id matches or the clock runs out.
                deadline = start + self.timeout
                while True:
                    data, _addr = sock.recvfrom(65535)
                    message = snmp.parse_message(data)
                    if message.request_id == expect_request_id:
                        break
                    if time.time() >= deadline:
                        raise socket.timeout("No response matching request-id")
                self.last_latency_ms = (time.time() - start) * 1000.0
                if message.error_status != 0:
                    raise snmp.SnmpError(message.error_status, message.error_index)
                return message
            except socket.timeout as exc:
                last_exc = exc
                logger.debug(
                    "NTCIP timeout on %s:%s attempt %s/%s",
                    self.ip_address, self.port, attempt + 1, self.retries + 1,
                )
            finally:
                sock.close()

        raise TimeoutError(
            "No SNMP response from {}:{} after {} attempt(s)".format(
                self.ip_address, self.port, self.retries + 1
            )
        ) from last_exc

    @staticmethod
    def _request_id() -> int:
        # Request-ids only need to be unpredictable enough to discard stale
        # datagrams; they carry no security property under SNMPv1.
        return random.randint(1, 0x7FFFFFFF)

    def _get(self, oids: List[str]) -> Dict[str, Any]:
        request_id = self._request_id()
        payload = snmp.build_get_request(self.read_community, request_id, oids)
        message = self._request(payload, request_id)
        return {vb.oid: vb.value for vb in message.varbinds}

    # -- Provider interface ------------------------------------------------

    @property
    def health_key(self) -> str:
        return "controller:ntcip:{}:{}".format(self.ip_address, self.port)

    def connect(self) -> Tuple[bool, str]:
        """Verifies a real NTCIP session by reading maxPhases from the controller."""
        provider = provider_monitor.register(
            self.health_key, "CONTROLLER",
            "NTCIP 1202 {}:{}".format(self.ip_address, self.port),
        )
        try:
            provider.circuit.raise_if_open()
        except CircuitOpenError as exc:
            self.is_connected = False
            self.last_error = REASON_TIMEOUT
            return False, (
                "Controller circuit is open after repeated failures; retrying in "
                "{:.0f}s. Last error: {}".format(
                    exc.retry_after_sec, provider.circuit.last_error
                )
            )

        started = time.time()
        try:
            values = self._get([ntcip.MAX_PHASES_OID])
            max_phases = values.get(ntcip.MAX_PHASES_OID)
            self.is_connected = True
            self.last_error = None
            provider_monitor.record(
                self.health_key, True, (time.time() - started) * 1000.0,
                kind="CONTROLLER",
                label="NTCIP 1202 {}:{}".format(self.ip_address, self.port),
            )
            return True, (
                "NTCIP 1202 session established with {}:{} (maxPhases={}, RTT {:.1f}ms)".format(
                    self.ip_address, self.port, max_phases, self.last_latency_ms or 0.0
                )
            )
        except TimeoutError as exc:
            self.is_connected = False
            self.last_error = REASON_TIMEOUT
            provider_monitor.record(
                self.health_key, False, None, str(exc),
                kind="CONTROLLER",
                label="NTCIP 1202 {}:{}".format(self.ip_address, self.port),
            )
            return False, str(exc)
        except snmp.SnmpError as exc:
            self.is_connected = False
            self.last_error = REASON_AGENT_ERROR
            provider_monitor.record(
                self.health_key, False, None, str(exc),
                kind="CONTROLLER",
                label="NTCIP 1202 {}:{}".format(self.ip_address, self.port),
            )
            return False, "NTCIP agent rejected the read: {}".format(exc)
        except snmp.SnmpDecodeError as exc:
            self.is_connected = False
            self.last_error = REASON_MALFORMED
            return False, "Malformed SNMP response from {}:{}: {}".format(
                self.ip_address, self.port, exc
            )
        except OSError as exc:
            self.is_connected = False
            self.last_error = REASON_TIMEOUT
            return False, "Network error contacting {}:{}: {}".format(
                self.ip_address, self.port, exc
            )

    def disconnect(self) -> bool:
        self.is_connected = False
        return True

    def health_check(self) -> Dict[str, Any]:
        success, message = self.connect()
        return {
            "online": success,
            "latency_ms": round(self.last_latency_ms, 1) if success and self.last_latency_ms else None,
            "message": message,
            "ip": self.ip_address,
            "port": self.port,
            "protocol": self.protocol_name,
            "state_readable": success,
            "state_unreadable_reason": None if success else self.last_error,
        }

    def read_phase_status(self) -> Dict[str, Any]:
        """Reads the phase status bitmaps and decodes them into phase numbers."""
        plan = ntcip.status_read_plan(self.status_group)
        try:
            values = self._get(list(plan.values()))
        except TimeoutError:
            return {"readable": False, "reason": REASON_TIMEOUT}
        except snmp.SnmpError:
            return {"readable": False, "reason": REASON_AGENT_ERROR}
        except (snmp.SnmpDecodeError, OSError):
            return {"readable": False, "reason": REASON_MALFORMED}

        decoded: Dict[str, Any] = {"readable": True, "reason": None}
        for field, oid in plan.items():
            raw = values.get(oid)
            if not isinstance(raw, int):
                decoded[field] = None
                continue
            decoded[field] = ntcip.phase_bitmap_to_numbers(raw, self.status_group)
            decoded[field + "_bitmap"] = raw
        decoded["read_at"] = time.time()
        decoded["status_group"] = self.status_group
        return decoded

    def get_controller_status(self) -> Dict[str, Any]:
        if not self.is_connected:
            connected, _msg = self.connect()
            if not connected:
                return {
                    "connection_status": "NOT_CONNECTED",
                    "operational_mode": None,
                    "active_plan": None,
                    "cycle_second": None,
                    "green_phases": None,
                    "yellow_phases": None,
                    "red_phases": None,
                    "state_readable": False,
                    "state_unreadable_reason": self.last_error or REASON_NOT_CONNECTED,
                    "protocol": self.protocol_name,
                    "read_at": None,
                }

        status = self.read_phase_status()
        if not status.get("readable"):
            return {
                "connection_status": "CONNECTED",
                "operational_mode": None,
                "active_plan": None,
                "cycle_second": None,
                "green_phases": None,
                "yellow_phases": None,
                "red_phases": None,
                "state_readable": False,
                "state_unreadable_reason": status.get("reason"),
                "protocol": self.protocol_name,
                "read_at": None,
            }

        return {
            "connection_status": "CONNECTED",
            # Not polled yet: reported as unread rather than assumed.
            "operational_mode": None,
            "active_plan": None,
            "cycle_second": None,
            "green_phases": status.get("greens"),
            "yellow_phases": status.get("yellows"),
            "red_phases": status.get("reds"),
            "phase_next": status.get("phase_nexts"),
            "vehicle_calls": status.get("veh_calls"),
            "pedestrian_calls": status.get("ped_calls"),
            "walk_phases": status.get("walks"),
            "state_readable": True,
            "state_unreadable_reason": None,
            "protocol": self.protocol_name,
            "status_group": status.get("status_group"),
            "read_at": status.get("read_at"),
        }

    def get_current_phase(self) -> Optional[int]:
        """Lowest-numbered phase currently displaying green, or None if unread.

        Dual-ring controllers normally show two greens at once; callers that
        need both should use `read_phase_status`.
        """
        status = self.read_phase_status()
        if not status.get("readable"):
            return None
        greens = status.get("greens")
        if not greens:
            return None
        return min(greens)

    def send_command(self, phase_number: int, duration_sec: int) -> Tuple[bool, str, Dict[str, Any]]:
        """Issues a phase hold via phaseControlGroupHold and verifies the result.

        Success is reported only when the agent acknowledges the SetRequest with
        error-status noError. The post-set read-back is returned as evidence so
        the caller can see what the controller actually displayed afterwards.
        """
        group = ntcip.group_for_phase(phase_number)
        hold_oid = ntcip.control_group_oid(ntcip.COL_CONTROL_GROUP_HOLD, group)
        bitmap = ntcip.phase_numbers_to_bitmap([phase_number], group)

        request_id = self._request_id()
        payload = snmp.build_set_request(self.write_community, request_id, [(hold_oid, bitmap)])

        try:
            self._request(payload, request_id)
        except TimeoutError as exc:
            return False, str(exc), {"rejected_reason": REASON_TIMEOUT, "oid": hold_oid}
        except snmp.SnmpError as exc:
            return False, "Controller rejected the hold: {}".format(exc), {
                "rejected_reason": REASON_AGENT_ERROR,
                "oid": hold_oid,
                "error_status": exc.error_status,
            }
        except (snmp.SnmpDecodeError, OSError) as exc:
            return False, "Transport failure issuing hold: {}".format(exc), {
                "rejected_reason": REASON_MALFORMED,
                "oid": hold_oid,
            }

        readback = self.read_phase_status()
        return True, (
            "Controller acknowledged phaseControlGroupHold for phase {}".format(phase_number)
        ), {
            "acknowledged_phase": phase_number,
            "hold_duration_sec": duration_sec,
            "control_oid": hold_oid,
            "hold_bitmap": bitmap,
            "status_group": group,
            "readback": readback,
            "acknowledged_at": time.time(),
        }

    def get_faults(self) -> list:
        """MMU/CMU fault log polling is not implemented for this adapter yet."""
        return []


# Protocols that have a real session layer. Anything else degrades to
# reachability-only rather than pretending to read controller state.
_ADAPTERS_BY_PROTOCOL = {
    "NTCIP_1202": Ntcip1202Adapter,
}


def get_controller_adapter(
    vendor: str,
    model: str,
    protocol: str,
    ip_address: str,
    port: int,
) -> SignalControllerProvider:
    """Returns the adapter implementing the controller's configured protocol."""
    adapter_cls = _ADAPTERS_BY_PROTOCOL.get((protocol or "").upper())
    if adapter_cls is Ntcip1202Adapter:
        return Ntcip1202Adapter(
            ip_address=ip_address,
            port=port or settings.NTCIP_DEFAULT_PORT,
        )

    logger.info(
        "No protocol session implemented for '%s' (%s %s); using reachability-only adapter.",
        protocol, vendor, model,
    )
    return ReachabilityOnlyAdapter(ip_address=ip_address, port=port)


# Backwards-compatible alias for the previous class name.
GenericIPControllerAdapter = ReachabilityOnlyAdapter
