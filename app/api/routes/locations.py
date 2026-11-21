"""Admin location CRUD."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request, Response

from app.api.deps import AdminUser, DbSession, SuperAdminUser, client_meta
from app.schemas.locations import LocationCreate, LocationOut, LocationUpdate
from app.services import location_service

router = APIRouter()


@router.get("", response_model=list[LocationOut])
def list_locations(
    db: DbSession,
    _: AdminUser,
    active_only: Annotated[bool, Query()] = False,
) -> list[LocationOut]:
    return location_service.list_locations(db, active_only=active_only)


@router.post("", response_model=LocationOut, status_code=201)
def create_location(
    payload: LocationCreate,
    request: Request,
    db: DbSession,
    actor: SuperAdminUser,
) -> LocationOut:
    return location_service.create_location(db, payload, actor=actor, **client_meta(request))


@router.get("/{location_id}", response_model=LocationOut)
def get_location(location_id: UUID, db: DbSession, _: AdminUser) -> LocationOut:
    return location_service.get_location(db, location_id)


@router.patch("/{location_id}", response_model=LocationOut)
def update_location(
    location_id: UUID,
    payload: LocationUpdate,
    request: Request,
    db: DbSession,
    actor: SuperAdminUser,
) -> LocationOut:
    return location_service.update_location(
        db, location_id, payload, actor=actor, **client_meta(request)
    )


@router.delete("/{location_id}")
def delete_location(
    location_id: UUID,
    request: Request,
    db: DbSession,
    actor: SuperAdminUser,
) -> Response:
    location_service.delete_location(
        db, location_id, actor=actor, **client_meta(request)
    )
    return Response(status_code=204)
