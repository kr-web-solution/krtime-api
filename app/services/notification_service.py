"""Outbound push via self-hosted ntfy (UnifiedPush-compatible topics)."""

from __future__ import annotations

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
    if tags:
        headers["Tags"] = tags

    try:
        with httpx.Client(timeout=8.0) as client:
            response = client.post(url, content=message.encode("utf-8"), headers=headers)
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
