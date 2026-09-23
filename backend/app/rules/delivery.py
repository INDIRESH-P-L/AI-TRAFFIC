"""TRAFFICINTEL AI - Alert Delivery

Delivers an alert to the channels its rule declares, and records the outcome of
every attempt.

Two honesty rules:

1. **A channel that is not configured is SKIPPED_NOT_CONFIGURED, not
   DELIVERED.** A rule listing EMAIL with no SMTP host configured has not
   notified anybody, and the delivery record says so rather than showing a
   green tick nobody earned.

2. **Delivery failures never swallow the alert.** The alert row exists before
   any delivery is attempted, so a dead webhook loses a notification, not the
   record that something happened.
"""

from __future__ import annotations

import json
import logging
import smtplib
from email.message import EmailMessage
from typing import Any, Dict, List

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import Alert, AlertDelivery, AlertRule

logger = logging.getLogger("trafficintel.rules.delivery")

DELIVERED = "DELIVERED"
FAILED = "FAILED"
SKIPPED_NOT_CONFIGURED = "SKIPPED_NOT_CONFIGURED"

WEBHOOK_TIMEOUT_SEC = 5.0


def _payload(alert: Alert, rule: AlertRule) -> Dict[str, Any]:
    """The alert as sent to an external system, provenance included."""
    return {
        "alert_id": alert.id,
        "rule": {"id": rule.id, "name": rule.name, "condition_type": rule.condition_type},
        "severity": alert.severity,
        "title": alert.title,
        "message": alert.message,
        "resource": {"type": alert.resource_type, "id": alert.resource_id},
        "observed": alert.observed,
        "occurrence_count": alert.occurrence_count,
        "raised_at": alert.timestamp.isoformat() if alert.timestamp else None,
        "source": "TRAFFICINTEL AI",
    }


def _record(
    db: Session, alert_id: str, channel: str, target: str, status: str, detail: str
) -> None:
    db.add(AlertDelivery(
        alert_id=alert_id, channel=channel, target=target, status=status, detail=detail,
    ))


def deliver_alert(db: Session, rule: AlertRule, alert: Alert) -> List[Dict[str, str]]:
    """Attempts delivery on each declared channel. Never raises."""
    channels = rule.delivery_channels or ["UI"]
    outcomes: List[Dict[str, str]] = []

    for channel in channels:
        channel = str(channel).upper()

        if channel == "UI":
            # The alert row itself is the UI delivery: the console reads alerts
            # from the database and receives an alert.raised event.
            _record(db, alert.id, "UI", "operations console", DELIVERED,
                    "Alert row written and alert.raised published.")
            outcomes.append({"channel": "UI", "status": DELIVERED})

        elif channel == "WEBHOOK":
            outcomes.append(_deliver_webhook(db, rule, alert))

        elif channel == "EMAIL":
            outcomes.append(_deliver_email(db, rule, alert))

        else:
            _record(db, alert.id, channel, "", SKIPPED_NOT_CONFIGURED,
                    "Unknown delivery channel '{}'.".format(channel))
            outcomes.append({"channel": channel, "status": SKIPPED_NOT_CONFIGURED})

    db.flush()
    return outcomes


def _deliver_webhook(db: Session, rule: AlertRule, alert: Alert) -> Dict[str, str]:
    if not rule.webhook_url:
        _record(db, alert.id, "WEBHOOK", "", SKIPPED_NOT_CONFIGURED,
                "Rule lists WEBHOOK but no webhook_url is set. Nobody was notified.")
        return {"channel": "WEBHOOK", "status": SKIPPED_NOT_CONFIGURED}

    try:
        with httpx.Client(timeout=WEBHOOK_TIMEOUT_SEC) as client:
            response = client.post(
                rule.webhook_url,
                json=_payload(alert, rule),
                headers={"Content-Type": "application/json"},
            )
        if 200 <= response.status_code < 300:
            _record(db, alert.id, "WEBHOOK", rule.webhook_url, DELIVERED,
                    "HTTP {}".format(response.status_code))
            return {"channel": "WEBHOOK", "status": DELIVERED}

        _record(db, alert.id, "WEBHOOK", rule.webhook_url, FAILED,
                "HTTP {}: {}".format(response.status_code, response.text[:400]))
        return {"channel": "WEBHOOK", "status": FAILED}

    except Exception as exc:  # noqa: BLE001 - recorded verbatim, never raised
        logger.warning("Webhook delivery failed for alert %s: %s", alert.id, exc)
        _record(db, alert.id, "WEBHOOK", rule.webhook_url, FAILED, str(exc))
        return {"channel": "WEBHOOK", "status": FAILED}


def _deliver_email(db: Session, rule: AlertRule, alert: Alert) -> Dict[str, str]:
    recipients = (rule.email_to or "").strip()
    if not recipients:
        _record(db, alert.id, "EMAIL", "", SKIPPED_NOT_CONFIGURED,
                "Rule lists EMAIL but no recipient is set. Nobody was notified.")
        return {"channel": "EMAIL", "status": SKIPPED_NOT_CONFIGURED}

    if not settings.SMTP_HOST:
        _record(db, alert.id, "EMAIL", recipients, SKIPPED_NOT_CONFIGURED,
                "No SMTP host is configured on this deployment. Nobody was notified.")
        return {"channel": "EMAIL", "status": SKIPPED_NOT_CONFIGURED}

    message = EmailMessage()
    message["Subject"] = "[{}] {}".format(alert.severity, alert.title)
    message["From"] = settings.SMTP_FROM or "trafficintel@localhost"
    message["To"] = recipients
    message.set_content(
        "{}\n\nObserved values:\n{}\n\nAlert id: {}\nRule: {}\n".format(
            alert.message,
            json.dumps(alert.observed or {}, indent=2),
            alert.id,
            rule.name,
        )
    )

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
            if settings.SMTP_USE_TLS:
                smtp.starttls()
            if settings.SMTP_USERNAME:
                smtp.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            smtp.send_message(message)

        _record(db, alert.id, "EMAIL", recipients, DELIVERED,
                "Sent via {}:{}".format(settings.SMTP_HOST, settings.SMTP_PORT))
        return {"channel": "EMAIL", "status": DELIVERED}

    except Exception as exc:  # noqa: BLE001
        logger.warning("Email delivery failed for alert %s: %s", alert.id, exc)
        _record(db, alert.id, "EMAIL", recipients, FAILED, str(exc))
        return {"channel": "EMAIL", "status": FAILED}
