"""Employee admin CRUD + /me for mobile."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import selectinload
from sqlalchemy import select

from app.api.deps import AdminUser, CurrentEmployee, CurrentUser, DbSession, SuperAdminUser, client_meta
from app.models import Employee
from app.schemas.employees import (
    EmployeeCreate,
    EmployeeMeOut,
    EmployeeOut,
    EmployeeUpdate,
    EnrollmentCodeOut,
)
from app.services import employee_service

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
