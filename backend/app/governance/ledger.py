"""TRAFFICINTEL AI - Tamper-Evident Audit Ledger

Every audit entry is chained to the one before it:

    entry_hash = SHA256( sequence || previous_hash || canonical(entry_fields) )

Altering or deleting any historical row breaks the chain from that point
onward, and `verify_chain` reports exactly which sequence number broke and how.

**What this does and does not give you.** A hash chain makes tampering
*detectable*, not *impossible*. Anyone who can write to the database can also
recompute every subsequent hash. It raises the cost of quiet tampering from
"edit one row" to "rewrite the entire tail", and it makes a partial edit
obvious. For tamper-*proofing* the export must be anchored somewhere the
database administrator does not control — periodic signed exports to
write-once storage. The export endpoint exists for exactly that, and the
platform states this limitation rather than implying more than it delivers.

**Concurrency.** Chain integrity requires appends to be serialised: two
concurrent writers reading the same tip would produce two entries claiming the
same predecessor. A process-level lock covers a single API process. A
multi-process deployment must serialise appends at the database (a transaction
-level advisory lock on PostgreSQL); `verify_chain` detects it if that is not
done, rather than the corruption passing silently.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session

from app.models.entities import AuditLog, generate_uuid, utc_now

logger = logging.getLogger("trafficintel.governance.ledger")

GENESIS_HASH = "0" * 64

_append_lock = threading.Lock()


def _canonical(entry: AuditLog) -> str:
    """Stable serialisation of the fields the hash covers.

    Sorted keys and a fixed separator so the same entry always hashes the same
    way regardless of dict ordering or JSON library behaviour.
    """
    payload = {
        "actor_username": entry.actor_username,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "result": entry.result,
        "details": entry.details,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_hash(sequence: int, previous_hash: str, entry: AuditLog) -> str:
    material = "{}|{}|{}".format(sequence, previous_hash, _canonical(entry))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def chain_tip(db: Session) -> Dict[str, Any]:
    """The current end of the chain."""
    last = (
        db.query(AuditLog)
        .filter(AuditLog.sequence.isnot(None))
        .order_by(AuditLog.sequence.desc())
        .first()
    )
    if last is None:
        return {"sequence": 0, "hash": GENESIS_HASH}
    return {"sequence": last.sequence, "hash": last.entry_hash or GENESIS_HASH}


def stamp_pending_entries(session: Session) -> None:
    """Assigns sequence and hash to every AuditLog being inserted.

    Registered as a `before_flush` listener so existing call sites that add an
    AuditLog directly are chained automatically. Chaining at the boundary
    rather than at each call site means a new endpoint cannot forget to do it.
    """
    pending = [obj for obj in session.new if isinstance(obj, AuditLog)]
    if not pending:
        return

    with _append_lock:
        tip = chain_tip(session)
        sequence = tip["sequence"]
        previous = tip["hash"]

        # Column defaults (timestamp, id) are applied by SQLAlchemy at INSERT,
        # which is AFTER before_flush. Hashing an entry whose timestamp is
        # still None would produce a digest that never matches the stored row,
        # so both are materialised here, before they are hashed.
        for entry in pending:
            if entry.timestamp is None:
                entry.timestamp = utc_now()
            # The DateTime column is naive, so an aware value written here
            # reads back without its offset and would hash differently. The
            # stored form is normalised BEFORE hashing, so the digest covers
            # exactly the bytes that end up in the row.
            if entry.timestamp.tzinfo is not None:
                entry.timestamp = entry.timestamp.astimezone(timezone.utc).replace(tzinfo=None)
            if entry.id is None:
                entry.id = generate_uuid()

        # Deterministic order for entries added in the same flush.
        for entry in sorted(pending, key=lambda e: (e.timestamp or datetime.min, e.id or "")):
            if entry.sequence is not None:
                continue  # already chained
            sequence += 1
            entry.sequence = sequence
            entry.previous_hash = previous
            entry.entry_hash = compute_hash(sequence, previous, entry)
            previous = entry.entry_hash


def install_listener() -> None:
    """Ensures the chaining listener is active.

    The listener is registered by `app.models.entities` at import time, so an
    audit row written outside a running application - by a script, a migration
    helper or a test - is chained too. An unchained row would be a silent gap
    in a ledger whose entire purpose is that gaps are not silent.

    This function remains as the explicit entry point called at startup, and
    is idempotent.
    """
    from app.models.entities import _install_audit_chaining

    _install_audit_chaining()
    logger.info("Audit ledger chaining listener active")


def verify_chain(db: Session, limit: Optional[int] = None) -> Dict[str, Any]:
    """Recomputes every hash and reports the first break, if any."""
    query = db.query(AuditLog).order_by(AuditLog.sequence.asc())
    entries: List[AuditLog] = [e for e in query.all() if e.sequence is not None]

    if limit:
        entries = entries[-limit:]

    if not entries:
        return {
            "status": "EMPTY",
            "entries_verified": 0,
            "detail": "The audit ledger contains no chained entries yet.",
            "tamper_evidence_note": _EVIDENCE_NOTE,
        }

    expected_previous = GENESIS_HASH if entries[0].sequence == 1 else entries[0].previous_hash
    expected_sequence = entries[0].sequence

    for entry in entries:
        if entry.sequence != expected_sequence:
            return {
                "status": "BROKEN",
                "break_type": "SEQUENCE_GAP",
                "broken_at_sequence": entry.sequence,
                "expected_sequence": expected_sequence,
                "entries_verified": expected_sequence - entries[0].sequence,
                "detail": (
                    "Expected sequence {} but found {}. Entries were deleted or "
                    "inserted out of order.".format(expected_sequence, entry.sequence)
                ),
                "tamper_evidence_note": _EVIDENCE_NOTE,
            }

        if entry.previous_hash != expected_previous:
            return {
                "status": "BROKEN",
                "break_type": "PREVIOUS_HASH_MISMATCH",
                "broken_at_sequence": entry.sequence,
                "entries_verified": expected_sequence - entries[0].sequence,
                "detail": (
                    "Entry {} claims predecessor {} but the chain expects {}.".format(
                        entry.sequence,
                        (entry.previous_hash or "")[:16],
                        (expected_previous or "")[:16],
                    )
                ),
                "tamper_evidence_note": _EVIDENCE_NOTE,
            }

        recomputed = compute_hash(entry.sequence, entry.previous_hash or GENESIS_HASH, entry)
        if recomputed != entry.entry_hash:
            return {
                "status": "BROKEN",
                "break_type": "ENTRY_MODIFIED",
                "broken_at_sequence": entry.sequence,
                "entries_verified": expected_sequence - entries[0].sequence,
                "detail": (
                    "Entry {} does not hash to its stored value: its contents were "
                    "modified after it was written.".format(entry.sequence)
                ),
                "recomputed_hash": recomputed,
                "stored_hash": entry.entry_hash,
                "tamper_evidence_note": _EVIDENCE_NOTE,
            }

        expected_previous = entry.entry_hash
        expected_sequence += 1

    return {
        "status": "INTACT",
        "entries_verified": len(entries),
        "first_sequence": entries[0].sequence,
        "last_sequence": entries[-1].sequence,
        "chain_tip_hash": entries[-1].entry_hash,
        "detail": "Every entry hashes to its stored value and links to its predecessor.",
        "tamper_evidence_note": _EVIDENCE_NOTE,
    }


_EVIDENCE_NOTE = (
    "A hash chain makes tampering detectable, not impossible: anyone with write "
    "access to the database can recompute the tail. Export the ledger periodically "
    "to storage the database administrator does not control to obtain an external "
    "anchor."
)


def export_entries(db: Session, since_sequence: int = 0) -> Dict[str, Any]:
    """Full chained export, suitable for anchoring outside this database."""
    entries = (
        db.query(AuditLog)
        .filter(AuditLog.sequence > since_sequence)
        .order_by(AuditLog.sequence.asc())
        .all()
    )

    rows = [
        {
            "sequence": entry.sequence,
            "previous_hash": entry.previous_hash,
            "entry_hash": entry.entry_hash,
            "actor_username": entry.actor_username,
            "action": entry.action,
            "resource_type": entry.resource_type,
            "resource_id": entry.resource_id,
            "result": entry.result,
            "details": entry.details,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        }
        for entry in entries
    ]

    # A digest over the export lets a verifier check the whole file at once.
    digest_material = json.dumps(rows, sort_keys=True, separators=(",", ":"), default=str)
    export_digest = hashlib.sha256(digest_material.encode("utf-8")).hexdigest()

    return {
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "since_sequence": since_sequence,
        "entry_count": len(rows),
        "export_sha256": export_digest,
        "hash_algorithm": "SHA-256",
        "chain_formula": "entry_hash = SHA256(sequence || previous_hash || canonical_json(entry))",
        "verification": verify_chain(db),
        "entries": rows,
    }
