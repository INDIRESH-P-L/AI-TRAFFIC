"""TRAFFICINTEL AI - NMEA 0183 RMC Parsing for Emergency Vehicle AVL

The Recommended Minimum (RMC) sentence is what GPS receivers and most vehicle
AVL units emit: position, speed, course, and a validity flag.

    $GPRMC,123519.00,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A

This parser is strict on purpose. A position that decides whether an ambulance
gets a green light must be one the receiver itself marked valid and whose
checksum matches; anything else is rejected with the reason, never "repaired".

* The checksum (XOR of every character between '$' and '*') must match.
* The status field must be 'A' (valid). 'V' means the receiver has no fix -
  its coordinates are stale or invented by the receiver, and acting on them
  could preempt the wrong junction.
* Any talker ID is accepted (GP, GN, GL, GA, BD): the sentence format is the same.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

KNOTS_TO_KPH = 1.852


class NmeaError(ValueError):
    """A sentence that cannot be trusted, with a stable machine-readable code."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(detail)


@dataclass
class RmcFix:
    latitude: float
    longitude: float
    speed_kph: float
    heading_deg: Optional[float]
    reported_at: datetime
    raw: str


def nmea_checksum(body: str) -> str:
    value = 0
    for character in body:
        value ^= ord(character)
    return "{:02X}".format(value)


def _coordinate(value: str, hemisphere: str, degree_digits: int) -> float:
    if not value or not hemisphere:
        raise NmeaError("MISSING_COORDINATE", "Coordinate field is empty.")
    degrees = int(value[:degree_digits])
    minutes = float(value[degree_digits:])
    if minutes >= 60:
        raise NmeaError("INVALID_COORDINATE", "Minutes field {} is out of range.".format(minutes))
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    elif hemisphere not in ("N", "E"):
        raise NmeaError("INVALID_COORDINATE", "Unknown hemisphere '{}'.".format(hemisphere))
    return decimal


def parse_rmc(sentence: str) -> RmcFix:
    """Parses and validates one RMC sentence, or raises NmeaError."""
    sentence = (sentence or "").strip()
    if not sentence.startswith("$") or "*" not in sentence:
        raise NmeaError("NOT_AN_NMEA_SENTENCE", "Expected '$...*hh'.")

    body, _, checksum = sentence[1:].partition("*")
    if nmea_checksum(body) != checksum.strip().upper()[:2]:
        raise NmeaError(
            "CHECKSUM_MISMATCH",
            "Checksum {} does not match the sentence ({}). The position may have been "
            "corrupted in transit and is not used.".format(checksum, nmea_checksum(body)),
        )

    fields = body.split(",")
    if len(fields[0]) != 5 or not fields[0].endswith("RMC"):
        raise NmeaError("NOT_AN_RMC_SENTENCE", "Sentence type {} is not RMC.".format(fields[0]))
    if len(fields) < 10:
        raise NmeaError("TRUNCATED_SENTENCE", "RMC sentence has {} fields.".format(len(fields)))

    if fields[2] != "A":
        raise NmeaError(
            "NO_GPS_FIX",
            "Receiver status is '{}', not 'A': it has no valid fix, so its coordinates "
            "cannot be used to choose a junction.".format(fields[2] or "empty"),
        )

    try:
        latitude = _coordinate(fields[3], fields[4], 2)
        longitude = _coordinate(fields[5], fields[6], 3)
        speed_kph = float(fields[7] or 0.0) * KNOTS_TO_KPH
        heading = float(fields[8]) if fields[8] else None
        time_field, date_field = fields[1], fields[9]
        # RMC carries a two-digit year. Pivot at 80, the common receiver
        # convention; the freshness check downstream rejects any fix far from
        # now whichever century it lands in.
        two_digit_year = int(date_field[4:6])
        reported_at = datetime(
            (1900 if two_digit_year >= 80 else 2000) + two_digit_year,
            int(date_field[2:4]), int(date_field[0:2]),
            int(time_field[0:2]), int(time_field[2:4]), int(float(time_field[4:])),
            tzinfo=timezone.utc,
        )
    except NmeaError:
        raise
    except (ValueError, IndexError) as exc:
        raise NmeaError("MALFORMED_FIELD", "Could not parse RMC fields: {}".format(exc))

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise NmeaError("INVALID_COORDINATE", "Coordinates out of range.")

    return RmcFix(latitude=latitude, longitude=longitude, speed_kph=speed_kph,
                  heading_deg=heading, reported_at=reported_at, raw=sentence)


def build_rmc(latitude: float, longitude: float, speed_kph: float, heading_deg: float,
              when: datetime, status: str = "A", talker: str = "GP") -> str:
    """Encodes an RMC sentence. Used by tests to produce protocol-exact input."""
    lat_deg, lon_deg = int(abs(latitude)), int(abs(longitude))
    lat = "{:02d}{:07.4f}".format(lat_deg, (abs(latitude) - lat_deg) * 60)
    lon = "{:03d}{:07.4f}".format(lon_deg, (abs(longitude) - lon_deg) * 60)
    body = "{}RMC,{},{},{},{},{},{},{:.1f},{:.1f},{},,".format(
        talker, when.strftime("%H%M%S.00"), status,
        lat, "N" if latitude >= 0 else "S", lon, "E" if longitude >= 0 else "W",
        speed_kph / KNOTS_TO_KPH, heading_deg, when.strftime("%d%m%y"),
    )
    return "${}*{}".format(body, nmea_checksum(body))
