"""Shift catalogue, assignment, and employee my-shift."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response

from app.api.deps import AdminUser, CurrentEmployee, DbSession, SuperAdminUser
from app.core.config import Settings, get_settings
from app.schemas.shifts import MyShiftOut, ShiftAssignRequest, ShiftAssignmentOut, ShiftCreate, ShiftOut
from app.services import shift_service

router = APIRouter()


@router.get("/my", response_model=MyShiftOut | None)
def my_shift(
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> MyShiftOut | None:
    data = shift_service.my_shift(db, employee_id=employee.id, settings=settings)
    if data is None:
        return None
    return MyShiftOut(**data)


@router.get("", response_model=list[ShiftOut])
def list_shifts(db: DbSession, _: AdminUser) -> list[ShiftOut]:
    return [ShiftOut.model_validate(s) for s in shift_service.list_shifts(db)]


@router.post("", response_model=ShiftOut, status_code=201)
def create_shift(payload: ShiftCreate, db: DbSession, actor: SuperAdminUser) -> ShiftOut:
    shift = shift_service.create_shift(
        db,
        name=payload.name,
        code=payload.code,
        start_time=payload.start_time,
        end_time=payload.end_time,
        grace_late_minutes=payload.grace_late_minutes,
        grace_early_minutes=payload.grace_early_minutes,
        cross_midnight=payload.cross_midnight,
        actor=actor,
    )
    return ShiftOut.model_validate(shift)


@router.delete("/{shift_id}")
def delete_shift(shift_id: UUID, db: DbSession, actor: SuperAdminUser) -> Response:
    shift_service.delete_shift(db, shift_id=shift_id, actor=actor)
    return Response(status_code=204)


@router.post("/employees/{employee_id}/assign", response_model=ShiftAssignmentOut)
def assign_shift(
    employee_id: UUID,
    payload: ShiftAssignRequest,
    db: DbSession,
    actor: SuperAdminUser,
) -> ShiftAssignmentOut:
    assignment = shift_service.assign_shift(
        db,
        employee_id=employee_id,
        shift_id=payload.shift_id,
        effective_from=payload.effective_from or date.today(),
        actor=actor,
    )
    return ShiftAssignmentOut.model_validate(assignment)
