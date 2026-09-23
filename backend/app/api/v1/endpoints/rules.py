"""TRAFFICINTEL AI - Alert Rules API

Operator-defined rules over real stored state, with an explicit dry-run so a
rule can be checked before it is allowed to page anyone.
"""

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user, require_roles
from app.models.entities import (
    Alert, AlertDelivery, AlertRule, AuditLog, RuleEvaluation, User, utc_now,
)
from app.rules.engine import CONDITION_TYPES, RulesEngine
from app.schemas.domain import AlertRuleCreate, AlertRuleResponse, AlertRuleUpdate

router = APIRouter(prefix="/rules", tags=["Alert Rules"])


@router.get("/condition-types")
def list_condition_types(current_user: User = Depends(get_current_user)):
    """The conditions a rule may use, and the parameters each requires."""
    return {
        "condition_types": [
            {"type": key, **value} for key, value in CONDITION_TYPES.items()
        ],
        "note": (
            "Every condition distinguishes 'not matched' from 'insufficient data'. "
            "A subject that has never reported is reported as INSUFFICIENT_DATA, "
            "not as a passing check."
        ),
    }


@router.get("", response_model=List[AlertRuleResponse])
def list_rules(
    enabled_only: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AlertRule)
    if enabled_only:
        query = query.filter(AlertRule.enabled == True)  # noqa: E712
    return query.order_by(AlertRule.created_at.desc()).all()


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    data: AlertRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"])),
):
    if data.condition_type not in CONDITION_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Unknown condition type '{}'. Valid types: {}".format(
                data.condition_type, sorted(CONDITION_TYPES)
            ),
        )
    if db.query(AlertRule).filter(AlertRule.name == data.name).first():
        raise HTTPException(status_code=400, detail="A rule named '{}' already exists.".format(data.name))

    rule = AlertRule(
        name=data.name,
        description=data.description,
        condition_type=data.condition_type,
        parameters=data.parameters,
        intersection_id=data.intersection_id,
        severity=data.severity,
        enabled=data.enabled,
        cooldown_sec=data.cooldown_sec,
        escalate_after_sec=data.escalate_after_sec,
        escalate_to_severity=data.escalate_to_severity,
        delivery_channels=data.delivery_channels,
        webhook_url=data.webhook_url,
        email_to=data.email_to,
        created_by=current_user.username,
    )
    db.add(rule)
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="CREATE_ALERT_RULE",
        resource_type="AlertRule",
        resource_id=rule.id,
        result="EXECUTED",
        details={"name": data.name, "condition_type": data.condition_type},
    ))
    db.commit()
    db.refresh(rule)
    return rule


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
def update_rule(
    rule_id: str,
    data: AlertRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"])),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(rule, field, value)

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="UPDATE_ALERT_RULE",
        resource_type="AlertRule",
        resource_id=rule.id,
        result="EXECUTED",
        details={"changed_fields": sorted(changes)},
    ))
    db.commit()
    db.refresh(rule)
    return rule


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"])),
):
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Evaluations reference the rule; drop them with it so the audit of *why*
    # a rule existed stays in the audit ledger rather than dangling here.
    db.query(RuleEvaluation).filter(RuleEvaluation.rule_id == rule_id).delete()
    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="DELETE_ALERT_RULE",
        resource_type="AlertRule",
        resource_id=rule_id,
        result="EXECUTED",
        details={"name": rule.name},
    ))
    db.delete(rule)
    db.commit()
    return None


@router.post("/{rule_id}/evaluate")
def evaluate_rule(
    rule_id: str,
    dry_run: bool = Query(default=True, description="Dry runs raise no alerts and write nothing."),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"])),
):
    """Evaluates one rule against current stored state."""
    rule = db.query(AlertRule).filter(AlertRule.id == rule_id).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return RulesEngine.evaluate_rule(db, rule, dry_run=dry_run)


@router.post("/evaluate-all")
def evaluate_all_rules(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER"])),
):
    """Evaluates every enabled rule and applies escalations."""
    return RulesEngine.evaluate_all(db)


@router.get("/{rule_id}/evaluations")
def list_evaluations(
    rule_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Why this rule fired, or did not, on each recent evaluation."""
    rows = (
        db.query(RuleEvaluation)
        .filter(RuleEvaluation.rule_id == rule_id)
        .order_by(RuleEvaluation.evaluated_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "rule_id": rule_id,
        "count": len(rows),
        "empty_reason": None if rows else "RULE_HAS_NOT_BEEN_EVALUATED_YET",
        "evaluations": [
            {
                "id": row.id,
                "subject_type": row.subject_type,
                "subject_id": row.subject_id,
                "outcome": row.outcome,
                "observed": row.observed,
                "explanation": row.explanation,
                "alert_id": row.alert_id,
                "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at else None,
            }
            for row in rows
        ],
    }


@router.get("/alerts/{alert_id}/deliveries")
def list_alert_deliveries(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Every delivery attempt for one alert, including the ones that were skipped."""
    rows = (
        db.query(AlertDelivery)
        .filter(AlertDelivery.alert_id == alert_id)
        .order_by(AlertDelivery.attempted_at.asc())
        .all()
    )
    return {
        "alert_id": alert_id,
        "deliveries": [
            {
                "channel": row.channel,
                "target": row.target,
                "status": row.status,
                "detail": row.detail,
                "attempted_at": row.attempted_at.isoformat() if row.attempted_at else None,
            }
            for row in rows
        ],
        "empty_reason": None if rows else "NO_DELIVERY_ATTEMPTED",
        "note": (
            "SKIPPED_NOT_CONFIGURED means the channel was listed on the rule but "
            "has no destination configured, so nobody was notified on it."
        ),
    }


@router.post("/alerts/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(["ADMIN", "ENGINEER", "OPERATOR"])),
):
    alert = db.query(Alert).filter(Alert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")

    alert.is_acknowledged = True
    alert.acknowledged_by = current_user.username
    alert.acknowledged_at = utc_now()

    db.add(AuditLog(
        actor_id=current_user.id,
        actor_username=current_user.username,
        action="ACKNOWLEDGE_ALERT",
        resource_type="Alert",
        resource_id=alert.id,
        result="EXECUTED",
        details={"severity": alert.severity, "title": alert.title},
    ))
    db.commit()

    from app.events import topics
    from app.events.bus import event_bus
    event_bus.publish(topics.ALERT_ACKNOWLEDGED, {
        "alert_id": alert.id,
        "acknowledged_by": current_user.username,
        "severity": alert.severity,
    })

    return {
        "alert_id": alert.id,
        "is_acknowledged": True,
        "acknowledged_by": alert.acknowledged_by,
        "acknowledged_at": alert.acknowledged_at.isoformat(),
    }
