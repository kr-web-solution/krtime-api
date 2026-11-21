"""Admin daily attendance board schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DailyAttendanceEmployeeOut(BaseModel):
    employee_id: UUID
    full_name: str
    employee_code: str
    record_id: UUID
    status: str
    check_in_at: datetime | None
    check_out_at: datetime | None
    is_late: bool
    presence_status: str  # inside | outside | mocked | unknown | checked_out | on_leave
    presence_at: datetime | None = None
    distance_m: float | None = None
    lat: float | None = None
    lng: float | None = None
    accuracy_m: float | None = None


class DailyAttendanceLocationOut(BaseModel):
    location_id: UUID | None
    name: str
    slug: str | None = None
    checked_in_count: int
    inside_count: int
    outside_count: int
    employees: list[DailyAttendanceEmployeeOut]


class DailyAttendanceOut(BaseModel):
    work_date: str
    timezone: str
    total_checked_in: int
    currently_open: int
    inside_count: int
    outside_count: int
    locations: list[DailyAttendanceLocationOut]
