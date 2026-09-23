"""TRAFFICINTEL AI - API Keys with Scopes

Keys are for machine callers: an ingest agent posting detector telemetry, a
reporting job pulling analytics.

Security properties:

* **The key is shown once, at creation, and never again.** Only a SHA-256 hash
  is stored, so a database disclosure does not hand over working credentials.
* **A key carries scopes, and cannot hold a scope its creator lacks.** An
  ENGINEER cannot mint an admin key, which would otherwise be a trivial
  privilege-escalation path.
* **Keys expire.** An unbounded credential is one nobody ever revokes.
* **A key can never hold `signal:command`.** Issuing a signal change is an
  action with a named accountable operator behind it; a shared machine
  credential has no such person, and the audit ledger would record a
  meaningless actor. Machine callers ingest and read; they do not command
  traffic signals.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.governance import scopes as scope_vocab
from app.models.entities import ApiKey, utc_now

logger = logging.getLogger("trafficintel.governance.apikeys")

KEY_PREFIX = "tiai"
KEY_BYTES = 32

#: Scopes a machine credential may never hold, whatever its creator holds.
FORBIDDEN_FOR_KEYS = {
    scope_vocab.COMMAND_SIGNAL,
    scope_vocab.MANAGE_USERS,
    scope_vocab.MANAGE_API_KEYS,
}


def hash_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_key() -> Tuple[str, str, str]:
    """Returns (raw_key, key_hash, display_prefix).

    The display prefix is stored so an operator can recognise a key in a list
    without the key itself being recoverable.
    """
    secret = secrets.token_urlsafe(KEY_BYTES)
    raw = "{}_{}".format(KEY_PREFIX, secret)
    return raw, hash_key(raw), raw[: len(KEY_PREFIX) + 9]


def create_api_key(
    db: Session,
    name: str,
    requested_scopes: List[str],
    creator_role: str,
    creator_username: str,
    expires_in_days: int = 90,
) -> Dict[str, Any]:
    """Creates a key. Raises ValueError with a specific reason on refusal."""
    unknown = scope_vocab.validate_scopes(requested_scopes)
    if unknown:
        raise ValueError("Unknown scopes: {}".format(sorted(unknown)))

    forbidden = sorted(set(requested_scopes) & FORBIDDEN_FOR_KEYS)
    if forbidden:
        raise ValueError(
            "These scopes cannot be granted to an API key: {}. Issuing a signal "
            "change requires a named accountable operator; a shared machine "
            "credential would record a meaningless actor in the audit ledger."
            .format(forbidden)
        )

    creator_scopes = scope_vocab.scopes_for_role(creator_role)
    escalation = sorted(set(requested_scopes) - creator_scopes)
    if escalation:
        raise ValueError(
            "You cannot grant scopes you do not hold: {}. Your role ({}) does not "
            "include them.".format(escalation, creator_role)
        )

    raw, key_hash, prefix = generate_key()
    record = ApiKey(
        name=name,
        key_hash=key_hash,
        key_prefix=prefix,
        scopes=sorted(set(requested_scopes)),
        created_by=creator_username,
        expires_at=utc_now() + timedelta(days=expires_in_days),
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "id": record.id,
        "name": record.name,
        "key_prefix": record.key_prefix,
        "scopes": record.scopes,
        "expires_at": record.expires_at.isoformat(),
        # The one and only time this value exists outside the caller's hands.
        "api_key": raw,
        "warning": (
            "This key is shown once and cannot be retrieved again. Only its hash "
            "is stored. Record it now or issue a new one."
        ),
    }


def resolve_api_key(db: Session, raw_key: str) -> Optional[ApiKey]:
    """Returns the active, unexpired key matching this secret, or None."""
    if not raw_key or not raw_key.startswith(KEY_PREFIX):
        return None

    record = db.query(ApiKey).filter(ApiKey.key_hash == hash_key(raw_key)).first()
    if record is None or not record.is_active:
        return None

    expires_at = record.expires_at
    if expires_at is not None:
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at < datetime.now(timezone.utc):
            return None

    record.last_used_at = utc_now()
    record.use_count = (record.use_count or 0) + 1
    db.commit()
    return record


def revoke_api_key(db: Session, key_id: str) -> bool:
    record = db.query(ApiKey).filter(ApiKey.id == key_id).first()
    if record is None:
        return False
    record.is_active = False
    record.revoked_at = utc_now()
    db.commit()
    return True
