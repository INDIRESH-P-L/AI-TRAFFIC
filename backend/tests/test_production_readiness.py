"""TRAFFICINTEL AI - Production Readiness Tests

Liveness/readiness probes, the single-writer poll lease, and the production
configuration guards.

The lease tests are the important ones. Two API replicas both running the
in-process poller would write two `signal_state_logs` rows per observation,
silently doubling every throughput and arrival-on-green figure derived from
that log. That is worse than an outage: an outage is visible, a doubled
measurement just looks like a busy junction, and an operator would act on it.
"""

import contextlib
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.ingest import lease
from app.main import app
from app.models.entities import PollerLease, User

client = TestClient(app)


@contextlib.contextmanager
def _environment(**overrides):
    """Temporarily overrides live settings, restoring them afterwards.

    The bootstrap reads `settings.ENVIRONMENT` at call time, and a test that
    left the process in production mode would change how every later test
    behaves.
    """
    from app.core.config import settings

    previous = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        object.__setattr__(settings, key, value)
    try:
        yield
    finally:
        for key, value in previous.items():
            object.__setattr__(settings, key, value)


@pytest.fixture(autouse=True)
def clean_lease():
    """Each test starts with no lease held."""
    db = SessionLocal()
    try:
        db.query(PollerLease).delete()
        db.commit()
    finally:
        db.close()
    yield
    db = SessionLocal()
    try:
        db.query(PollerLease).delete()
        db.commit()
    finally:
        db.close()


# ===========================================================================
# Liveness & readiness
# ===========================================================================

def test_probes_do_not_require_authentication():
    """A probe runs before anyone has a token.

    A readiness endpoint that returns 401 to its own orchestrator is
    indistinguishable from one that is down.
    """
    assert client.get("/api/v1/health/live").status_code == 200
    assert client.get("/api/v1/health/ready").status_code in (200, 503)


def test_liveness_touches_no_dependency():
    """A liveness probe that checks the database restarts a healthy app every
    time the database hiccups, turning a blip into a restart storm."""
    body = client.get("/api/v1/health/live").json()

    assert body["status"] == "ALIVE"
    assert "checks" not in body, "liveness must not perform dependency checks"
    assert "says nothing about whether its dependencies" in body["detail"]


def test_readiness_reports_each_check_with_a_reason():
    body = client.get("/api/v1/health/ready").json()

    assert body["status"] in ("READY", "NOT_READY")
    names = {check["name"] for check in body["checks"]}
    assert names == {"database_reachable", "schema_at_head"}

    for check in body["checks"]:
        assert check["detail"], "every check states what it found"
        assert check["why_it_blocks"], "every check states why it gates traffic"


def test_readiness_is_about_this_instance_not_the_field():
    """A controller being unreachable must not take the console out of rotation
    - operators need the console most when equipment is failing."""
    body = client.get("/api/v1/health/ready").json()
    assert "not a statement about field equipment" in body["scope_note"]


def test_probes_leak_nothing_about_the_network():
    """They are unauthenticated, so they must expose no operational detail."""
    for path in ("/api/v1/health/live", "/api/v1/health/ready"):
        text = client.get(path).text.lower()
        for leaked in ("intersection", "junction", "vehicle", "occupancy", "phase"):
            assert leaked not in text, "{} leaked '{}'".format(path, leaked)


# ===========================================================================
# Single-writer poll lease
# ===========================================================================

def test_first_instance_acquires_the_lease():
    db = SessionLocal()
    try:
        acquired, reason = lease.try_acquire(db)
        assert acquired is True
        assert "no previous holder" in reason
    finally:
        db.close()


def test_a_second_instance_does_not_poll_while_the_first_heartbeats():
    """The whole point: two live instances must not both write."""
    db = SessionLocal()
    try:
        assert lease.try_acquire(db)[0] is True

        # Simulate a peer process by rewriting the holder id.
        row = db.query(PollerLease).filter(PollerLease.name == lease.LEASE_NAME).first()
        row.holder_id = "other-host:999:abcdef12"
        row.heartbeat_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.commit()

        acquired, reason = lease.try_acquire(db)
        assert acquired is False
        assert "other-host:999:abcdef12" in reason
        assert "recorded exactly once" in reason
    finally:
        db.close()


def test_an_expired_lease_is_taken_over():
    """A holder that died must not leave the network unpolled forever."""
    db = SessionLocal()
    try:
        stale = datetime.now(timezone.utc) - timedelta(seconds=lease.LEASE_TTL_SEC + 10)
        db.add(PollerLease(
            name=lease.LEASE_NAME,
            holder_id="dead-host:1:deadbeef",
            acquired_at=stale.replace(tzinfo=None),
            heartbeat_at=stale.replace(tzinfo=None),
        ))
        db.commit()

        acquired, reason = lease.try_acquire(db)
        assert acquired is True
        assert "Took over" in reason
        assert "dead-host:1:deadbeef" in reason
    finally:
        db.close()


def test_renewing_does_not_reset_the_acquisition_time():
    """`acquired_at` is how long this instance has been the writer; resetting it
    on every heartbeat would make every holder look brand new."""
    db = SessionLocal()
    try:
        lease.try_acquire(db)
        row = db.query(PollerLease).filter(PollerLease.name == lease.LEASE_NAME).first()
        first_acquired = row.acquired_at

        later = datetime.now(timezone.utc) + timedelta(seconds=5)
        lease.try_acquire(db, now=later)
        db.refresh(row)

        assert row.acquired_at == first_acquired
        assert row.heartbeat_at > first_acquired
    finally:
        db.close()


def test_release_lets_a_peer_take_over_immediately():
    """A rolling restart must not leave the network unobserved for a full TTL."""
    db = SessionLocal()
    try:
        lease.try_acquire(db)
        assert lease.release(db) is True

        holder = lease.current_holder(db)
        assert holder["expired"] is True, "a released lease is immediately available"
    finally:
        db.close()


def test_a_non_holder_reports_not_leader_rather_than_looking_idle():
    """'Another instance is doing this' and 'polling is broken' must not look
    the same on a status page."""
    from app.ingest.poller import controller_poller

    db = SessionLocal()
    try:
        db.add(PollerLease(
            name=lease.LEASE_NAME,
            holder_id="other-host:42:cafebabe",
            acquired_at=datetime.now(timezone.utc).replace(tzinfo=None),
            heartbeat_at=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        db.commit()
    finally:
        db.close()

    cycle = controller_poller.poll_once()

    assert cycle["status"] == "NOT_LEADER"
    assert cycle["controllers_polled"] == 0
    assert "other-host:42:cafebabe" in cycle["detail"]

    status = controller_poller.status()
    assert status["is_polling_instance"] is False
    assert status["lease"]["holder_id"] == "other-host:42:cafebabe"
    assert "not missing" in status["lease_note"]


def test_the_holder_polls_normally():
    from app.ingest.poller import controller_poller

    cycle = controller_poller.poll_once()

    assert cycle["status"] != "NOT_LEADER"
    assert controller_poller.status()["is_polling_instance"] is True


# ===========================================================================
# Production configuration guards
# ===========================================================================

def _prod(**overrides):
    from app.core.config import Settings

    base = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "a" * 64,
        "BACKEND_CORS_ORIGINS": "https://traffic.example.gov",
    }
    base.update(overrides)
    return Settings(**base)


def test_production_refuses_the_published_placeholder_secret():
    from app.core.config import INSECURE_DEFAULT_SECRET_KEY

    with pytest.raises(ValueError, match="SECRET_KEY"):
        _prod(SECRET_KEY=INSECURE_DEFAULT_SECRET_KEY)


def test_production_refuses_localhost_cors():
    """A stale dev default is an access-control hole nothing in the UI reveals."""
    with pytest.raises(ValueError, match="development origins"):
        _prod(BACKEND_CORS_ORIGINS="http://localhost:5173")


def test_production_refuses_wildcard_cors():
    with pytest.raises(ValueError, match="wildcard"):
        _prod(BACKEND_CORS_ORIGINS="*")


def test_production_refuses_debug():
    with pytest.raises(ValueError, match="DEBUG"):
        _prod(DEBUG=True)


def test_a_correctly_configured_production_instance_starts():
    settings = _prod()
    assert settings.BACKEND_CORS_ORIGINS == ["https://traffic.example.gov"]


def test_cors_origins_accept_a_comma_separated_string():
    """Deployment tooling supplies environment variables as plain strings, and a
    list that silently parses wrong fails as a browser error, not a startup one."""
    settings = _prod(BACKEND_CORS_ORIGINS="https://a.gov, https://b.gov")
    assert settings.BACKEND_CORS_ORIGINS == ["https://a.gov", "https://b.gov"]


def test_development_keeps_working_defaults():
    """Hardening production must not make local development need configuration."""
    from app.core.config import Settings

    settings = Settings(ENVIRONMENT="development")
    assert any("localhost" in origin for origin in settings.BACKEND_CORS_ORIGINS)


# ===========================================================================
# Initial administrator provisioning
# ===========================================================================

def test_production_refuses_an_admin_with_no_password_supplied():
    """This account can command signal controllers."""
    from app.bootstrap_admin import bootstrap_admin

    with _environment(ENVIRONMENT="production"):
        created, message = bootstrap_admin(username="p4_nopass", email="p4_nopass@trafficintel.gov", password="")

    assert created is False
    assert "INITIAL_ADMIN_PASSWORD is not set" in message


def test_production_refuses_the_published_development_password():
    """It appears in this repository's documentation, so it is not a secret."""
    from app.bootstrap_admin import PUBLISHED_DEV_PASSWORD, bootstrap_admin

    with _environment(ENVIRONMENT="production"):
        created, message = bootstrap_admin(
            username="p4_published", email="p4_published@trafficintel.gov", password=PUBLISHED_DEV_PASSWORD
        )

    assert created is False
    assert "not a secret" in message


def test_production_refuses_a_short_password():
    from app.bootstrap_admin import bootstrap_admin

    with _environment(ENVIRONMENT="production"):
        created, message = bootstrap_admin(username="p4_short", email="p4_short@trafficintel.gov", password="short1!")

    assert created is False
    assert "at least" in message


def test_a_supplied_production_password_creates_the_account():
    from app.bootstrap_admin import bootstrap_admin

    with _environment(ENVIRONMENT="production"):
        created, message = bootstrap_admin(
            username="p4_real_admin", email="p4_real_admin@trafficintel.gov", password="a-properly-chosen-operator-password"
        )

    assert created is True, message

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.username == "p4_real_admin").first()
        assert user is not None and user.role == "ADMIN"
        # Never recoverable from the system.
        assert "a-properly-chosen-operator-password" not in (user.hashed_password or "")
    finally:
        db.close()


def test_rerunning_never_overwrites_an_existing_account():
    """Rotating a password is a deliberate act, not a side effect of setup."""
    from app.bootstrap_admin import bootstrap_admin

    with _environment(ENVIRONMENT="production"):
        bootstrap_admin(
            username="p4_twice", email="p4_twice@trafficintel.gov",
            password="first-chosen-password-x",
        )
        created, message = bootstrap_admin(
            username="p4_twice", email="p4_twice@trafficintel.gov",
            password="second-different-password-y",
        )

    assert created is False
    assert "already exists" in message


def test_development_still_needs_no_configuration():
    """Making local setup need config is how people disable the checks that matter."""
    from app.bootstrap_admin import bootstrap_admin

    created, message = bootstrap_admin(username="p4_dev_admin", email="p4_dev_admin@trafficintel.gov", password="")
    assert created is True, message
