"""Aggregate /api/v1 routers."""

from fastapi import APIRouter

from app.api.routes import (
    admin_dashboard,
    attendance,
    auth,
    biometrics,
    corrections,
    devices,
    employees,
    health,
    holidays,
    leave,
    locations,
    qr,
    reports,
    reviews,
    security_events,
    settings,
    shifts,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(employees.router, prefix="/employees", tags=["employees"])
api_router.include_router(locations.router, prefix="/locations", tags=["locations"])
api_router.include_router(devices.router, prefix="/devices", tags=["devices"])
api_router.include_router(qr.router, prefix="/qr", tags=["qr"])
api_router.include_router(admin_dashboard.router, prefix="/admin", tags=["admin"])
api_router.include_router(shifts.router, prefix="/shifts", tags=["shifts"])
api_router.include_router(holidays.router, prefix="/holidays", tags=["holidays"])
api_router.include_router(leave.router, prefix="/leave", tags=["leave"])
api_router.include_router(corrections.router, prefix="/corrections", tags=["corrections"])
api_router.include_router(reports.router, prefix="/admin/reports", tags=["reports"])
api_router.include_router(attendance.router, prefix="/attendance", tags=["attendance"])
api_router.include_router(biometrics.router, prefix="/biometrics", tags=["biometrics"])
api_router.include_router(settings.router, prefix="/admin/settings", tags=["settings"])
api_router.include_router(reviews.router, prefix="/admin/reviews", tags=["reviews"])
api_router.include_router(
    security_events.router, prefix="/admin/security-events", tags=["security-events"]
)
