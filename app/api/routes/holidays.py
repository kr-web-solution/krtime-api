"""Holiday catalogue."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response

from app.api.deps import AdminUser, DbSession, SuperAdminUser
from app.schemas.holidays import HolidayCreate, HolidayOut
from app.services import shift_service

router = APIRouter()


@router.get("", response_model=list[HolidayOut])
def list_holidays(
    db: DbSession,
    _: AdminUser,
    year: Annotated[int | None, Query()] = None,
) -> list[HolidayOut]:
    return [HolidayOut.model_validate(h) for h in shift_service.list_holidays(db, year=year)]


@router.post("", response_model=HolidayOut, status_code=201)
def create_holiday(payload: HolidayCreate, db: DbSession, actor: SuperAdminUser) -> HolidayOut:
    row = shift_service.create_holiday(
        db,
        name=payload.name,
        holiday_date=payload.holiday_date,
        location_id=payload.location_id,
        is_optional=payload.is_optional,
        actor=actor,
    )
    return HolidayOut.model_validate(row)


@router.delete("/{holiday_id}")
def delete_holiday(holiday_id: UUID, db: DbSession, actor: SuperAdminUser) -> Response:
    shift_service.delete_holiday(db, holiday_id=holiday_id, actor=actor)
    return Response(status_code=204)
