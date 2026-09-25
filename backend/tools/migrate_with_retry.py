"""TRAFFICINTEL AI - Migration Entrypoint with Connection Retry

Used as the `migrate` compose service's command. The database is no longer a
compose-managed service with a healthcheck compose can wait on - it is
external (a native install or a managed provider), reachable only over the
network. A transient DNS hiccup or a managed provider's cold-start pause
would otherwise crash-loop this container on the very first attempt.

So this script does exactly two things, in order:

1. Waits for DATABASE_URL to be reachable, retrying a handful of times with a
   short backoff. Not indefinitely: a database that is still unreachable after
   this many attempts is a configuration problem (wrong host, firewall,
   credentials), and a job that retries forever hides that behind an
   ever-growing log instead of a failed deploy.
2. Runs the same `upgrade_to_head()` path db_init.py and the test suite use -
   never a second, divergent way of applying migrations.

No new dependency: retry logic is a plain loop around the SQLAlchemy engine
this project already builds from DATABASE_URL.
"""

from __future__ import annotations

import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("trafficintel.migrate")

MAX_ATTEMPTS = 8
INITIAL_DELAY_SEC = 2.0
MAX_DELAY_SEC = 20.0


def _fail_fast_if_database_url_unset() -> None:
    """Refuses to guess. A missing DATABASE_URL must not silently fall back to
    the SQLite default `app.core.config.Settings` declares for local dev -
    that would "succeed" by migrating a throwaway file inside the container
    and never touch the real database at all."""
    if not os.environ.get("DATABASE_URL", "").strip():
        logger.error(
            "DATABASE_URL is not set. This service does not assume compose will "
            "start a database for it - point DATABASE_URL at a reachable "
            "PostgreSQL instance (see .env.example) before starting this "
            "container."
        )
        sys.exit(1)


def _wait_for_database() -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    # Imported after the DATABASE_URL check above, and after logging config:
    # app.core.database builds its engine from settings at import time.
    from app.core.database import engine

    delay = INITIAL_DELAY_SEC
    last_error: Exception | None = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            logger.info("Database is reachable (attempt %d/%d).", attempt, MAX_ATTEMPTS)
            return
        except OperationalError as exc:
            last_error = exc
            if attempt == MAX_ATTEMPTS:
                break
            logger.warning(
                "Database not reachable yet (attempt %d/%d): %s. Retrying in %.0fs.",
                attempt, MAX_ATTEMPTS, str(exc).splitlines()[0], delay,
            )
            time.sleep(delay)
            delay = min(delay * 2, MAX_DELAY_SEC)

    logger.error(
        "Database at DATABASE_URL was unreachable after %d attempts. Last error: %s",
        MAX_ATTEMPTS, last_error,
    )
    logger.error(
        "This is a configuration problem, not a transient one: check the host, "
        "port, credentials and that the database accepts connections from this "
        "container's network (see README section 9)."
    )
    sys.exit(1)


def _run_migrations() -> None:
    from app.core.migrations import upgrade_to_head

    revision = upgrade_to_head()
    logger.info("Migrations applied. Schema is at revision %s.", revision)


def main() -> None:
    _fail_fast_if_database_url_unset()
    _wait_for_database()
    _run_migrations()


if __name__ == "__main__":
    main()
