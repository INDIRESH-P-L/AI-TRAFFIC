"""TRAFFICINTEL AI - Governance API

The audit explorer, chain verification and export, scoped API key management,
and the access model itself served as data so an agency can read its own
permissions rather than infer them.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import Principal, get_current_user, require_scope
from app.governance import api_keys as key_service
from app.governance import ledger, scopes as scope_vocab
from app.models.entities import ApiKey, AuditLog, User, utc_now
from app.schemas.domain import ApiKeyCreate

router = APIRouter(prefix="/governance", tags=["Governance"])


# ===========================================================================
# Access model
# ===========================================================================

@router.get("/scopes")
def list_scopes(current_user: User = Depends(get_current_user)):
    """The whole access model, as data."""
    return {
        "scopes": [
            {"scope": scope, "description": scope_vocab.SCOPE_DESCRIPTIONS.get(scope, "")}
            for scope in sorted(scope_vocab.ALL_SCOPES)
        ],
        "roles": [
            scope_vocab.describe_role(role)
            for role in (
                scope_vocab.VIEWER, scope_vocab.OPERATOR, scope_vocab.ENGINEER,
                scope_vocab.AUDITOR, scope_vocab.ADMIN,
            )
        ],
        "your_role": current_user.role,
        "your_scopes": sorted(scope_vocab.scopes_for_role(current_user.role)),
        "note": (
            "No scope bypasses the Deterministic Safety Engine. The engine is in the "
            "command code path, not an authorisation check a privileged caller can skip."
        ),
    }


@router.get("/whoami")
def whoami(principal: Principal = Depends(require_scope(scope_vocab.READ_TELEMETRY))):
    """Who the platform thinks you are, and what you may do."""
    return {
        "kind": principal.kind,
        "identity": principal.identity,
        "role": principal.role,
        "scopes": sorted(principal.scopes),
        "denied_scopes": sorted(scope_vocab.ALL_SCOPES - principal.scopes),
    }


# ===========================================================================
# Audit explorer
# ===========================================================================

@router.get("/audit")
def explore_audit(
    action: Optional[str] = None,
    actor: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    result: Optional[str] = None,
    hours: Optional[int] = Query(default=None, ge=1, le=8760),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.READ_AUDIT)),
):
    """Filterable view of the immutable action ledger."""
    query = db.query(AuditLog)

    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_username == actor)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if resource_id:
        query = query.filter(AuditLog.resource_id == resource_id)
    if result:
        query = query.filter(AuditLog.result == result)
    if hours:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(tzinfo=None)
        query = query.filter(AuditLog.timestamp >= since)

    total = query.count()
    rows = (
        query.order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    unchained = db.query(AuditLog).filter(AuditLog.sequence.is_(None)).count()

    return {
        "total_matching": total,
        "returned": len(rows),
        "offset": offset,
        "limit": limit,
        "empty_reason": None if rows else "NO_AUDIT_ENTRIES_MATCH_THESE_FILTERS",
        "chain": {
            "unchained_legacy_entries": unchained,
            "note": (
                "{} entries predate the hash chain and carry no sequence. They are "
                "shown, but their integrity is not cryptographically verifiable."
                .format(unchained)
                if unchained else
                "Every entry in the ledger is chained."
            ),
        },
        "entries": [
            {
                "id": row.id,
                "sequence": row.sequence,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "actor_username": row.actor_username,
                "action": row.action,
                "resource_type": row.resource_type,
                "resource_id": row.resource_id,
                "result": row.result,
                "details": row.details,
                "entry_hash": row.entry_hash,
                "previous_hash": row.previous_hash,
                "chained": row.sequence is not None,
            }
            for row in rows
        ],
    }


@router.get("/audit/verify")
def verify_audit_chain(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.READ_AUDIT)),
):
    """Recomputes every hash and reports the first break, if any."""
    return ledger.verify_chain(db)


@router.get("/audit/export")
def export_audit_chain(
    since_sequence: int = Query(default=0, ge=0),
    download: bool = Query(default=False, description="Return as a downloadable file."),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.EXPORT_AUDIT)),
):
    """Chained export for anchoring outside this database."""
    export = ledger.export_entries(db, since_sequence=since_sequence)

    if not download:
        return export

    import json
    payload = json.dumps(export, indent=2, default=str)
    filename = "trafficintel-audit-{}.json".format(
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    )
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="{}"'.format(filename)},
    )


# ===========================================================================
# API keys
# ===========================================================================

@router.get("/api-keys")
def list_api_keys(
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.MANAGE_API_KEYS)),
):
    """Issued keys. The secrets themselves are not stored and cannot be listed."""
    rows = db.query(ApiKey).order_by(ApiKey.created_at.desc()).all()
    now = datetime.now(timezone.utc)

    def status_of(record: ApiKey) -> str:
        if not record.is_active:
            return "REVOKED"
        expires = record.expires_at
        if expires is not None:
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if expires < now:
                return "EXPIRED"
        return "ACTIVE"

    return {
        "count": len(rows),
        "empty_reason": None if rows else "NO_API_KEYS_ISSUED",
        "keys": [
            {
                "id": row.id,
                "name": row.name,
                "key_prefix": row.key_prefix,
                "scopes": row.scopes,
                "status": status_of(row),
                "created_by": row.created_by,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "expires_at": row.expires_at.isoformat() if row.expires_at else None,
                "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
                "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
                "use_count": row.use_count,
            }
            for row in rows
        ],
        "note": (
            "Only a SHA-256 hash of each key is stored. A key's plaintext exists "
            "once, in the creation response, and cannot be recovered."
        ),
    }


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.MANAGE_API_KEYS)),
):
    """Issues a scoped key. The secret is returned exactly once."""
    try:
        created = key_service.create_api_key(
            db=db,
            name=data.name,
            requested_scopes=data.scopes,
            creator_role=principal.role or "ADMIN",
            creator_username=principal.identity,
            expires_in_days=data.expires_in_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    db.add(AuditLog(
        actor_id=principal.user.id if principal.user else None,
        actor_username=principal.identity,
        action="CREATE_API_KEY",
        resource_type="ApiKey",
        resource_id=created["id"],
        result="EXECUTED",
        details={"name": data.name, "scopes": created["scopes"]},
    ))
    db.commit()
    return created


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_200_OK)
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_scope(scope_vocab.MANAGE_API_KEYS)),
):
    if not key_service.revoke_api_key(db, key_id):
        raise HTTPException(status_code=404, detail="API key not found")

    db.add(AuditLog(
        actor_id=principal.user.id if principal.user else None,
        actor_username=principal.identity,
        action="REVOKE_API_KEY",
        resource_type="ApiKey",
        resource_id=key_id,
        result="EXECUTED",
        details={},
    ))
    db.commit()
    return {"key_id": key_id, "status": "REVOKED", "revoked_at": utc_now().isoformat()}
