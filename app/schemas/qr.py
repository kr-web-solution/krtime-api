"""QR token schemas."""

from __future__ import annotations

from pydantic import BaseModel


class QrTokenOut(BaseModel):
    site_slug: str
    location_id: str
    token: str
    window: int
    window_seconds: int
    expires_in: int
    server_time: str


class QrDisplayLinkOut(BaseModel):
    site_slug: str
    exp: int
    sig: str
    path: str
    display_url: str
