"""TRAFFICINTEL AI - Initial Administrator Provisioning

Creates the first operator account so a fresh deployment can be logged into.

Run explicitly, never automatically on startup:

    python -m app.bootstrap_admin

Why the password comes from the environment
-------------------------------------------
This platform commands traffic signals. An administrator password committed to
the repository is known to everyone who can read it, which is the same defect
as the published placeholder SECRET_KEY the application already refuses to boot
on in production - and a worse one, because it grants `signal:command` rather
than merely forging tokens.

So in production the password must be supplied and must not be the published
development default. In development the convenient default is kept, because
making local setup need configuration is how people end up disabling the checks
that matter.

This is also deliberately not wired into container startup. Creating an
administrator is a decision an operator makes once, with a password they chose;
doing it as a side effect of a container booting means nobody ever chose.
"""

from __future__ import annotations

import logging
import os
import sys

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import get_password_hash
from app.models.entities import User

logger = logging.getLogger("trafficintel.bootstrap")

#: The password this project has shipped in its own documentation. Published,
#: therefore not a secret, therefore refused in production.
PUBLISHED_DEV_PASSWORD = "TrafficIntel2026!"

#: Short enough to type, long enough not to be guessed in a drive-by attempt.
MIN_PRODUCTION_PASSWORD_LENGTH = 12


def bootstrap_admin(
    username: str | None = None,
    password: str | None = None,
    email: str | None = None,
) -> tuple[bool, str]:
    """Creates the initial administrator.

    Returns (created, message). Never overwrites an existing account: rotating
    a forgotten password is a deliberate act, not something a re-run of a setup
    script should do silently to a live system.
    """
    username = username or os.environ.get("INITIAL_ADMIN_USERNAME", "admin")
    email = email or os.environ.get("INITIAL_ADMIN_EMAIL", "admin@trafficintel.gov")
    password = password or os.environ.get("INITIAL_ADMIN_PASSWORD", "")

    is_production = settings.ENVIRONMENT.lower() == "production"

    if not password:
        if is_production:
            return False, (
                "INITIAL_ADMIN_PASSWORD is not set and ENVIRONMENT=production. "
                "Refusing to create an administrator with a default password: "
                "this account can command signal controllers, and a password "
                "published in this repository is known to everyone who can read "
                "it. Set INITIAL_ADMIN_PASSWORD and run this again."
            )
        password = PUBLISHED_DEV_PASSWORD
        logger.warning(
            "Using the published development password for '%s'. This is fine "
            "locally and unacceptable anywhere reachable by anyone else.",
            username,
        )

    if is_production:
        if password == PUBLISHED_DEV_PASSWORD:
            return False, (
                "INITIAL_ADMIN_PASSWORD is the published development password "
                "while ENVIRONMENT=production. It appears in this repository's "
                "documentation, so it is not a secret."
            )
        if len(password) < MIN_PRODUCTION_PASSWORD_LENGTH:
            return False, (
                "INITIAL_ADMIN_PASSWORD is {} characters; at least {} are required "
                "in production for an account that can command signal controllers."
                .format(len(password), MIN_PRODUCTION_PASSWORD_LENGTH)
            )

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == username).first()
        if existing:
            return False, (
                "User '{}' already exists; nothing was changed. Rotating a "
                "password is a deliberate act, not a side effect of re-running "
                "setup.".format(username)
            )

        # Checked explicitly: the column is unique, and letting the database
        # raise would hand an operator a SQLAlchemy stack trace instead of the
        # one-line reason they can act on.
        if db.query(User).filter(User.email == email).first():
            return False, (
                "A user with email '{}' already exists. Pass a different address "
                "via INITIAL_ADMIN_EMAIL.".format(email)
            )

        db.add(User(
            username=username,
            email=email,
            hashed_password=get_password_hash(password),
            full_name="Initial System Administrator",
            role="ADMIN",
            is_active=True,
        ))
        db.commit()
        return True, (
            "Administrator '{}' created. The password is the one you supplied; "
            "it is not stored anywhere in plaintext and cannot be recovered "
            "from this system.".format(username)
        )
    finally:
        db.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    created, message = bootstrap_admin()
    if created:
        logger.info("%s", message)
        return 0
    logger.error("%s", message)
    return 1


if __name__ == "__main__":
    sys.exit(main())
