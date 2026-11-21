"""Admin → employee alert notification schemas."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class EmployeeAlertType(StrEnum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    RETURN_SITE = "return_site"
    CALL_ADMIN = "call_admin"
    URGENT = "urgent"
    CUSTOM = "custom"


class EmployeeAlertRequest(BaseModel):
    alert_type: EmployeeAlertType = EmployeeAlertType.CUSTOM
    title: str | None = Field(default=None, max_length=120)
    message: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=280)

    @model_validator(mode="after")
    def require_message_for_custom(self) -> EmployeeAlertRequest:
        if self.alert_type == EmployeeAlertType.CUSTOM:
            if not (self.message or "").strip():
                raise ValueError("message is required for custom notifications")
        return self


class EmployeeAlertOut(BaseModel):
    employee_id: str
    alert_type: EmployeeAlertType
    title: str
    message: str
    delivered: int
    push_enabled: bool
