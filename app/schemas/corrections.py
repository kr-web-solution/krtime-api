"""Correction and month-lock schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class CorrectionCreate(BaseModel):
    attendance_record_id: UUID
    reason: str = Field(min_length=3, max_length=2000)
    proposed_check_in_at: datetime | None = None
    proposed_check_out_at: datetime | None = None


class CorrectionOut(ORMModel):
    id: UUID
    attendance_record_id: UUID
    requested_by_user_id: UUID
    reason: str
    proposed_check_in_at: datetime | None
    proposed_check_out_at: datetime | None
    linked_event_id: UUID | None
    status: str
    created_at: datetime


class CorrectionDecision(BaseModel):
    approve: bool
    notes: str | None = Field(default=None, max_length=1000)


class MonthLockRequest(BaseModel):
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
