"""Public (signed) QR token endpoint for entrance tablets."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, SuperAdminUser
from app.core.config import Settings, get_settings
from app.schemas.qr import QrDisplayLinkOut, QrTokenOut
from app.services import qr_service

router = APIRouter()


@router.get("/{site_slug}/token", response_model=QrTokenOut)
def get_site_qr_token(
    site_slug: str,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    exp: Annotated[int, Query(description="Unix expiry from signed admin link")],
    sig: Annotated[str, Query(min_length=32, max_length=128)],
) -> QrTokenOut:
    qr_service.verify_qr_display_signature(
        site_slug=site_slug, exp=exp, sig=sig, settings=settings
    )
    location = qr_service.get_active_location_by_slug(db, site_slug)
    return QrTokenOut(**qr_service.current_qr_payload(location, settings))


@router.post("/{site_slug}/display-link", response_model=QrDisplayLinkOut)
def create_display_link(
    site_slug: str,
    db: DbSession,
    _: SuperAdminUser,
    settings: Annotated[Settings, Depends(get_settings)],
    ttl_hours: Annotated[int, Query(ge=1, le=24 * 365)] = 24 * 90,
) -> QrDisplayLinkOut:
    qr_service.get_active_location_by_slug(db, site_slug)
    return QrDisplayLinkOut(
        **qr_service.sign_qr_display_link(
            site_slug=site_slug, settings=settings, ttl_hours=ttl_hours
        )
    )
