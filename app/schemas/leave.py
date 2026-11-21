"""Leave schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LeaveTypeOut(ORMModel):
    id: UUID
    name: str
    code: str
    paid: bool
    annual_allowance_days: int | None
    active: bool


class LeaveApplyRequest(BaseModel):
    leave_type_id: UUID
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=2000)


class LeaveRequestOut(ORMModel):
    id: UUID
    employee_id: UUID
    leave_type_id: UUID
    start_date: date
    end_date: date
    reason: str | None
    status: str
    decided_by_user_id: UUID | None
    decided_at: datetime | None
    decision_notes: str | None
    created_at: datetime


class LeaveDecision(BaseModel):
    approve: bool
    notes: str | None = Field(default=None, max_length=1000)
