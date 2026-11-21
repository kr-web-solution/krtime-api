"""Holiday schemas."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class HolidayCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    holiday_date: date
    location_id: UUID | None = None
    is_optional: bool = False


class HolidayOut(ORMModel):
    id: UUID
    name: str
    holiday_date: date
    location_id: UUID | None
    is_optional: bool
    created_at: datetime
