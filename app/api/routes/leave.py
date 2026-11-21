"""Employee leave apply + admin approvals."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, CurrentEmployee, CurrentUser, DbSession, SuperAdminUser
from app.schemas.leave import LeaveApplyRequest, LeaveDecision, LeaveRequestOut, LeaveTypeOut
from app.services import leave_service

router = APIRouter()


@router.get("/types", response_model=list[LeaveTypeOut])
def leave_types(db: DbSession, _: CurrentUser) -> list[LeaveTypeOut]:
    return [LeaveTypeOut.model_validate(t) for t in leave_service.list_leave_types(db)]


@router.post("/apply", response_model=LeaveRequestOut, status_code=201)
def apply_leave(
    payload: LeaveApplyRequest,
    db: DbSession,
    employee: CurrentEmployee,
) -> LeaveRequestOut:
    row = leave_service.apply_leave(
        db,
        employee=employee,
        leave_type_id=payload.leave_type_id,
        start_date=payload.start_date,
        end_date=payload.end_date,
        reason=payload.reason,
    )
    return LeaveRequestOut.model_validate(row)


@router.get("/history", response_model=list[LeaveRequestOut])
def my_leave_history(
    db: DbSession,
    employee: CurrentEmployee,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[LeaveRequestOut]:
    rows = leave_service.list_employee_leave(db, employee_id=employee.id, limit=limit)
    return [LeaveRequestOut.model_validate(r) for r in rows]


@router.delete("/{request_id}", response_model=LeaveRequestOut)
def cancel_leave(
    request_id: UUID,
    db: DbSession,
    employee: CurrentEmployee,
) -> LeaveRequestOut:
    row = leave_service.cancel_leave(db, request_id=request_id, employee=employee)
    return LeaveRequestOut.model_validate(row)


@router.get("/admin", response_model=list[LeaveRequestOut])
def admin_list_leave(
    db: DbSession,
    _: AdminUser,
    pending_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> list[LeaveRequestOut]:
    rows = (
        leave_service.list_pending_leave(db, limit=limit)
        if pending_only
        else leave_service.list_all_leave(db, limit=limit)
    )
    return [LeaveRequestOut.model_validate(r) for r in rows]


@router.post("/admin/{request_id}/decide", response_model=LeaveRequestOut)
def admin_decide_leave(
    request_id: UUID,
    payload: LeaveDecision,
    db: DbSession,
    actor: SuperAdminUser,
) -> LeaveRequestOut:
    row = leave_service.decide_leave(
        db,
        request_id=request_id,
        approve=payload.approve,
        notes=payload.notes,
        actor=actor,
    )
    return LeaveRequestOut.model_validate(row)
