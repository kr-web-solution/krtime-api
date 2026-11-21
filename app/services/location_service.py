"""Location CRUD."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Location, User
from app.schemas.locations import LocationCreate, LocationOut, LocationUpdate
from app.services.audit import write_audit
from app.services.crypto_keys import generate_qr_secret


def create_location(
    db: Session,
    payload: LocationCreate,
    *,
    actor: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> LocationOut:
    existing = db.scalar(select(Location).where(Location.slug == payload.slug))
    if existing:
        raise AppError("slug_taken", "Location slug already exists", status_code=409)

    location = Location(
        name=payload.name.strip(),
        slug=payload.slug,
        lat=payload.lat,
        lng=payload.lng,
        radius_m=payload.radius_m,
        qr_secret=generate_qr_secret(),
        notes=payload.notes,
        active=payload.active,
    )
    db.add(location)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="location.create",
        entity_type="location",
        entity_id=payload.slug,
        after={"name": location.name, "slug": location.slug, "radius_m": location.radius_m},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(location)
    return LocationOut.model_validate(location)


def list_locations(db: Session, *, active_only: bool = False) -> list[LocationOut]:
    stmt = select(Location)
    if active_only:
        stmt = stmt.where(Location.active.is_(True))
    rows = db.scalars(stmt.order_by(Location.name)).all()
    return [LocationOut.model_validate(row) for row in rows]


def get_location(db: Session, location_id: UUID) -> LocationOut:
    location = db.get(Location, location_id)
    if location is None:
        raise AppError("location_not_found", "Location not found", status_code=404)
    return LocationOut.model_validate(location)


def update_location(
    db: Session,
    location_id: UUID,
    payload: LocationUpdate,
    *,
    actor: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> LocationOut:
    location = db.get(Location, location_id)
    if location is None:
        raise AppError("location_not_found", "Location not found", status_code=404)

    before = {
        "name": location.name,
        "lat": location.lat,
        "lng": location.lng,
        "radius_m": location.radius_m,
        "active": location.active,
    }

    data = payload.model_dump(exclude_unset=True, exclude={"rotate_qr_secret"})
    for key, value in data.items():
        setattr(location, key, value)
    if payload.rotate_qr_secret:
        location.qr_secret = generate_qr_secret()

    db.add(location)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="location.update",
        entity_type="location",
        entity_id=str(location.id),
        before=before,
        after={
            "name": location.name,
            "lat": location.lat,
            "lng": location.lng,
            "radius_m": location.radius_m,
            "active": location.active,
            "qr_rotated": payload.rotate_qr_secret,
        },
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(location)
    return LocationOut.model_validate(location)
