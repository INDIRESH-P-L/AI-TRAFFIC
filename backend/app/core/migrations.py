"""TRAFFICINTEL AI - Schema Migration Helpers

Alembic is the single source of truth for the relational schema. These helpers
let the bootstrap script apply migrations and let the API verify at startup
that the database it is about to serve actually matches the models it will use.

A schema drift check matters here beyond ordinary hygiene: a missing column
does not fail loudly at the API boundary, it fails inside a request handler,
and a half-working console is harder for an operator to distrust than one that
refuses to start.
"""

from __future__ import annotations

import logging
import pathlib
from typing import Optional, Tuple

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from app.core.config import settings
from app.core.database import engine

logger = logging.getLogger("trafficintel.migrations")

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_ROOT / "alembic.ini"
ALEMBIC_DIR = BACKEND_ROOT / "alembic"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def current_revision() -> Optional[str]:
    """Revision the database is stamped at, or None if it has never migrated."""
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def head_revision() -> Optional[str]:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def upgrade_to_head() -> str:
    """Applies all pending migrations. Returns the resulting revision."""
    command.upgrade(alembic_config(), "head")
    revision = current_revision()
    logger.info("Database schema migrated to revision %s", revision)
    return revision or "unknown"


def check_schema_is_current() -> Tuple[bool, str]:
    """Compares the stamped revision against the migration head.

    Returns (is_current, human-readable explanation).
    """
    try:
        current = current_revision()
        head = head_revision()
    except Exception as exc:  # noqa: BLE001 - reported, never swallowed
        return False, "Could not read the schema revision: {}".format(exc)

    if current is None:
        return False, (
            "The database carries no Alembic revision. If it was created by an earlier "
            "build, adopt migrations with: python -m alembic stamp 0001_baseline "
            "&& python -m alembic upgrade head"
        )
    if current != head:
        return False, (
            "Database is at revision {} but the code expects {}. "
            "Run: python -m alembic upgrade head".format(current, head)
        )
    return True, "Schema is at revision {}".format(current)
