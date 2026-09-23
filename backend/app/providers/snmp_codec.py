"""TRAFFICINTEL AI - Minimal SNMPv1 / BER Codec

A self-contained encoder and decoder for the subset of SNMPv1 (RFC 1157) that
NTCIP 1202 signal-controller integration requires: GetRequest, SetRequest and
the matching Response PDU, carrying INTEGER, OCTET STRING and OBJECT IDENTIFIER
values.

This is dependency-free on purpose. The alternative was to pull a large SNMP
stack in for three PDU types, and an ITS deployment is easier for an agency to
audit when the bytes that reach a signal cabinet come from code it can read in
one sitting.

Nothing here invents data: a decode failure raises, it never falls back to a
plausible-looking value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence, Tuple

# --- ASN.1 / BER tags -------------------------------------------------------
TAG_INTEGER = 0x02
TAG_OCTET_STRING = 0x04
TAG_NULL = 0x05
TAG_OID = 0x06
TAG_SEQUENCE = 0x30

# SNMP PDU tags (context-specific, constructed)
TAG_GET_REQUEST = 0xA0
TAG_GET_NEXT_REQUEST = 0xA1
TAG_GET_RESPONSE = 0xA2
TAG_SET_REQUEST = 0xA3

SNMP_VERSION_1 = 0

ERROR_STATUS_NAMES = {
    0: "noError",
    1: "tooBig",
    2: "noSuchName",
    3: "badValue",
    4: "readOnly",
    5: "genErr",
}


class SnmpDecodeError(ValueError):
    """Raised when a payload is not a well-formed SNMP message."""


class SnmpError(RuntimeError):
    """Raised when the agent returns a non-zero error-status."""

    def __init__(self, error_status: int, error_index: int):
        self.error_status = error_status
        self.error_index = error_index
        name = ERROR_STATUS_NAMES.get(error_status, "unknown(" + str(error_status) + ")")
        super().__init__(
            "SNMP agent returned error-status " + name + " at index " + str(error_index)
        )


# ---------------------------------------------------------------------------
# BER primitives
# ---------------------------------------------------------------------------

def encode_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    payload = b""
    remaining = length
    while remaining > 0:
        payload = bytes([remaining & 0xFF]) + payload
        remaining >>= 8
    return bytes([0x80 | len(payload)]) + payload


def decode_length(data: bytes, offset: int) -> Tuple[int, int]:
    """Returns (length, offset_of_first_value_byte)."""
    if offset >= len(data):
        raise SnmpDecodeError("Truncated length field")
    first = data[offset]
    offset += 1
    if first < 0x80:
        return first, offset
    count = first & 0x7F
    if count == 0 or offset + count > len(data):
        raise SnmpDecodeError("Invalid or truncated long-form length")
    value = int.from_bytes(data[offset:offset + count], "big")
    return value, offset + count


def _encode_tlv(tag: int, payload: bytes) -> bytes:
    return bytes([tag]) + encode_length(len(payload)) + payload


def encode_integer(value: int) -> bytes:
    value = int(value)
    payload = value.to_bytes((value.bit_length() // 8) + 1, "big", signed=True)
    # Strip redundant leading bytes while preserving the sign bit.
    while len(payload) > 1 and (
        (payload[0] == 0x00 and payload[1] & 0x80 == 0)
        or (payload[0] == 0xFF and payload[1] & 0x80 != 0)
    ):
        payload = payload[1:]
    return _encode_tlv(TAG_INTEGER, payload)


def encode_octet_string(value) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return _encode_tlv(TAG_OCTET_STRING, value)


def encode_null() -> bytes:
    return _encode_tlv(TAG_NULL, b"")


def encode_oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip().lstrip(".").split(".")]
    if len(parts) < 2:
        raise ValueError("OID " + oid + " must have at least two arcs")
    payload = bytes([parts[0] * 40 + parts[1]])
    for arc in parts[2:]:
        if arc < 0:
            raise ValueError("OID " + oid + " contains a negative arc")
        if arc == 0:
            payload += b"\x00"
            continue
        chunk = b""
        remaining = arc
        while remaining > 0:
            chunk = bytes([(remaining & 0x7F) | (0x80 if chunk else 0x00)]) + chunk
            remaining >>= 7
        payload += chunk
    return _encode_tlv(TAG_OID, payload)


def decode_oid(payload: bytes) -> str:
    if not payload:
        raise SnmpDecodeError("Empty OID payload")
    first = payload[0]
    arcs = [first // 40, first % 40]
    value = 0
    for byte in payload[1:]:
        value = (value << 7) | (byte & 0x7F)
        if not byte & 0x80:
            arcs.append(value)
            value = 0
    return ".".join(str(a) for a in arcs)


def encode_sequence(*chunks: bytes) -> bytes:
    return _encode_tlv(TAG_SEQUENCE, b"".join(chunks))


# ---------------------------------------------------------------------------
# Generic TLV walker
# ---------------------------------------------------------------------------

@dataclass
class Tlv:
    tag: int
    payload: bytes
    end: int


def read_tlv(data: bytes, offset: int = 0) -> Tlv:
    if offset >= len(data):
        raise SnmpDecodeError("Truncated TLV header")
    tag = data[offset]
    length, value_start = decode_length(data, offset + 1)
    value_end = value_start + length
    if value_end > len(data):
        raise SnmpDecodeError("TLV claims more bytes than the buffer holds")
    return Tlv(tag=tag, payload=data[value_start:value_end], end=value_end)


def decode_value(tag: int, payload: bytes) -> Any:
    """Decodes a varbind value, preserving unknown types as raw bytes."""
    if tag == TAG_INTEGER:
        return int.from_bytes(payload, "big", signed=True) if payload else 0
    if tag == TAG_OCTET_STRING:
        return payload
    if tag == TAG_OID:
        return decode_oid(payload)
    if tag == TAG_NULL:
        return None
    # Application types (Counter, Gauge, TimeTicks, ...) carry unsigned integers.
    if 0x40 <= tag <= 0x46:
        return int.from_bytes(payload, "big") if payload else 0
    return payload


# ---------------------------------------------------------------------------
# SNMP messages
# ---------------------------------------------------------------------------

@dataclass
class VarBind:
    oid: str
    value: Any = None
    tag: int = TAG_NULL


def build_get_request(community: str, request_id: int, oids: Sequence[str]) -> bytes:
    """Encodes an SNMPv1 GetRequest for the supplied OIDs."""
    varbinds = b"".join(encode_sequence(encode_oid(oid), encode_null()) for oid in oids)
    pdu_body = (
        encode_integer(request_id)
        + encode_integer(0)  # error-status
        + encode_integer(0)  # error-index
        + _encode_tlv(TAG_SEQUENCE, varbinds)
    )
    pdu = _encode_tlv(TAG_GET_REQUEST, pdu_body)
    return encode_sequence(
        encode_integer(SNMP_VERSION_1), encode_octet_string(community), pdu
    )


def build_set_request(
    community: str, request_id: int, bindings: Sequence[Tuple[str, int]]
) -> bytes:
    """Encodes an SNMPv1 SetRequest of INTEGER-valued objects.

    NTCIP 1202 phase control objects are INTEGER or bitmap-in-INTEGER, which is
    why this accepts only integers rather than a generic value type.
    """
    varbinds = b"".join(
        encode_sequence(encode_oid(oid), encode_integer(int(value)))
        for oid, value in bindings
    )
    pdu_body = (
        encode_integer(request_id)
        + encode_integer(0)
        + encode_integer(0)
        + _encode_tlv(TAG_SEQUENCE, varbinds)
    )
    pdu = _encode_tlv(TAG_SET_REQUEST, pdu_body)
    return encode_sequence(
        encode_integer(SNMP_VERSION_1), encode_octet_string(community), pdu
    )


@dataclass
class SnmpMessage:
    version: int
    community: str
    pdu_tag: int
    request_id: int
    error_status: int
    error_index: int
    varbinds: List[VarBind]


def parse_message(data: bytes) -> SnmpMessage:
    """Parses an SNMPv1 message. Raises SnmpDecodeError on any malformed field."""
    envelope = read_tlv(data)
    if envelope.tag != TAG_SEQUENCE:
        raise SnmpDecodeError("Expected SEQUENCE envelope")

    body = envelope.payload
    version_tlv = read_tlv(body, 0)
    community_tlv = read_tlv(body, version_tlv.end)
    pdu_tlv = read_tlv(body, community_tlv.end)

    version = decode_value(version_tlv.tag, version_tlv.payload)
    community = community_tlv.payload.decode("utf-8", errors="replace")

    pdu = pdu_tlv.payload
    request_id_tlv = read_tlv(pdu, 0)
    error_status_tlv = read_tlv(pdu, request_id_tlv.end)
    error_index_tlv = read_tlv(pdu, error_status_tlv.end)
    varbind_list_tlv = read_tlv(pdu, error_index_tlv.end)

    varbinds: List[VarBind] = []
    offset = 0
    blob = varbind_list_tlv.payload
    while offset < len(blob):
        vb_tlv = read_tlv(blob, offset)
        oid_tlv = read_tlv(vb_tlv.payload, 0)
        value_tlv = read_tlv(vb_tlv.payload, oid_tlv.end)
        varbinds.append(
            VarBind(
                oid=decode_oid(oid_tlv.payload),
                value=decode_value(value_tlv.tag, value_tlv.payload),
                tag=value_tlv.tag,
            )
        )
        offset = vb_tlv.end

    return SnmpMessage(
        version=version,
        community=community,
        pdu_tag=pdu_tlv.tag,
        request_id=decode_value(request_id_tlv.tag, request_id_tlv.payload),
        error_status=decode_value(error_status_tlv.tag, error_status_tlv.payload),
        error_index=decode_value(error_index_tlv.tag, error_index_tlv.payload),
        varbinds=varbinds,
    )


def build_response(
    community: str,
    request_id: int,
    varbinds: Sequence[VarBind],
    error_status: int = 0,
    error_index: int = 0,
) -> bytes:
    """Encodes an SNMPv1 Response PDU (used by the NTCIP emulator)."""
    encoded = b""
    for vb in varbinds:
        if vb.value is None:
            value_bytes = encode_null()
        elif isinstance(vb.value, bool):
            value_bytes = encode_integer(int(vb.value))
        elif isinstance(vb.value, int):
            value_bytes = encode_integer(vb.value)
        elif isinstance(vb.value, (bytes, str)):
            value_bytes = encode_octet_string(vb.value)
        else:
            raise ValueError("Unsupported varbind value type")
        encoded += encode_sequence(encode_oid(vb.oid), value_bytes)

    pdu_body = (
        encode_integer(request_id)
        + encode_integer(error_status)
        + encode_integer(error_index)
        + _encode_tlv(TAG_SEQUENCE, encoded)
    )
    pdu = _encode_tlv(TAG_GET_RESPONSE, pdu_body)
    return encode_sequence(
        encode_integer(SNMP_VERSION_1), encode_octet_string(community), pdu
    )
