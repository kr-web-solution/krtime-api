"""Dashboard response schemas."""

from __future__ import annotations

from pydantic import BaseModel


class SitePresenceOut(BaseModel):
    location_id: str
    name: str
    slug: str
    present: int


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
    devices_needing_attention: int
    by_site: list[SitePresenceOut]
