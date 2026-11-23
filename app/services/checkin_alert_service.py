"""Late / missed check-in alerts for admin dashboard + security feed."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.models import (
    AttendanceRecord,
    AttendanceRecordStatus,
    Employee,
    SecurityEvent,
    SecurityEventSeverity,
    Shift,
)
from app.services import leave_service, notification_service, shift_service


def _tz(settings: Settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _business_now(settings: Settings) -> datetime:
    return datetime.now(_tz(settings))


def list_check_in_alerts(db: Session, settings: Settings) -> list[dict]:
    """
    Live alerts:
    - late: checked in after shift start + grace
    - missed: past grace and still no check-in (before shift end)
    """
    now = _business_now(settings)
    today = now.date()
    alerts: list[dict] = []

    records_today = {
        r.employee_id: r
        for r in db.scalars(
            select(AttendanceRecord).where(AttendanceRecord.work_date == today)
        ).all()
    }

    if shift_service.is_holiday(db, today, location_id=None) is not None:
        return []

    employees = db.scalars(
        select(Employee)
        .where(Employee.is_active.is_(True))
        .options(joinedload(Employee.user))
    ).unique().all()
    for emp in employees:
        record = records_today.get(emp.id)
        if record and record.status == AttendanceRecordStatus.ON_LEAVE.value:
            continue
        if leave_service.employee_on_leave(db, employee_id=emp.id, work_date=today):
            continue

        assignment = shift_service.current_assignment(db, emp.id, on_date=today)
        if assignment is None:
            continue
        shift = db.get(Shift, assignment.shift_id)
        if shift is None or not shift.active:
            continue

        start, end = shift_service.shift_bounds(shift, today, settings=settings)
        late_after = start + timedelta(minutes=shift.grace_late_minutes)
        full_name = emp.user.full_name if emp.user else emp.employee_code

        # Already checked in late
        if record and record.check_in_at is not None and record.is_late:
            check_in_at = record.check_in_at
            if check_in_at.tzinfo is None:
                check_in_at = check_in_at.replace(tzinfo=_tz(settings))
            minutes_over = max(0, int((check_in_at - start).total_seconds() // 60))
            alerts.append(
                {
                    "employee_id": str(emp.id),
                    "full_name": full_name,
                    "employee_code": emp.employee_code,
                    "kind": "late",
                    "shift_name": shift.name,
                    "scheduled_start": start.isoformat(),
                    "check_in_at": check_in_at.isoformat(),
                    "minutes_over": minutes_over,
                    "message": f"{full_name} checked in late ({minutes_over} min after shift start).",
                }
            )
            continue

        # Missed / not yet checked in after grace
        if record and record.check_in_at is not None:
            continue
        if now < late_after:
            continue
        # Only while shift is still expected (or shortly after start window)
        if now > end:
            # After shift end with no punch — still surface as missed for the day
            minutes_over = max(0, int((now - start).total_seconds() // 60))
            alerts.append(
                {
                    "employee_id": str(emp.id),
                    "full_name": full_name,
                    "employee_code": emp.employee_code,
                    "kind": "missed",
                    "shift_name": shift.name,
                    "scheduled_start": start.isoformat(),
                    "check_in_at": None,
                    "minutes_over": minutes_over,
                    "message": f"{full_name} did not check in for {shift.name}.",
                }
            )
            continue

        minutes_over = max(0, int((now - start).total_seconds() // 60))
        alerts.append(
            {
                "employee_id": str(emp.id),
                "full_name": full_name,
                "employee_code": emp.employee_code,
                "kind": "missed",
                "shift_name": shift.name,
                "scheduled_start": start.isoformat(),
                "check_in_at": None,
                "minutes_over": minutes_over,
                "message": (
                    f"{full_name} has not checked in — "
                    f"{minutes_over} min past {shift.name} start."
                ),
            }
        )

    # Missed first, then late; within each by minutes_over desc
    kind_order = {"missed": 0, "late": 1}
    alerts.sort(key=lambda a: (kind_order.get(a["kind"], 9), -int(a["minutes_over"])))
    return alerts


def _has_event_today(
    db: Session,
    *,
    employee_id: UUID,
    event_type: str,
    work_date_iso: str,
) -> bool:
    rows = db.scalars(
        select(SecurityEvent)
        .where(
            SecurityEvent.employee_id == employee_id,
            SecurityEvent.event_type == event_type,
        )
        .order_by(SecurityEvent.created_at.desc())
        .limit(20)
    ).all()
    for row in rows:
        details = row.details or {}
        if details.get("work_date") == work_date_iso:
            return True
    return False


def flag_missed_checkins(db: Session, settings: Settings) -> int:
    """Persist one security event + admin push per missed employee per day."""
    alerts = [a for a in list_check_in_alerts(db, settings) if a["kind"] == "missed"]
    today = _business_now(settings).date().isoformat()
    created = 0
    for alert in alerts:
        emp_id = UUID(alert["employee_id"])
        if _has_event_today(db, employee_id=emp_id, event_type="missed_checkin", work_date_iso=today):
            continue
        db.add(
            SecurityEvent(
                employee_id=emp_id,
                event_type="missed_checkin",
                severity=SecurityEventSeverity.WARNING.value,
                message=alert["message"],
                details={
                    "work_date": today,
                    "shift_name": alert["shift_name"],
                    "scheduled_start": alert["scheduled_start"],
                    "minutes_over": alert["minutes_over"],
                    "active": True,
                },
            )
        )
        notification_service.notify_admin(
            title="Missed check-in",
            message=alert["message"],
            priority=4,
            tags="alarm_clock,warning",
            settings=settings,
        )
        created += 1
    if created:
        db.commit()
    return created


def log_late_checkin(
    db: Session,
    *,
    employee: Employee,
    shift_name: str | None,
    check_in_at: datetime,
    minutes_over: int,
    settings: Settings,
) -> None:
    """One late-check-in security event + admin notify (caller commits)."""
    today = _business_now(settings).date().isoformat()
    if _has_event_today(
        db, employee_id=employee.id, event_type="late_checkin", work_date_iso=today
    ):
        return
    name = shift_name or "shift"
    full_name = employee.user.full_name if employee.user else employee.employee_code
    message = (
        f"{full_name} checked in late for {name} "
        f"({minutes_over} min after start)."
    )
    db.add(
        SecurityEvent(
            employee_id=employee.id,
            event_type="late_checkin",
            severity=SecurityEventSeverity.WARNING.value,
            message=message,
            details={
                "work_date": today,
                "shift_name": shift_name,
                "check_in_at": check_in_at.isoformat(),
                "minutes_over": minutes_over,
            },
        )
    )
    notification_service.notify_admin(
        title="Late check-in",
        message=message,
        priority=4,
        tags="clock,warning",
        settings=settings,
    )
