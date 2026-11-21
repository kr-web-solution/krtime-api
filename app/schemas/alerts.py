"""Admin → employee alert notification schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class EmployeeAlertType(StrEnum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    RETURN_SITE = "return_site"
    CALL_ADMIN = "call_admin"
    URGENT = "urgent"


class EmployeeAlertRequest(BaseModel):
    alert_type: EmployeeAlertType
    note: str | None = Field(default=None, max_length=280)


class EmployeeAlertOut(BaseModel):
    employee_id: str
    alert_type: EmployeeAlertType
    title: str
    message: str
    delivered: int
    push_enabled: bool
