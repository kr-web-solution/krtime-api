"""Shift schemas."""

from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ShiftCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    code: str | None = Field(default=None, max_length=40)
    start_time: time
    end_time: time
    grace_late_minutes: int = Field(default=10, ge=0, le=120)
    grace_early_minutes: int = Field(default=10, ge=0, le=120)
    cross_midnight: bool = False


class ShiftOut(ORMModel):
    id: UUID
    name: str
    code: str | None
    start_time: time
    end_time: time
    grace_late_minutes: int
    grace_early_minutes: int
    cross_midnight: bool
    active: bool
    created_at: datetime


class ShiftAssignRequest(BaseModel):
    shift_id: UUID
    effective_from: date | None = None


class ShiftAssignmentOut(ORMModel):
    id: UUID
    employee_id: UUID
    shift_id: UUID
    effective_from: date
    effective_to: date | None
    active: bool


class MyShiftOut(BaseModel):
    assignment_id: UUID
    shift_id: UUID
    name: str
    code: str | None
    start_time: time
    end_time: time
    grace_late_minutes: int
    grace_early_minutes: int
    cross_midnight: bool
    effective_from: date
    effective_to: date | None
    today_window_start: datetime
    today_window_end: datetime
