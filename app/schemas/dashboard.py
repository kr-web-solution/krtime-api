"""Dashboard response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SitePresenceOut(BaseModel):
    location_id: str
    name: str
    slug: str
    present: int


class CheckInAlertOut(BaseModel):
    employee_id: str
    full_name: str
    employee_code: str
    kind: str  # late | missed
    shift_name: str
    scheduled_start: str
    check_in_at: str | None = None
    minutes_over: int
    message: str


class DashboardOut(BaseModel):
    work_date: str
    timezone: str
    total_employees: int
    present: int
    absent: int
    late: int
    early_departure: int
    currently_checked_in: int
    on_leave: int
    rejected_attempts: int
    pending_review: int
    suspicious_events: int
    geofence_exits_today: int
    check_in_alerts_count: int
    devices_needing_attention: int
    by_site: list[SitePresenceOut]
    check_in_alerts: list[CheckInAlertOut]
