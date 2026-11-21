"""Shift catalogue, assignment, window/late/early rules, holidays helper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models import Employee, Holiday, Shift, ShiftAssignment, User
from app.services.audit import write_audit


def list_shifts(db: Session, *, active_only: bool = True) -> list[Shift]:
    stmt = select(Shift).order_by(Shift.name)
    if active_only:
        stmt = stmt.where(Shift.active.is_(True))
    return list(db.scalars(stmt).all())


def create_shift(
    db: Session,
    *,
    name: str,
    code: str | None,
    start_time: time,
    end_time: time,
    grace_late_minutes: int,
    grace_early_minutes: int,
    cross_midnight: bool,
    actor: User,
) -> Shift:
    if db.scalar(select(Shift).where(Shift.name == name.strip())):
        raise AppError("shift_name_taken", "Shift name already exists", status_code=409)
    shift = Shift(
        name=name.strip(),
        code=code,
        start_time=start_time,
        end_time=end_time,
        grace_late_minutes=grace_late_minutes,
        grace_early_minutes=grace_early_minutes,
        cross_midnight=cross_midnight,
        active=True,
    )
    db.add(shift)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="shift.create",
        entity_type="shift",
        entity_id=name,
    )
    db.commit()
    db.refresh(shift)
    return shift


def assign_shift(
    db: Session,
    *,
    employee_id: UUID,
    shift_id: UUID,
    effective_from: date,
    actor: User,
) -> ShiftAssignment:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise AppError("employee_not_found", "Employee not found", status_code=404)
    shift = db.get(Shift, shift_id)
    if shift is None or not shift.active:
        raise AppError("shift_not_found", "Shift not found", status_code=404)

    existing = db.scalars(
        select(ShiftAssignment).where(
            ShiftAssignment.employee_id == employee_id,
            ShiftAssignment.active.is_(True),
            ShiftAssignment.effective_to.is_(None),
        )
    ).all()
    for row in existing:
        if row.effective_from < effective_from:
            row.effective_to = effective_from
        row.active = False
        db.add(row)

    assignment = ShiftAssignment(
        employee_id=employee_id,
        shift_id=shift_id,
        effective_from=effective_from,
        active=True,
    )
    db.add(assignment)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="shift.assign",
        entity_type="shift_assignment",
        entity_id=str(employee_id),
        after={"shift_id": str(shift_id), "effective_from": effective_from.isoformat()},
    )
    db.commit()
    db.refresh(assignment)
    return assignment


def current_assignment(db: Session, employee_id: UUID, on_date: date | None = None) -> ShiftAssignment | None:
    day = on_date or date.today()
    return db.scalar(
        select(ShiftAssignment)
        .where(
            ShiftAssignment.employee_id == employee_id,
            ShiftAssignment.active.is_(True),
            ShiftAssignment.effective_from <= day,
            or_(ShiftAssignment.effective_to.is_(None), ShiftAssignment.effective_to >= day),
        )
        .order_by(ShiftAssignment.effective_from.desc())
    )


def _tz(settings: Settings) -> ZoneInfo:
    try:
        return ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def shift_bounds(
    shift: Shift,
    work_date: date,
    *,
    settings: Settings,
) -> tuple[datetime, datetime]:
    """Return aware start/end datetimes for the shift on work_date."""
    tz = _tz(settings)
    start = datetime.combine(work_date, shift.start_time, tzinfo=tz)
    if shift.cross_midnight or shift.end_time <= shift.start_time:
        end = datetime.combine(work_date + timedelta(days=1), shift.end_time, tzinfo=tz)
    else:
        end = datetime.combine(work_date, shift.end_time, tzinfo=tz)
    return start, end


@dataclass
class ShiftWindowResult:
    allowed: bool
    reason_code: str | None = None
    is_late: bool = False
    is_early_departure: bool = False
    shift: Shift | None = None
    assignment: ShiftAssignment | None = None


def is_holiday(
    db: Session,
    work_date: date,
    *,
    location_id: UUID | None = None,
) -> Holiday | None:
    rows = db.scalars(
        select(Holiday).where(
            Holiday.holiday_date == work_date,
            Holiday.is_optional.is_(False),
        )
    ).all()
    for h in rows:
        if h.location_id is None or h.location_id == location_id:
            return h
    return None


def evaluate_shift_window(
    db: Session,
    *,
    employee_id: UUID,
    work_date: date,
    when: datetime,
    purpose: str,
    settings: Settings,
    location_id: UUID | None = None,
    enforce_window: bool = True,
) -> ShiftWindowResult:
    """Check holiday + shift window. Late/early flagged but still allowed within grace+window."""
    holiday = is_holiday(db, work_date, location_id=location_id)
    if holiday is not None and purpose == "check_in":
        return ShiftWindowResult(allowed=False, reason_code="holiday")

    assignment = current_assignment(db, employee_id, on_date=work_date)
    if assignment is None:
        # No shift assigned: allow attendance (lab / flexible sites).
        return ShiftWindowResult(allowed=True, assignment=None, shift=None)

    shift = db.get(Shift, assignment.shift_id)
    if shift is None or not shift.active:
        return ShiftWindowResult(allowed=True, assignment=assignment, shift=None)

    start, end = shift_bounds(shift, work_date, settings=settings)
    if when.tzinfo is None:
        when = when.replace(tzinfo=_tz(settings))
    else:
        when = when.astimezone(_tz(settings))

    window_open = start - timedelta(minutes=shift.grace_late_minutes)
    # Allow check-in until end; check-out until end + early grace after earliest leave.
    if purpose == "check_in":
        if enforce_window and (when < window_open or when > end):
            return ShiftWindowResult(
                allowed=False,
                reason_code="outside_shift",
                shift=shift,
                assignment=assignment,
            )
        late_after = start + timedelta(minutes=shift.grace_late_minutes)
        return ShiftWindowResult(
            allowed=True,
            is_late=when > late_after,
            shift=shift,
            assignment=assignment,
        )

    # check_out
    earliest_out = end - timedelta(minutes=shift.grace_early_minutes)
    latest_out = end + timedelta(minutes=max(shift.grace_early_minutes, 60))
    if enforce_window and when > latest_out:
        return ShiftWindowResult(
            allowed=False,
            reason_code="outside_shift",
            shift=shift,
            assignment=assignment,
        )
    return ShiftWindowResult(
        allowed=True,
        is_early_departure=when < earliest_out,
        shift=shift,
        assignment=assignment,
    )


def my_shift(db: Session, *, employee_id: UUID, settings: Settings) -> dict | None:
    assignment = current_assignment(db, employee_id)
    if assignment is None:
        return None
    shift = db.get(Shift, assignment.shift_id)
    if shift is None:
        return None
    today = datetime.now(_tz(settings)).date()
    start, end = shift_bounds(shift, today, settings=settings)
    return {
        "assignment_id": assignment.id,
        "shift_id": shift.id,
        "name": shift.name,
        "code": shift.code,
        "start_time": shift.start_time,
        "end_time": shift.end_time,
        "grace_late_minutes": shift.grace_late_minutes,
        "grace_early_minutes": shift.grace_early_minutes,
        "cross_midnight": shift.cross_midnight,
        "effective_from": assignment.effective_from,
        "effective_to": assignment.effective_to,
        "today_window_start": start,
        "today_window_end": end,
    }


# --- Holidays ---


def list_holidays(db: Session, *, year: int | None = None) -> list[Holiday]:
    stmt = select(Holiday).order_by(Holiday.holiday_date)
    if year is not None:
        stmt = stmt.where(
            Holiday.holiday_date >= date(year, 1, 1),
            Holiday.holiday_date <= date(year, 12, 31),
        )
    return list(db.scalars(stmt).all())


def create_holiday(
    db: Session,
    *,
    name: str,
    holiday_date: date,
    location_id: UUID | None,
    is_optional: bool,
    actor: User,
) -> Holiday:
    row = Holiday(
        name=name.strip(),
        holiday_date=holiday_date,
        location_id=location_id,
        is_optional=is_optional,
    )
    db.add(row)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="holiday.create",
        entity_type="holiday",
        entity_id=holiday_date.isoformat(),
        after={"name": name, "location_id": str(location_id) if location_id else None},
    )
    db.commit()
    db.refresh(row)
    return row


def delete_holiday(db: Session, *, holiday_id: UUID, actor: User) -> None:
    row = db.get(Holiday, holiday_id)
    if row is None:
        raise AppError("holiday_not_found", "Holiday not found", status_code=404)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="holiday.delete",
        entity_type="holiday",
        entity_id=str(holiday_id),
        before={"name": row.name, "date": row.holiday_date.isoformat()},
    )
    db.delete(row)
    db.commit()
