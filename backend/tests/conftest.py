"""TRAFFICINTEL AI - Test Session Configuration

Isolates the automated suite from the operational database.

The suite must never read or write the operator's real telemetry store: a test
that mutates `trafficintel.db` can leave fabricated-looking rows behind in a
production console. We therefore point DATABASE_URL at a throwaway store BEFORE
any application module is imported (app.core.database builds its engine at
import time, so this ordering is load-bearing).

Dual-dialect runs
-----------------
By default the suite runs on a throwaway SQLite file, which needs nothing
installed. Set TRAFFICINTEL_TEST_DATABASE_URL to run the identical suite
against PostgreSQL:

    TRAFFICINTEL_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db \\
        python -m pytest

This exists because "dual-dialect" was an untested claim until it was run: the
migrations applied cleanly on SQLite for months while PostgreSQL rejected a
boolean column default outright. A portability claim nobody executes is a
guess, so CI runs both.

The target database is DROPPED AND REBUILT from migrations on every session,
so it must be a scratch database, never one holding real telemetry.
"""

import os
import pathlib
import tempfile

_OVERRIDE = os.environ.get("TRAFFICINTEL_TEST_DATABASE_URL", "").strip()

_TEST_DB_PATH = pathlib.Path(tempfile.gettempdir()) / "trafficintel_pytest.db"

# Must be set before `app.*` is imported anywhere in the suite.
os.environ["DATABASE_URL"] = (
    _OVERRIDE if _OVERRIDE else f"sqlite:///{_TEST_DB_PATH.as_posix()}"
)
os.environ["ENVIRONMENT"] = "development"
os.environ.setdefault("SECRET_KEY", "pytest-only-key-not-used-outside-the-test-suite")

import pytest  # noqa: E402  (import intentionally follows env setup)

USING_SQLITE = not _OVERRIDE


def _remove_test_db() -> None:
    if not USING_SQLITE:
        return
    try:
        _TEST_DB_PATH.unlink(missing_ok=True)
    except PermissionError:
        # Windows keeps a handle open until the engine is disposed; a stale file
        # is dropped by the next session instead of failing the current one.
        pass


def _reset_external_database() -> None:
    """Drops every object in the target schema before rebuilding it.

    For a file-backed SQLite run, deleting the file is enough. A server-backed
    database has to be emptied explicitly, and it is emptied rather than merely
    migrated so that a leftover table from an abandoned run cannot make a
    broken migration look like it applied.
    """
    from sqlalchemy import text
    from app.core.database import engine

    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture(scope="session", autouse=True)
def isolated_database():
    """Creates a clean schema in the throwaway database for the whole session."""
    _remove_test_db()

    from app.core.database import engine
    from app.core.migrations import upgrade_to_head
    import app.models.entities  # noqa: F401  (registers mappers on Base)

    if not USING_SQLITE:
        _reset_external_database()

    # Build the test schema through the real migrations rather than
    # create_all, so every run exercises the migration path an operator uses.
    upgrade_to_head()
    yield
    engine.dispose()
    _remove_test_db()


@pytest.fixture(scope="module", autouse=True)
def fresh_rate_limit_buckets():
    """Gives each test module its own rate-limit buckets.

    The limiter is per-process and every TestClient request comes from the same
    address, so without this the modules share one login budget (10 per five
    minutes) and whether a module can log in depends on how many ran before it.
    That was observed: adding one module's logins pushed a later module into
    429s. Reset per module, not per test, so a module that exercises the
    limiter still sees its own requests accumulate.
    """
    from app.governance.rate_limit import rate_limiter

    rate_limiter.reset()
    yield


@pytest.fixture
def db_session():
    """Per-test session against the isolated database."""
    from app.core.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
