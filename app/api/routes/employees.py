"""Employee admin CRUD + /me for mobile."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentEmployee, CurrentUser, DbSession, SuperAdminUser, client_meta
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models import Employee
from app.schemas.alerts import EmployeeAlertOut, EmployeeAlertRequest
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeMeOut,
    EmployeeOut,
    EmployeeUpdate,
    EnrollmentCodeOut,
)
from app.services import employee_service, notification_service
from app.services.audit import write_audit

router = APIRouter()


class EmployeeCreateResponse(BaseModel):
    employee: EmployeeOut
    enrollment_code: EnrollmentCodeOut | None = None


class EnrollmentCodeCreateRequest(BaseModel):
    hours: int = Field(default=72, ge=1, le=720)


@router.get("/me", response_model=EmployeeMeOut)
def employees_me(user: CurrentUser, employee: CurrentEmployee, db: DbSession) -> EmployeeMeOut:
    # reload links
    row = db.scalar(
        select(Employee)
        .options(selectinload(Employee.location_links), selectinload(Employee.user))
        .where(Employee.id == employee.id)
    )
    assert row is not None
    return EmployeeMeOut(
        id=row.id,
        employee_code=row.employee_code,
        full_name=row.user.full_name,
        email=row.user.email,
        phone=row.phone,
        job_title=row.job_title,
        role=user.role,
        location_ids=[link.location_id for link in row.location_links],
        is_active=row.is_active,
    )


@router.get("", response_model=list[EmployeeOut])
def list_employees(
    db: DbSession,
    _: AdminUser,
    active_only: Annotated[bool, Query()] = False,
) -> list[EmployeeOut]:
    return employee_service.list_employees(db, active_only=active_only)


@router.post("", response_model=EmployeeCreateResponse, status_code=201)
def create_employee(
    payload: EmployeeCreate,
    request: Request,
    db: DbSession,
    actor: SuperAdminUser,
) -> EmployeeCreateResponse:
    employee, code = employee_service.create_employee(
        db, payload, actor=actor, **client_meta(request)
    )
    return EmployeeCreateResponse(employee=employee, enrollment_code=code)


@router.get("/{employee_id}", response_model=EmployeeOut)
def get_employee(employee_id: UUID, db: DbSession, _: AdminUser) -> EmployeeOut:
    return employee_service.get_employee(db, employee_id)


@router.patch("/{employee_id}", response_model=EmployeeOut)
def update_employee(
    employee_id: UUID,
    payload: EmployeeUpdate,
    request: Request,
    db: DbSession,
    actor: SuperAdminUser,
) -> EmployeeOut:
    return employee_service.update_employee(
        db, employee_id, payload, actor=actor, **client_meta(request)
    )


@router.post("/{employee_id}/enrollment-codes", response_model=EnrollmentCodeOut, status_code=201)
def create_enrollment_code(
    employee_id: UUID,
    payload: EnrollmentCodeCreateRequest,
    db: DbSession,
    actor: SuperAdminUser,
) -> EnrollmentCodeOut:
    return employee_service.create_enrollment_code_for_employee(
        db, employee_id, actor=actor, hours=payload.hours
    )


@router.post("/{employee_id}/alerts", response_model=EmployeeAlertOut)
def send_employee_alert(
    employee_id: UUID,
    payload: EmployeeAlertRequest,
    db: DbSession,
    actor: AdminUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> EmployeeAlertOut:
    employee = db.get(Employee, employee_id)
    if employee is None or not employee.is_active:
        raise AppError("employee_not_found", "Employee not found", status_code=404)
    try:
        title, message, delivered, enabled = notification_service.send_employee_alert(
            db,
            employee_id=employee_id,
            alert_type=payload.alert_type.value,
            note=payload.note,
            settings=settings,
        )
    except ValueError as exc:
        raise AppError("invalid_alert", str(exc), status_code=400) from exc

    write_audit(
        db,
        actor_user_id=actor.id,
        action="employee.alert",
        entity_type="employee",
        entity_id=str(employee_id),
        after={
            "alert_type": payload.alert_type.value,
            "delivered": delivered,
            "note": payload.note,
        },
    )
    db.commit()

    if not enabled:
        raise AppError(
            "push_disabled",
            "Push notifications are not configured on the server (NTFY_BASE_URL)",
            status_code=503,
        )
    if delivered == 0:
        raise AppError(
            "no_subscription",
            "Employee has no push subscription. Ask them to open KRTime and subscribe in ntfy.",
            status_code=409,
        )

    return EmployeeAlertOut(
        employee_id=str(employee_id),
        alert_type=payload.alert_type,
        title=title,
        message=message,
        delivered=delivered,
        push_enabled=enabled,
    )
