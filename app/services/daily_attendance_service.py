"""Admin daily attendance board: check-ins grouped by site with presence."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.config import Settings
from app.core.errors import AppError
from app.models import (
    AttendanceRecord,
    AttendanceRecordStatus,
    Employee,
    Location,
    User,
)
from app.schemas.daily_attendance import (
    DailyAttendanceEmployeeOut,
    DailyAttendanceLocationOut,
    DailyAttendanceOut,
)
from app.services.audit import write_audit


def _business_today(settings: Settings) -> date:
    try:
        tz = ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def _presence_for_record(record: AttendanceRecord) -> tuple[str, datetime | None]:
    if record.status == AttendanceRecordStatus.ON_LEAVE.value:
        return "on_leave", None
    if record.status == AttendanceRecordStatus.COMPLETE.value:
        return "checked_out", record.last_presence_at
    if record.status == AttendanceRecordStatus.MISSING_CHECKOUT.value:
        # Still treat last ping if any
        if record.last_presence_status in {"inside", "outside", "mocked"}:
            return record.last_presence_status, record.last_presence_at
        return "unknown", record.last_presence_at
    if record.status == AttendanceRecordStatus.OPEN.value:
        if record.last_presence_status in {"inside", "outside", "mocked"}:
            return record.last_presence_status, record.last_presence_at
        return "unknown", None
    return "unknown", record.last_presence_at


def daily_attendance_board(db: Session, settings: Settings) -> DailyAttendanceOut:
    today = _business_today(settings)
    records = db.scalars(
        select(AttendanceRecord)
        .where(
            AttendanceRecord.work_date == today,
            AttendanceRecord.check_in_at.is_not(None),
        )
        .order_by(AttendanceRecord.check_in_at.asc())
    ).all()

    employee_ids = {r.employee_id for r in records}
    employees = {
        e.id: e
        for e in db.scalars(
            select(Employee)
            .options(selectinload(Employee.user))
            .where(Employee.id.in_(employee_ids))
        ).all()
    } if employee_ids else {}

    location_ids = {r.location_id for r in records if r.location_id}
    locations = {
        loc.id: loc
        for loc in db.scalars(select(Location).where(Location.id.in_(location_ids))).all()
    } if location_ids else {}

    # Also include active locations with zero check-ins for empty sections? Plan said
    # categorize by location — show only locations that have check-ins, plus Unassigned.
    grouped: dict[UUID | None, list[DailyAttendanceEmployeeOut]] = defaultdict(list)

    inside_total = 0
    outside_total = 0
    open_total = 0

    for record in records:
        emp = employees.get(record.employee_id)
        user: User | None = emp.user if emp else None
        presence, presence_at = _presence_for_record(record)
        if record.status == AttendanceRecordStatus.OPEN.value:
            open_total += 1
        if presence == "inside":
            inside_total += 1
        elif presence == "outside":
            outside_total += 1

        row = DailyAttendanceEmployeeOut(
            employee_id=record.employee_id,
            full_name=(user.full_name if user else None) or (emp.employee_code if emp else "Unknown"),
            employee_code=emp.employee_code if emp else "—",
            record_id=record.id,
            status=record.status,
            check_in_at=record.check_in_at,
            check_out_at=record.check_out_at,
            is_late=record.is_late,
            presence_status=presence,
            presence_at=presence_at,
            distance_m=record.last_presence_distance_m,
            lat=record.last_presence_lat,
            lng=record.last_presence_lng,
            accuracy_m=record.last_presence_accuracy_m,
        )
        grouped[record.location_id].append(row)

    location_blocks: list[DailyAttendanceLocationOut] = []
    # Sort named locations by name; unassigned last
    named_ids = sorted(
        (lid for lid in grouped if lid is not None),
        key=lambda lid: (locations[lid].name if lid in locations else str(lid)).lower(),
    )
    for lid in named_ids:
        loc = locations.get(lid)
        emps = grouped[lid]
        location_blocks.append(
            DailyAttendanceLocationOut(
                location_id=lid,
                name=loc.name if loc else "Unknown site",
                slug=loc.slug if loc else None,
                checked_in_count=len(emps),
                inside_count=sum(1 for e in emps if e.presence_status == "inside"),
                outside_count=sum(1 for e in emps if e.presence_status == "outside"),
                employees=emps,
            )
        )
    if None in grouped:
        emps = grouped[None]
        location_blocks.append(
            DailyAttendanceLocationOut(
                location_id=None,
                name="Unassigned site",
                slug=None,
                checked_in_count=len(emps),
                inside_count=sum(1 for e in emps if e.presence_status == "inside"),
                outside_count=sum(1 for e in emps if e.presence_status == "outside"),
                employees=emps,
            )
        )

    return DailyAttendanceOut(
        work_date=today.isoformat(),
        timezone=settings.business_timezone,
        total_checked_in=len(records),
        currently_open=open_total,
        inside_count=inside_total,
        outside_count=outside_total,
        locations=location_blocks,
    )


def delete_attendance_record(
    db: Session,
    *,
    record_id: UUID,
    actor: User,
) -> None:
    """Remove a daily summary row. Append-only attendance_events are kept for audit."""
    record = db.get(AttendanceRecord, record_id)
    if record is None:
        raise AppError("attendance_not_found", "Attendance record not found", status_code=404)
    if record.month_locked:
        raise AppError(
            "month_locked",
            "This attendance day is month-locked and cannot be deleted",
            status_code=409,
        )
    write_audit(
        db,
        actor_user_id=actor.id,
        action="attendance.delete",
        entity_type="attendance_record",
        entity_id=str(record_id),
        before={
            "employee_id": str(record.employee_id),
            "work_date": record.work_date.isoformat(),
            "status": record.status,
            "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
            "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
        },
    )
    db.delete(record)
    db.commit()
