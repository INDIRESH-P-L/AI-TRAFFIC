"""TRAFFICINTEL AI - GTFS-Realtime Protocol Buffers Codec (dependency-free)

GTFS-Realtime feeds are Protocol Buffers messages defined by
`gtfs-realtime.proto`. The platform carries no protobuf runtime - the same
decision made for SNMP (see snmp_codec.py) - so this module decodes the wire
format directly and extracts the fields transit signal priority needs:

    FeedMessage        header = 1, entity = 2 (repeated)
    FeedHeader         gtfs_realtime_version = 1, incrementality = 2, timestamp = 3
    FeedEntity         id = 1, is_deleted = 2, trip_update = 3, vehicle = 4
    VehiclePosition    trip = 1, position = 2, timestamp = 5, vehicle = 8
    Position           latitude = 1 (float), longitude = 2 (float),
                       bearing = 3 (float), speed = 5 (float, m/s)
    TripUpdate         trip = 1, stop_time_update = 2 (repeated), vehicle = 3,
                       timestamp = 4, delay = 5 (int32)
    StopTimeUpdate     stop_sequence = 1, arrival = 2, departure = 3, stop_id = 4
    StopTimeEvent      delay = 1 (int32), time = 2 (int64)
    TripDescriptor     trip_id = 1, route_id = 5, direction_id = 6
    VehicleDescriptor  id = 1, label = 2

Unknown fields are skipped, as the protobuf specification requires, so a feed
carrying extensions or newer fields still decodes. A malformed message raises
rather than yielding a partially invented vehicle.

The small encoder at the end exists so tests can build protocol-exact feeds.
It is never used to produce data the platform acts on.
"""

from __future__ import annotations

import struct
from typing import Any, Dict, List, Optional, Tuple

WIRE_VARINT, WIRE_FIXED64, WIRE_LENGTH, WIRE_FIXED32 = 0, 1, 2, 5


class GtfsRtDecodeError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Wire format
# ---------------------------------------------------------------------------

def _read_varint(data: bytes, pos: int) -> Tuple[int, int]:
    result, shift = 0, 0
    while True:
        if pos >= len(data):
            raise GtfsRtDecodeError("Truncated varint")
        byte = data[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise GtfsRtDecodeError("Varint longer than 64 bits")


def _fields(data: bytes) -> Dict[int, List[Tuple[int, Any]]]:
    """Parses one message into {field_number: [(wire_type, raw_value), ...]}."""
    fields: Dict[int, List[Tuple[int, Any]]] = {}
    pos = 0
    while pos < len(data):
        key, pos = _read_varint(data, pos)
        number, wire = key >> 3, key & 0x07
        if number == 0:
            raise GtfsRtDecodeError("Field number 0 is invalid")
        if wire == WIRE_VARINT:
            value, pos = _read_varint(data, pos)
        elif wire == WIRE_FIXED64:
            if pos + 8 > len(data):
                raise GtfsRtDecodeError("Truncated fixed64")
            value, pos = data[pos:pos + 8], pos + 8
        elif wire == WIRE_LENGTH:
            length, pos = _read_varint(data, pos)
            if pos + length > len(data):
                raise GtfsRtDecodeError("Length-delimited field overruns the message")
            value, pos = data[pos:pos + length], pos + length
        elif wire == WIRE_FIXED32:
            if pos + 4 > len(data):
                raise GtfsRtDecodeError("Truncated fixed32")
            value, pos = data[pos:pos + 4], pos + 4
        else:
            raise GtfsRtDecodeError("Unsupported wire type {}".format(wire))
        fields.setdefault(number, []).append((wire, value))
    return fields


def _first(fields, number, wire=None):
    for w, value in fields.get(number, []):
        if wire is None or w == wire:
            return value
    return None


def _string(fields, number) -> Optional[str]:
    raw = _first(fields, number, WIRE_LENGTH)
    return raw.decode("utf-8", errors="replace") if raw is not None else None


def _float32(fields, number) -> Optional[float]:
    raw = _first(fields, number, WIRE_FIXED32)
    return struct.unpack("<f", raw)[0] if raw is not None else None


def _uint(fields, number) -> Optional[int]:
    return _first(fields, number, WIRE_VARINT)


def _int32(fields, number) -> Optional[int]:
    """int32 is varint-encoded; negatives arrive as 64-bit two's complement."""
    raw = _first(fields, number, WIRE_VARINT)
    if raw is None:
        return None
    if raw >= 1 << 63:
        raw -= 1 << 64
    return raw


# ---------------------------------------------------------------------------
# Schema-directed decoding
# ---------------------------------------------------------------------------

def _trip(data: Optional[bytes]) -> Dict[str, Any]:
    if data is None:
        return {}
    f = _fields(data)
    return {"trip_id": _string(f, 1), "route_id": _string(f, 5), "direction_id": _uint(f, 6)}


def _vehicle_descriptor(data: Optional[bytes]) -> Dict[str, Any]:
    if data is None:
        return {}
    f = _fields(data)
    return {"id": _string(f, 1), "label": _string(f, 2)}


def _vehicle_position(data: bytes) -> Dict[str, Any]:
    f = _fields(data)
    position = _first(f, 2, WIRE_LENGTH)
    pos = _fields(position) if position is not None else {}
    speed = _float32(pos, 5)
    return {
        "trip": _trip(_first(f, 1, WIRE_LENGTH)),
        "vehicle": _vehicle_descriptor(_first(f, 8, WIRE_LENGTH)),
        "latitude": _float32(pos, 1),
        "longitude": _float32(pos, 2),
        "bearing_deg": _float32(pos, 3),
        "speed_mps": speed,
        "timestamp": _uint(f, 5),
    }


def _stop_time_event(data: Optional[bytes]) -> Dict[str, Any]:
    if data is None:
        return {}
    f = _fields(data)
    return {"delay_sec": _int32(f, 1), "time": _int32(f, 2)}


def _trip_update(data: bytes) -> Dict[str, Any]:
    f = _fields(data)
    stops = []
    for wire, raw in f.get(2, []):
        if wire != WIRE_LENGTH:
            continue
        s = _fields(raw)
        stops.append({
            "stop_sequence": _uint(s, 1),
            "stop_id": _string(s, 4),
            "arrival": _stop_time_event(_first(s, 2, WIRE_LENGTH)),
            "departure": _stop_time_event(_first(s, 3, WIRE_LENGTH)),
        })
    return {
        "trip": _trip(_first(f, 1, WIRE_LENGTH)),
        "vehicle": _vehicle_descriptor(_first(f, 3, WIRE_LENGTH)),
        "timestamp": _uint(f, 4),
        "delay_sec": _int32(f, 5),
        "stop_time_updates": stops,
    }


def decode_feed(data: bytes) -> Dict[str, Any]:
    """Decodes a FeedMessage into its header, vehicle positions and trip updates."""
    if not data:
        raise GtfsRtDecodeError("Empty feed")
    f = _fields(data)
    header_raw = _first(f, 1, WIRE_LENGTH)
    if header_raw is None:
        raise GtfsRtDecodeError("FeedMessage has no header (field 1 is required)")
    header = _fields(header_raw)

    vehicles, trip_updates = [], []
    for wire, raw in f.get(2, []):
        if wire != WIRE_LENGTH:
            continue
        entity = _fields(raw)
        if _uint(entity, 2):
            continue  # is_deleted
        entity_id = _string(entity, 1)
        vehicle = _first(entity, 4, WIRE_LENGTH)
        if vehicle is not None:
            vehicles.append({"entity_id": entity_id, **_vehicle_position(vehicle)})
        update = _first(entity, 3, WIRE_LENGTH)
        if update is not None:
            trip_updates.append({"entity_id": entity_id, **_trip_update(update)})

    return {
        "header": {
            "gtfs_realtime_version": _string(header, 1),
            "incrementality": _uint(header, 2),
            "timestamp": _uint(header, 3),
        },
        "vehicles": vehicles,
        "trip_updates": trip_updates,
    }


# ---------------------------------------------------------------------------
# Encoder (tests only)
# ---------------------------------------------------------------------------

def _varint(value: int) -> bytes:
    if value < 0:
        value += 1 << 64
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _key(number: int, wire: int) -> bytes:
    return _varint((number << 3) | wire)


def _len(number: int, payload: bytes) -> bytes:
    return _key(number, WIRE_LENGTH) + _varint(len(payload)) + payload


def _str(number: int, text: str) -> bytes:
    return _len(number, text.encode("utf-8"))


def _f32(number: int, value: float) -> bytes:
    return _key(number, WIRE_FIXED32) + struct.pack("<f", value)


def _vint(number: int, value: int) -> bytes:
    return _key(number, WIRE_VARINT) + _varint(value)


def encode_feed(timestamp: int, vehicles: List[Dict[str, Any]] = (),
                trip_updates: List[Dict[str, Any]] = ()) -> bytes:
    """Builds a FeedMessage. For tests: produces exactly what an agency serves."""
    header = _str(1, "2.0") + _vint(2, 0) + _vint(3, timestamp)
    body = _len(1, header)
    for index, v in enumerate(vehicles):
        trip = _str(1, v["trip_id"]) + _str(5, v.get("route_id", ""))
        position = _f32(1, v["latitude"]) + _f32(2, v["longitude"])
        if v.get("bearing_deg") is not None:
            position += _f32(3, v["bearing_deg"])
        if v.get("speed_mps") is not None:
            position += _f32(5, v["speed_mps"])
        vehicle = (_len(1, trip) + _len(2, position) + _vint(5, v["timestamp"])
                   + _len(8, _str(1, v["vehicle_id"])))
        body += _len(2, _str(1, "v{}".format(index)) + _len(4, vehicle))
    for index, u in enumerate(trip_updates):
        trip = _str(1, u["trip_id"]) + _str(5, u.get("route_id", ""))
        update = _len(1, trip)
        if u.get("stop_delay_sec") is not None:
            arrival = _vint(1, u["stop_delay_sec"])
            update += _len(2, _vint(1, u.get("stop_sequence", 1)) + _len(2, arrival))
        if u.get("vehicle_id"):
            update += _len(3, _str(1, u["vehicle_id"]))
        update += _vint(4, u.get("timestamp", timestamp))
        if u.get("delay_sec") is not None:
            update += _vint(5, u["delay_sec"])
        body += _len(2, _str(1, "t{}".format(index)) + _len(3, update))
    return body
