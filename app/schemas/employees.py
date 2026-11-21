"""Employee schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import ORMModel


class EmployeeCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=160)
    employee_code: str = Field(min_length=2, max_length=40)
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=120)
    department_id: UUID | None = None
    location_ids: list[UUID] = Field(default_factory=list)
    primary_location_id: UUID | None = None
    shift_id: UUID | None = None
    temporary_password: str | None = Field(default=None, min_length=10, max_length=128)
    create_enrollment_code: bool = True
    enrollment_code_hours: int = Field(default=72, ge=1, le=720)


class EmployeeUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    phone: str | None = Field(default=None, max_length=32)
    job_title: str | None = Field(default=None, max_length=120)
    department_id: UUID | None = None
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)
    location_ids: list[UUID] | None = None
    primary_location_id: UUID | None = None
    shift_id: UUID | None = None


class EnrollmentCodeOut(ORMModel):
    id: UUID
    code: str
    status: str
    expires_at: datetime
    created_at: datetime


class EmployeeOut(ORMModel):
    id: UUID
    user_id: UUID
    employee_code: str
    full_name: str
    email: str
    phone: str | None
    job_title: str | None
    department_id: UUID | None
    is_active: bool
    notes: str | None
    location_ids: list[UUID]
    primary_location_id: UUID | None
    current_shift_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class EmployeeMeOut(ORMModel):
    id: UUID
    employee_code: str
    full_name: str
    email: str
    phone: str | None
    job_title: str | None
    role: str
    location_ids: list[UUID]
    is_active: bool
