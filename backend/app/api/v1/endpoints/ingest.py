"""TRAFFICINTEL AI - Data Import Endpoints

Imports operator-supplied files. There is no sample-data generator: every row
that reaches the database came out of a file a human supplied, tagged with its
filename, content hash and import id.

Every import validates first. `commit=false` (the default) returns the full
validation report and writes nothing, so an operator sees exactly which rows
would be rejected before anything lands.
"""

from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Principal, require_scope
from app.governance import scopes as scope_vocab
from app.ingest.importers import IMPORTERS
from app.models.entities import AuditLog

router = APIRouter(prefix="/ingest", tags=["Data Import"])

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


@router.get("/formats")
def list_formats(
    principal: Principal = Depends(require_scope(scope_vocab.READ_TELEMETRY)),
):
    """Supported import formats and what each requires."""
    return {
        "formats": [
            {"format": key, **{k: v for k, v in spec.items() if k != "function"}}
            for key, spec in sorted(IMPORTERS.items())
        ],
        "contract": [
            "Validation runs over every row before anything is written.",
            "commit=false returns the report and writes nothing.",
            "Rejected rows are listed individually with their row number and reason.",
            "Every imported record carries the source filename, content hash and import id.",
            "Physical bounds are enforced at import, so an impossible value never "
            "enters the database.",
        ],
        "max_upload_bytes": MAX_UPLOAD_BYTES,
    }


@router.post("/{import_format}")
async def import_file(
    import_format: str,
    file: UploadFile = File(...),
    commit: bool = Query(
        default=False,
        description="False validates and reports without writing. True imports valid rows.",
    ),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.IMPORT_DATA)),
) -> Dict[str, Any]:
    """Validates, and optionally imports, an operator-supplied file."""
    spec = IMPORTERS.get(import_format)
    if spec is None:
        raise HTTPException(
            status_code=404,
            detail="Unknown import format '{}'. Available: {}".format(
                import_format, sorted(IMPORTERS)
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail="File is {} bytes; the limit is {}.".format(len(content), MAX_UPLOAD_BYTES),
        )

    report = spec["function"](db, content, file.filename or "unnamed", commit)
    payload = report.as_dict()

    db.add(AuditLog(
        actor_id=principal.user.id if principal.user else None,
        actor_username=principal.identity,
        action="DATA_IMPORT" if commit else "DATA_IMPORT_VALIDATE",
        resource_type="Import",
        resource_id=report.import_id,
        result="EXECUTED" if report.committed else "VALIDATED",
        details={
            "format": import_format,
            "filename": report.source_filename,
            "content_sha256": report.content_sha256,
            "rows_read": report.rows_read,
            "rows_valid": report.rows_valid,
            "rows_rejected": report.rows_rejected,
            "rows_written": report.rows_written,
        },
    ))
    db.commit()

    return payload
