"""Rotating site QR tokens and signed tablet display links."""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models import Location


def _window_index(now: float | None = None, window_seconds: int = 30) -> int:
    ts = int(now if now is not None else time.time())
    return ts // window_seconds


def compute_qr_token(*, qr_secret: str, location_id: UUID, window: int) -> str:
    message = f"{location_id}:{window}".encode("utf-8")
    digest = hmac.new(qr_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return digest[:16]


def current_qr_payload(location: Location, settings: Settings) -> dict:
    window = _window_index(window_seconds=settings.qr_window_seconds)
    token = compute_qr_token(
        qr_secret=location.qr_secret,
        location_id=location.id,
        window=window,
    )
    expires_in = settings.qr_window_seconds - (int(time.time()) % settings.qr_window_seconds)
    return {
        "site_slug": location.slug,
        "location_id": str(location.id),
        "token": token,
        "window": window,
        "window_seconds": settings.qr_window_seconds,
        "expires_in": expires_in,
        "server_time": datetime.now(UTC).isoformat(),
    }


def verify_qr_token(
    location: Location,
    token: str,
    settings: Settings,
    *,
    now: float | None = None,
) -> bool:
    """Accept current or previous 30s window."""
    window = _window_index(now=now, window_seconds=settings.qr_window_seconds)
    for candidate in (window, window - 1):
        expected = compute_qr_token(
            qr_secret=location.qr_secret,
            location_id=location.id,
            window=candidate,
        )
        if hmac.compare_digest(expected, token):
            return True
    return False


def sign_qr_display_link(
    *,
    site_slug: str,
    settings: Settings,
    ttl_hours: int = 24 * 30,
) -> dict:
    exp = int((datetime.now(UTC) + timedelta(hours=ttl_hours)).timestamp())
    message = f"{site_slug}|{exp}".encode("utf-8")
    sig = hmac.new(settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    query = urlencode({"exp": exp, "sig": sig})
    path = f"/qr/{site_slug}/?{query}"
    display_url = f"{settings.admin_public_url.rstrip('/')}{path}"
    return {
        "site_slug": site_slug,
        "exp": exp,
        "sig": sig,
        "path": path,
        "display_url": display_url,
    }


def verify_qr_display_signature(
    *,
    site_slug: str,
    exp: int,
    sig: str,
    settings: Settings,
) -> None:
    if exp < int(time.time()):
        raise AppError("qr_link_expired", "QR display link has expired", status_code=401)
    message = f"{site_slug}|{exp}".encode("utf-8")
    expected = hmac.new(settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        raise AppError("qr_link_invalid", "QR display link signature is invalid", status_code=401)


def get_active_location_by_slug(db: Session, site_slug: str) -> Location:
    location = db.scalar(select(Location).where(Location.slug == site_slug))
    if location is None:
        raise AppError("location_not_found", "Location not found", status_code=404)
    if not location.active:
        raise AppError("location_inactive", "Location is inactive", status_code=400)
    return location
