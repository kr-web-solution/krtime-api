"""Admin dashboard KPI aggregation (Phase 2 baseline)."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import (
    AttendanceEvent,
    AttendanceOutcome,
    AttendanceRecord,
    AttendanceRecordStatus,
    DeviceStatus,
    Employee,
    Location,
    RegisteredDevice,
    SecurityEvent,
)


def _business_today(settings: Settings) -> date:
    try:
        tz = ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def dashboard_summary(db: Session, settings: Settings) -> dict:
    today = _business_today(settings)
    total_employees = db.scalar(
        select(func.count()).select_from(Employee).where(Employee.is_active.is_(True))
    ) or 0

    records_today = db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.work_date == today)
    ).all()

    present = sum(
        1
        for r in records_today
        if r.status in {
            AttendanceRecordStatus.OPEN.value,
            AttendanceRecordStatus.COMPLETE.value,
            AttendanceRecordStatus.MISSING_CHECKOUT.value,
        }
        and r.check_in_at is not None
    )
    currently_in = sum(1 for r in records_today if r.status == AttendanceRecordStatus.OPEN.value)
    late = sum(1 for r in records_today if r.is_late)
    early = sum(1 for r in records_today if r.is_early_departure)
    on_leave = sum(1 for r in records_today if r.status == AttendanceRecordStatus.ON_LEAVE.value)
    absent = max(total_employees - present - on_leave, 0)

    # By site (open check-ins today)
    by_site_rows = db.execute(
        select(Location.id, Location.name, Location.slug, func.count(AttendanceRecord.id))
        .outerjoin(
            AttendanceRecord,
            (AttendanceRecord.location_id == Location.id)
            & (AttendanceRecord.work_date == today)
            & (AttendanceRecord.check_in_at.is_not(None)),
        )
        .where(Location.active.is_(True))
        .group_by(Location.id, Location.name, Location.slug)
        .order_by(Location.name)
    ).all()
    by_site = [
        {
            "location_id": str(row[0]),
            "name": row[1],
            "slug": row[2],
            "present": int(row[3] or 0),
        }
        for row in by_site_rows
    ]

    day_start = datetime.combine(today, time.min, tzinfo=UTC)
    # Approximate: use UTC day bounds; fine for Phase 2 shell
    day_end = day_start + timedelta(days=1)
    rejected = db.scalar(
        select(func.count())
        .select_from(AttendanceEvent)
        .where(
            AttendanceEvent.outcome == AttendanceOutcome.REJECTED.value,
            AttendanceEvent.created_at >= day_start,
            AttendanceEvent.created_at < day_end,
        )
    ) or 0
    pending_review = db.scalar(
        select(func.count())
        .select_from(AttendanceEvent)
        .where(
            AttendanceEvent.outcome == AttendanceOutcome.PENDING_REVIEW.value,
            AttendanceEvent.created_at >= day_start,
            AttendanceEvent.created_at < day_end,
        )
    ) or 0
    suspicious = db.scalar(
        select(func.count())
        .select_from(SecurityEvent)
        .where(SecurityEvent.created_at >= day_start, SecurityEvent.created_at < day_end)
    ) or 0
    geofence_exits = db.scalar(
        select(func.count())
        .select_from(SecurityEvent)
        .where(
            SecurityEvent.event_type == "geofence_exit",
            SecurityEvent.created_at >= day_start,
            SecurityEvent.created_at < day_end,
        )
    ) or 0

    devices_pending = db.scalar(
        select(func.count())
        .select_from(RegisteredDevice)
        .where(
            RegisteredDevice.status.in_(
                [DeviceStatus.PENDING.value, DeviceStatus.RESET_REQUESTED.value]
            )
        )
    ) or 0

    return {
        "work_date": today.isoformat(),
        "timezone": settings.business_timezone,
        "total_employees": total_employees,
        "present": present,
        "absent": absent,
        "late": late,
        "early_departure": early,
        "currently_checked_in": currently_in,
        "on_leave": on_leave,
        "rejected_attempts": rejected,
        "pending_review": pending_review,
        "suspicious_events": suspicious,
        "geofence_exits_today": geofence_exits,
        "devices_needing_attention": devices_pending,
        "by_site": by_site,
    }
