"""TRAFFICINTEL AI - NTCIP 1202 Object Identifiers

Object identifiers for the actuated signal controller (ASC) objects this
platform reads and writes, per NTCIP 1202 "Object Definitions for Actuated
Signal Controllers".

Two notes for integrators:

1. Vendors vary. Several manufacturers expose the standard status objects at
   the standard OIDs but gate control objects behind vendor-specific access
   rules or alternative branches. Every OID here is therefore assembled from
   named table/column constants and can be overridden per controller via
   `SignalController.config`, rather than being hard-coded at the call site.

2. Phase status objects are BITMAPS, not phase numbers. `phaseStatusGroupGreens`
   for group 1 is a single octet in which bit 0 represents phase 1 and bit 7
   represents phase 8. Group N covers phases (8N-7) through 8N. Decoding that
   bitmap is the only supported way to learn which phase is actually displaying
   green; this module never guesses a phase number.
"""

from __future__ import annotations

from typing import Dict, List, Optional

# Root of the NTCIP actuated signal controller branch:
# iso(1).org(3).dod(6).internet(1).private(4).enterprises(1).nema(1206)
#   .tmibs(4).tmibs-devices(2).asc(1)
ASC_ROOT = "1.3.6.1.4.1.1206.4.2.1"

# --- phase group (asc.phase = .1) ------------------------------------------
PHASE_GROUP = ASC_ROOT + ".1"

MAX_PHASES_OID = PHASE_GROUP + ".1.0"

# phaseStatusGroupTable (asc.phase.phaseStatusGroup = .1.4), entry .1
PHASE_STATUS_GROUP_ENTRY = PHASE_GROUP + ".4.1"
COL_STATUS_GROUP_NUMBER = 1
COL_STATUS_GROUP_REDS = 2
COL_STATUS_GROUP_YELLOWS = 3
COL_STATUS_GROUP_GREENS = 4
COL_STATUS_GROUP_DONT_WALKS = 5
COL_STATUS_GROUP_PED_CLEARS = 6
COL_STATUS_GROUP_WALKS = 7
COL_STATUS_GROUP_VEH_CALLS = 8
COL_STATUS_GROUP_PED_CALLS = 9
COL_STATUS_GROUP_PHASE_ONS = 10
COL_STATUS_GROUP_PHASE_NEXTS = 11

# phaseControlGroupTable (asc.phase.phaseControlGroup = .1.5), entry .1
PHASE_CONTROL_GROUP_ENTRY = PHASE_GROUP + ".5.1"
COL_CONTROL_GROUP_NUMBER = 1
COL_CONTROL_GROUP_PHASE_OMIT = 2
COL_CONTROL_GROUP_PED_OMIT = 3
COL_CONTROL_GROUP_HOLD = 4
COL_CONTROL_GROUP_FORCE_OFF = 5
COL_CONTROL_GROUP_VEH_CALL = 6
COL_CONTROL_GROUP_PED_CALL = 7

# Phases per status/control group, fixed by the standard's bitmap width.
PHASES_PER_GROUP = 8


def status_group_oid(column: int, group: int = 1) -> str:
    """OID of one column of phaseStatusGroupTable for the given group."""
    return PHASE_STATUS_GROUP_ENTRY + "." + str(column) + "." + str(group)


def control_group_oid(column: int, group: int = 1) -> str:
    """OID of one column of phaseControlGroupTable for the given group."""
    return PHASE_CONTROL_GROUP_ENTRY + "." + str(column) + "." + str(group)


def group_for_phase(phase_number: int) -> int:
    """Status/control group that carries the given phase number (1-based)."""
    if phase_number < 1:
        raise ValueError("Phase numbers are 1-based")
    return ((phase_number - 1) // PHASES_PER_GROUP) + 1


def bit_for_phase(phase_number: int) -> int:
    """Bit position of the phase within its group's bitmap octet."""
    if phase_number < 1:
        raise ValueError("Phase numbers are 1-based")
    return (phase_number - 1) % PHASES_PER_GROUP


def phase_bitmap_to_numbers(bitmap: int, group: int = 1) -> List[int]:
    """Decodes an NTCIP phase-status bitmap octet into phase numbers.

    Bit 0 of group 1 is phase 1; bit 7 of group 2 is phase 16, and so on.
    Returns an empty list when no bit is set, which is a truthful reading of a
    controller that is displaying no green in that group (for example, during
    an all-red clearance interval).
    """
    if bitmap is None:
        raise ValueError("Cannot decode a bitmap from a missing value")
    base = (group - 1) * PHASES_PER_GROUP
    return [
        base + bit + 1
        for bit in range(PHASES_PER_GROUP)
        if bitmap & (1 << bit)
    ]


def phase_numbers_to_bitmap(phase_numbers: List[int], group: int = 1) -> int:
    """Encodes phase numbers into a single group's bitmap octet."""
    base = (group - 1) * PHASES_PER_GROUP
    bitmap = 0
    for phase in phase_numbers:
        offset = phase - base - 1
        if 0 <= offset < PHASES_PER_GROUP:
            bitmap |= 1 << offset
    return bitmap


# Convenience map of the status objects polled on every heartbeat.
def status_read_plan(group: int = 1) -> Dict[str, str]:
    """OIDs read on each poll, keyed by the field they populate."""
    return {
        "greens": status_group_oid(COL_STATUS_GROUP_GREENS, group),
        "yellows": status_group_oid(COL_STATUS_GROUP_YELLOWS, group),
        "reds": status_group_oid(COL_STATUS_GROUP_REDS, group),
        "phase_ons": status_group_oid(COL_STATUS_GROUP_PHASE_ONS, group),
        "phase_nexts": status_group_oid(COL_STATUS_GROUP_PHASE_NEXTS, group),
        "veh_calls": status_group_oid(COL_STATUS_GROUP_VEH_CALLS, group),
        "ped_calls": status_group_oid(COL_STATUS_GROUP_PED_CALLS, group),
        "walks": status_group_oid(COL_STATUS_GROUP_WALKS, group),
    }
