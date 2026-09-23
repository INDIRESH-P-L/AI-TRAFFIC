"""TRAFFICINTEL AI - Single-Writer Lease for the Controller Poller

The poller runs in-process. Run two API replicas and both poll every
controller, writing two `signal_state_logs` rows per observation - which would
silently double every throughput, arrival-on-green and split-failure figure
derived from that log.

That failure is worse than an outage. An outage is visible; a doubled
measurement looks like a busy junction, and an operator would act on it.

So polling is leader-elected: exactly one instance holds a lease at a time, and
an instance that does not hold it does not poll. The instance that is not
polling says so - `NOT_LEADER` in its poller status - rather than appearing
idle, because "another instance is doing this" and "polling is broken" must not
look the same on a status page.

Why a database lease rather than a Postgres advisory lock: SQLite is a
supported dialect, the lease has to be *inspectable* (an operator needs to see
which instance is writing), and a lease with a heartbeat recovers on its own
when a holder dies, whereas a lock held by a wedged process does not.
"""

from __future__ import annotations

import logging
import os
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.models.entities import PollerLease, utc_now

logger = logging.getLogger("trafficintel.ingest.lease")

#: The single lease every poller contends for.
LEASE_NAME = "controller_poller"

#: A lease older than this is considered abandoned and may be taken over.
#: Comfortably longer than the poll interval so an instance that is merely slow
#: does not lose the lease to a peer and start alternating with it.
LEASE_TTL_SEC = 30.0

#: Identifies this process in the lease and in operator-facing status.
INSTANCE_ID = "{}:{}:{}".format(
    socket.gethostname(), os.getpid(), uuid.uuid4().hex[:8]
)


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def try_acquire(db: Session, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Acquires or renews the poll lease for this instance.

    Returns (holds_lease, human-readable reason).
    """
    now = now or datetime.now(timezone.utc)

    try:
        lease = (
            db.query(PollerLease)
            .filter(PollerLease.name == LEASE_NAME)
            .with_for_update(nowait=False)
            .first()
        )
    except (OperationalError, NotImplementedError):
        # SQLite has no SELECT ... FOR UPDATE. Its writes are serialised by the
        # database lock anyway, and a single-file deployment is single-instance
        # by construction, so the unlocked read is sound there.
        lease = (
            db.query(PollerLease).filter(PollerLease.name == LEASE_NAME).first()
        )

    if lease is None:
        lease = PollerLease(
            name=LEASE_NAME,
            holder_id=INSTANCE_ID,
            acquired_at=_naive(now),
            heartbeat_at=_naive(now),
        )
        db.add(lease)
        try:
            db.commit()
        except IntegrityError:
            # Another instance created it in the gap; fall through and contend
            # for it on the next cycle rather than guessing who won.
            db.rollback()
            return False, (
                "Another instance created the poll lease at the same moment. "
                "Not polling this cycle."
            )
        return True, "Acquired the poll lease (no previous holder)."

    if lease.holder_id == INSTANCE_ID:
        lease.heartbeat_at = _naive(now)
        db.commit()
        return True, "Holding the poll lease."

    heartbeat = _as_utc(lease.heartbeat_at)
    age_sec = (now - heartbeat).total_seconds() if heartbeat else None

    if age_sec is not None and age_sec <= LEASE_TTL_SEC:
        return False, (
            "Instance {} holds the poll lease (last heartbeat {:.0f}s ago). This "
            "instance is not polling, so observations are recorded exactly once."
            .format(lease.holder_id, age_sec)
        )

    # The holder stopped heartbeating: take over.
    previous = lease.holder_id
    lease.holder_id = INSTANCE_ID
    lease.acquired_at = _naive(now)
    lease.heartbeat_at = _naive(now)
    db.commit()
    return True, (
        "Took over the poll lease from {} after {} without a heartbeat."
        .format(previous, "no recorded heartbeat" if age_sec is None
                else "{:.0f}s".format(age_sec))
    )


def release(db: Session) -> bool:
    """Releases the lease if this instance holds it.

    Called on clean shutdown so a rolling restart hands over in seconds rather
    than leaving the network unpolled for a full TTL.
    """
    lease = db.query(PollerLease).filter(PollerLease.name == LEASE_NAME).first()
    if lease is None or lease.holder_id != INSTANCE_ID:
        return False
    # Backdated rather than deleted: the row stays inspectable, and any peer
    # sees an immediately-expired lease it may take over.
    lease.heartbeat_at = _naive(
        datetime.now(timezone.utc) - timedelta(seconds=LEASE_TTL_SEC + 1)
    )
    db.commit()
    return True


def current_holder(db: Session) -> Optional[dict]:
    """Reports the lease as it stands, for operator-facing status."""
    lease = db.query(PollerLease).filter(PollerLease.name == LEASE_NAME).first()
    if lease is None:
        return None
    heartbeat = _as_utc(lease.heartbeat_at)
    age = (
        (datetime.now(timezone.utc) - heartbeat).total_seconds()
        if heartbeat else None
    )
    return {
        "holder_id": lease.holder_id,
        "is_this_instance": lease.holder_id == INSTANCE_ID,
        "acquired_at": _as_utc(lease.acquired_at).isoformat() if lease.acquired_at else None,
        "heartbeat_at": heartbeat.isoformat() if heartbeat else None,
        "heartbeat_age_sec": round(age, 1) if age is not None else None,
        "expired": age is None or age > LEASE_TTL_SEC,
        "ttl_sec": LEASE_TTL_SEC,
    }
