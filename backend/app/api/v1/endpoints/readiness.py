"""TRAFFICINTEL AI - Liveness & Readiness Probes

Two endpoints an orchestrator can poll, kept deliberately distinct because
conflating them is how a broken deployment gets sent live traffic.

    /health/live   Is this process running and able to answer?
    /health/ready  Is it safe to route operators to this instance?

Neither requires authentication: a probe runs before anyone has a token, and a
readiness endpoint that returns 401 to its own orchestrator is indistinguishable
from one that is down. They therefore expose only what an operator would
already see on the login screen - never counts, never telemetry, never the
names of junctions - so an unauthenticated scrape learns nothing about the
network being controlled.

The rule that shapes readiness: it reports NOT READY when the instance cannot
serve correctly, even if the process is perfectly healthy. A pod that answers
requests against a drifted schema is worse than one that is plainly down,
because the failure surfaces as wrong data mid-shift rather than a failed
deploy.
"""

from typing import Any, Dict

from fastapi import APIRouter, Response, status
from sqlalchemy import text

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.migrations import check_schema_is_current

router = APIRouter(prefix="/health", tags=["Liveness & Readiness"])


@router.get("/live")
def liveness() -> Dict[str, Any]:
    """Liveness: the process is up and the event loop is turning.

    Deliberately touches nothing external. A liveness probe that checks the
    database will restart a healthy application every time the database
    hiccups, turning a brief dependency blip into a restart storm that takes
    the console down for the whole shift.
    """
    return {
        "status": "ALIVE",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "detail": (
            "The process is running. This says nothing about whether its "
            "dependencies are reachable - see /health/ready for that."
        ),
    }


@router.get("/ready")
def readiness(response: Response) -> Dict[str, Any]:
    """Readiness: this instance can serve correctly right now.

    Returns 503 with the reason when it cannot, so an orchestrator removes the
    instance from rotation rather than sending operators to it.
    """
    checks = []

    # --- database reachable ------------------------------------------------
    db_ok = False
    db_detail = ""
    db = None
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db_ok = True
        db_detail = "Connection established and a trivial query succeeded."
    except Exception as exc:  # noqa: BLE001 - surfaced, never swallowed
        db_detail = "Database is unreachable: {}".format(exc)
    finally:
        if db is not None:
            db.close()

    checks.append({
        "name": "database_reachable",
        "passed": db_ok,
        "detail": db_detail,
        "why_it_blocks": (
            "Every screen in the console reads from the database. Without it "
            "the platform cannot distinguish 'no incidents' from 'cannot see'."
        ),
    })

    # --- schema at head ----------------------------------------------------
    # Only meaningful if the database answered at all; reporting 'schema
    # drifted' when the real problem is a dead database sends an operator to
    # fix the wrong thing.
    if db_ok:
        schema_ok, schema_message = check_schema_is_current()
        checks.append({
            "name": "schema_at_head",
            "passed": schema_ok,
            "detail": schema_message,
            "why_it_blocks": (
                "An instance serving against a drifted schema fails inside "
                "requests, mid-shift, as wrong or missing data - which is worse "
                "than a deploy that plainly refuses to come up."
            ),
        })
    else:
        checks.append({
            "name": "schema_at_head",
            "passed": False,
            "detail": "Not checked: the database did not answer.",
            "why_it_blocks": "Cannot be determined while the database is unreachable.",
        })

    ready = all(check["passed"] for check in checks)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "READY" if ready else "NOT_READY",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "checks": checks,
        "failed_checks": [c["name"] for c in checks if not c["passed"]],
        "detail": (
            "This instance can serve operator traffic."
            if ready else
            "This instance is not fit to serve operator traffic and should be "
            "removed from rotation. Failing: {}.".format(
                ", ".join(c["name"] for c in checks if not c["passed"])
            )
        ),
        "scope_note": (
            "Readiness covers this instance's own ability to serve. It is not a "
            "statement about field equipment: a controller being unreachable is "
            "reported per device, not by taking the console out of rotation."
        ),
    }
