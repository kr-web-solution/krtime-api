"""Admin dashboard KPIs and daily attendance board."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import AdminUser, DbSession
from app.core.config import Settings, get_settings
from app.schemas.daily_attendance import DailyAttendanceOut
from app.schemas.dashboard import DashboardOut
from app.services import daily_attendance_service, dashboard_service

router = APIRouter()


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: DbSession,
    _: AdminUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DashboardOut:
    return DashboardOut(**dashboard_service.dashboard_summary(db, settings))


@router.get("/daily-attendance", response_model=DailyAttendanceOut)
def get_daily_attendance(
    db: DbSession,
    _: AdminUser,
    settings: Annotated[Settings, Depends(get_settings)],
) -> DailyAttendanceOut:
    return daily_attendance_service.daily_attendance_board(db, settings)
