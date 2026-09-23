"""TRAFFICINTEL AI - Database Session & Engine

Dual-dialect support (PostgreSQL + PostGIS in production, SQLite local
zero-friction execution). Enforces declarative base, connection timeouts, and
provenance conventions.

Both dialects are exercised by the automated suite; see tests/conftest.py.
Portability here is verified rather than assumed, because it was assumed once
and PostgreSQL rejected a boolean column default that SQLite had accepted for
months.
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from app.core.config import settings

_IS_SQLITE = settings.DATABASE_URL.startswith("sqlite")

connect_args = {}
engine_kwargs = {
    # Verifies a pooled connection before handing it out. Without this, the
    # first request after a database restart, a failover, or an idle firewall
    # timeout fails on a dead socket - and it fails inside an operator's
    # request rather than at the pool.
    "pool_pre_ping": True,
}

if _IS_SQLITE:
    # SQLite connections are bound to the creating thread unless this is off,
    # and the poller runs on its own thread.
    connect_args["check_same_thread"] = False
else:
    engine_kwargs.update({
        # Sized for a control room rather than a public web app: a handful of
        # operators plus the polling thread and background workers. The ceiling
        # matters more than the floor - an unbounded pool turns a slow query
        # into exhausted database connections for every other service on the
        # same server.
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,

        # Waiting forever for a connection turns a saturated pool into a hung
        # console with no error. Failing in 30s surfaces it.
        "pool_timeout": settings.DB_POOL_TIMEOUT_SEC,

        # Recycled below the typical idle timeout of proxies and managed
        # Postgres services, which close connections silently.
        "pool_recycle": settings.DB_POOL_RECYCLE_SEC,
    })

    # A statement that never returns should not hold a connection for the rest
    # of the shift. Applied at connect time so it covers every session.
    connect_args["options"] = "-c statement_timeout={}".format(
        int(settings.DB_STATEMENT_TIMEOUT_SEC * 1000)
    )
    connect_args["connect_timeout"] = int(settings.DB_CONNECT_TIMEOUT_SEC)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    **engine_kwargs,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency for obtaining a database session."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
