"""TRAFFICINTEL AI - Reporting Endpoints

One-click daily operations, incident and signal performance reports, in JSON,
CSV or PDF. All three formats carry the same figures and the same caveats.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Principal, require_scope
from app.governance import scopes as scope_vocab
from app.models.entities import AuditLog
from app.reporting import reports as report_service

router = APIRouter(prefix="/reports", tags=["Reporting"])

FORMATS = ("json", "csv", "pdf")


def _deliver(report: Dict[str, Any], fmt: str, basename: str):
    """Renders a report in the requested format."""
    if fmt == "json":
        return report

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    if fmt == "csv":
        return Response(
            content=report_service.to_csv(report),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="{}-{}.csv"'.format(basename, stamp)
            },
        )

    return Response(
        content=report_service.to_pdf(report),
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="{}-{}.pdf"'.format(basename, stamp)
        },
    )


def _audit(db: Session, principal: Principal, report_type: str, resource_id: str, fmt: str) -> None:
    db.add(AuditLog(
        actor_id=principal.user.id if principal.user else None,
        actor_username=principal.identity,
        action="GENERATE_REPORT",
        resource_type="Report",
        resource_id=resource_id,
        result="EXECUTED",
        details={"report_type": report_type, "format": fmt},
    ))
    db.commit()


@router.get("/catalog")
def report_catalog(
    principal: Principal = Depends(require_scope(scope_vocab.READ_ANALYTICS)),
):
    """Available reports and what each is built from."""
    return {
        "reports": [
            {
                "id": "daily-operations",
                "name": "Daily operations summary",
                "built_from": "Stored incidents, commands, alerts and telemetry counts over 24 hours.",
                "path": "/api/v1/reports/daily-operations",
            },
            {
                "id": "signal-performance",
                "name": "Signal performance report",
                "built_from": "Stored observations and observed signal state (ATSPM measures).",
                "path": "/api/v1/reports/signal-performance/{intersection_id}",
            },
            {
                "id": "incident",
                "name": "Post-incident report",
                "built_from": "The incident's append-only timeline and attached evidence.",
                "path": "/api/v1/reports/incident/{incident_id}",
            },
        ],
        "formats": list(FORMATS),
        "policy": (
            "A measure that could not be computed appears with its reason and sample "
            "size rather than being omitted. An omitted section reads as 'nothing "
            "happened', which is a different claim from 'nothing was measured'."
        ),
    }


@router.get("/daily-operations")
def daily_operations(
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.READ_ANALYTICS)),
):
    report = report_service.daily_operations_summary(db)
    _audit(db, principal, "DAILY_OPERATIONS_SUMMARY", "network", format)
    return _deliver(report, format, "trafficintel-daily-operations")


@router.get("/signal-performance/{intersection_id}")
def signal_performance(
    intersection_id: str,
    hours: int = Query(default=24, ge=1, le=720),
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.READ_ANALYTICS)),
):
    try:
        report = report_service.signal_performance_report(db, intersection_id, hours)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    _audit(db, principal, "SIGNAL_PERFORMANCE_REPORT", intersection_id, format)
    return _deliver(report, format, "trafficintel-signal-performance")


@router.get("/incident/{incident_id}")
def incident(
    incident_id: str,
    format: str = Query(default="json", pattern="^(json|csv|pdf)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.READ_ANALYTICS)),
):
    try:
        report = report_service.incident_report(db, incident_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    _audit(db, principal, "INCIDENT_REPORT", incident_id, format)
    return _deliver(report, format, "trafficintel-incident")
