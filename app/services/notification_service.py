"""Outbound push via self-hosted ntfy (UnifiedPush-compatible topics)."""

from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models import PushSubscription

logger = logging.getLogger("attendguard.notifications")


def push_enabled(settings: Settings | None = None) -> bool:
    s = settings or get_settings()
    return bool(s.ntfy_base_url.strip())


def public_ntfy_url(settings: Settings | None = None) -> str:
    s = settings or get_settings()
    return (s.ntfy_public_url or s.ntfy_base_url or "").rstrip("/")


def _headers(settings: Settings) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "text/plain; charset=utf-8"}
    token = (settings.ntfy_token or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def publish(
    *,
    topic_or_url: str,
    title: str,
    message: str,
    priority: int = 3,
    tags: str | None = None,
    settings: Settings | None = None,
) -> bool:
    """POST a notification. topic_or_url may be a topic name or a full endpoint URL."""
    s = settings or get_settings()
    if not push_enabled(s):
        return False

    target = topic_or_url.strip()
    if not target:
        return False

    if target.startswith("http://") or target.startswith("https://"):
        url = target
    else:
        url = f"{s.ntfy_base_url.rstrip('/')}/{target.lstrip('/')}"

    headers = _headers(s)
    headers["Title"] = title[:200]
    headers["Priority"] = str(max(1, min(5, priority)))
    # Plain text body: ntfy shows Title header; KRTime parses JSON if present,
    # otherwise treats body as the notification text (works when app is closed).
    headers["Content-Type"] = "text/plain; charset=utf-8"
    if tags:
        headers["Tags"] = tags

    # Embed title+message as JSON so KRTime can show a normal system notification.
    payload = json.dumps(
        {"title": title[:200], "message": message[:2000]},
        ensure_ascii=False,
    ).encode("utf-8")

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(url, content=payload, headers=headers)
            response.raise_for_status()
        return True
    except Exception:
        logger.exception("ntfy publish failed target=%s", url)
        return False


def notify_admin(
    *,
    title: str,
    message: str,
    priority: int = 4,
    tags: str | None = "warning",
    settings: Settings | None = None,
) -> bool:
    s = settings or get_settings()
    topic = (s.ntfy_admin_topic or "").strip()
    if not topic:
        return False
    return publish(
        topic_or_url=topic,
        title=title,
        message=message,
        priority=priority,
        tags=tags,
        settings=s,
    )


# Preset admin → employee alerts (used by admin Employees page).
EMPLOYEE_ALERT_PRESETS: dict[str, dict[str, object]] = {
    "check_in": {
        "title": "Check in now",
        "message": "Please check in on KRTime.",
        "priority": 4,
        "tags": "alarm_clock",
    },
    "check_out": {
        "title": "Check out now",
        "message": "Please check out on KRTime.",
        "priority": 4,
        "tags": "door",
    },
    "return_site": {
        "title": "Return to site",
        "message": "Please return to your assigned workplace.",
        "priority": 5,
        "tags": "round_pushpin,warning",
    },
    "call_admin": {
        "title": "Contact admin",
        "message": "Please contact your admin as soon as possible.",
        "priority": 4,
        "tags": "telephone_receiver",
    },
    "urgent": {
        "title": "Urgent alert",
        "message": "Urgent: please open KRTime and respond immediately.",
        "priority": 5,
        "tags": "rotating_light,warning",
    },
}


def send_employee_alert(
    db: Session,
    *,
    employee_id: UUID,
    alert_type: str,
    note: str | None = None,
    title: str | None = None,
    message: str | None = None,
    settings: Settings | None = None,
) -> tuple[str, str, int, bool]:
    """Send a preset or custom alert. Returns (title, message, delivered_count, push_enabled)."""
    if alert_type == "custom":
        final_title = (title or "").strip() or "Message from admin"
        final_message = (message or "").strip()
        if not final_message:
            raise ValueError("message is required for custom notifications")
        if note and note.strip():
            final_message = f"{final_message}\n\nNote: {note.strip()}"
        priority = 3
        tags = "speech_balloon"
    else:
        preset = EMPLOYEE_ALERT_PRESETS.get(alert_type)
        if preset is None:
            raise ValueError(f"unknown alert_type: {alert_type}")
        final_title = str(preset["title"])
        final_message = str(preset["message"])
        if note and note.strip():
            final_message = f"{final_message}\n\nNote: {note.strip()}"
        priority = int(preset["priority"])
        tags = str(preset["tags"]) if preset.get("tags") else None

    s = settings or get_settings()
    enabled = push_enabled(s)
    delivered = notify_employee(
        db,
        employee_id=employee_id,
        title=final_title,
        message=final_message,
        priority=priority,
        tags=tags,
        settings=s,
    )
    return final_title, final_message, delivered, enabled


def notify_employee(
    db: Session,
    *,
    employee_id: UUID,
    title: str,
    message: str,
    priority: int = 3,
    tags: str | None = None,
    settings: Settings | None = None,
) -> int:
    """Send to all push subscriptions for an employee. Returns count attempted OK."""
    s = settings or get_settings()
    if not push_enabled(s):
        return 0
    rows = list(
        db.scalars(
            select(PushSubscription).where(PushSubscription.employee_id == employee_id)
        ).all()
    )
    ok = 0
    for row in rows:
        target = (row.endpoint_url or "").strip() or row.topic
        if publish(
            topic_or_url=target,
            title=title,
            message=message,
            priority=priority,
            tags=tags,
            settings=s,
        ):
            ok += 1
    return ok


def upsert_subscription(
    db: Session,
    *,
    employee_id: UUID,
    topic: str,
    endpoint_url: str | None = None,
    device_id: UUID | None = None,
) -> PushSubscription:
    cleaned = topic.strip()
    if not cleaned or len(cleaned) > 128:
        raise ValueError("invalid topic")
    existing = db.scalar(
        select(PushSubscription).where(
            PushSubscription.employee_id == employee_id,
            PushSubscription.topic == cleaned,
        )
    )
    if existing is None:
        existing = PushSubscription(
            employee_id=employee_id,
            topic=cleaned,
            endpoint_url=endpoint_url,
            device_id=device_id,
        )
        db.add(existing)
    else:
        existing.endpoint_url = endpoint_url or existing.endpoint_url
        if device_id is not None:
            existing.device_id = device_id
        db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing
