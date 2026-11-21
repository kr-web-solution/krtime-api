"""Leave types, employee apply, admin approve/reject."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import AppError
from app.models import (
    AttendanceRecord,
    AttendanceRecordStatus,
    Employee,
    LeaveRequest,
    LeaveRequestStatus,
    LeaveType,
    User,
)
from app.services import notification_service
from app.services.audit import write_audit


DEFAULT_LEAVE_TYPES: list[tuple[str, str, bool, int | None]] = [
    ("Casual Leave", "CL", True, 12),
    ("Sick Leave", "SL", True, 10),
    ("Earned Leave", "EL", True, 15),
    ("Unpaid Leave", "UL", False, None),
]


def ensure_leave_types(db: Session) -> None:
    for name, code, paid, allowance in DEFAULT_LEAVE_TYPES:
        exists = db.scalar(select(LeaveType).where(LeaveType.code == code))
        if exists is None:
            db.add(
                LeaveType(
                    name=name,
                    code=code,
                    paid=paid,
                    annual_allowance_days=allowance,
                    active=True,
                )
            )
    db.commit()


def list_leave_types(db: Session, *, active_only: bool = True) -> list[LeaveType]:
    stmt = select(LeaveType).order_by(LeaveType.name)
    if active_only:
        stmt = stmt.where(LeaveType.active.is_(True))
    return list(db.scalars(stmt).all())


def apply_leave(
    db: Session,
    *,
    employee: Employee,
    leave_type_id: UUID,
    start_date: date,
    end_date: date,
    reason: str | None,
) -> LeaveRequest:
    if end_date < start_date:
        raise AppError("invalid_dates", "end_date must be on or after start_date", status_code=400)
    leave_type = db.get(LeaveType, leave_type_id)
    if leave_type is None or not leave_type.active:
        raise AppError("leave_type_not_found", "Leave type not found", status_code=404)

    overlap = db.scalar(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee.id,
            LeaveRequest.status.in_(
                [LeaveRequestStatus.PENDING.value, LeaveRequestStatus.APPROVED.value]
            ),
            LeaveRequest.start_date <= end_date,
            LeaveRequest.end_date >= start_date,
        )
    )
    if overlap:
        raise AppError("leave_overlap", "Overlapping leave request exists", status_code=409)

    row = LeaveRequest(
        employee_id=employee.id,
        leave_type_id=leave_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
        status=LeaveRequestStatus.PENDING.value,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    notification_service.notify_admin(
        title="Leave request",
        message=(
            f"{employee.employee_code} requested leave "
            f"{start_date.isoformat()} → {end_date.isoformat()}"
        ),
        priority=3,
        tags="calendar",
        settings=get_settings(),
    )
    return row


def list_employee_leave(db: Session, *, employee_id: UUID, limit: int = 50) -> list[LeaveRequest]:
    return list(
        db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id)
            .order_by(LeaveRequest.created_at.desc())
            .limit(limit)
        ).all()
    )


def list_pending_leave(db: Session, *, limit: int = 100) -> list[LeaveRequest]:
    return list(
        db.scalars(
            select(LeaveRequest)
            .where(LeaveRequest.status == LeaveRequestStatus.PENDING.value)
            .order_by(LeaveRequest.created_at.asc())
            .limit(limit)
        ).all()
    )


def list_all_leave(db: Session, *, limit: int = 200) -> list[LeaveRequest]:
    return list(
        db.scalars(select(LeaveRequest).order_by(LeaveRequest.created_at.desc()).limit(limit)).all()
    )


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def decide_leave(
    db: Session,
    *,
    request_id: UUID,
    approve: bool,
    notes: str | None,
    actor: User,
) -> LeaveRequest:
    row = db.get(LeaveRequest, request_id)
    if row is None:
        raise AppError("leave_not_found", "Leave request not found", status_code=404)
    if row.status != LeaveRequestStatus.PENDING.value:
        raise AppError("leave_not_pending", "Leave request is not pending", status_code=400)

    row.status = LeaveRequestStatus.APPROVED.value if approve else LeaveRequestStatus.REJECTED.value
    row.decided_by_user_id = actor.id
    row.decided_at = datetime.now(UTC)
    row.decision_notes = notes
    db.add(row)

    if approve:
        for day in _daterange(row.start_date, row.end_date):
            existing = db.scalar(
                select(AttendanceRecord).where(
                    AttendanceRecord.employee_id == row.employee_id,
                    AttendanceRecord.work_date == day,
                )
            )
            if existing is None:
                db.add(
                    AttendanceRecord(
                        employee_id=row.employee_id,
                        work_date=day,
                        status=AttendanceRecordStatus.ON_LEAVE.value,
                    )
                )
            elif existing.status in {
                AttendanceRecordStatus.ABSENT.value,
                AttendanceRecordStatus.ON_LEAVE.value,
            } or (existing.check_in_at is None and existing.status != AttendanceRecordStatus.OPEN.value):
                if not existing.month_locked:
                    existing.status = AttendanceRecordStatus.ON_LEAVE.value
                    db.add(existing)

    write_audit(
        db,
        actor_user_id=actor.id,
        action="leave.decide",
        entity_type="leave_request",
        entity_id=str(request_id),
        after={"approve": approve, "notes": notes, "status": row.status},
    )
    db.commit()
    db.refresh(row)
    decision = "approved" if approve else "rejected"
    notification_service.notify_employee(
        db,
        employee_id=row.employee_id,
        title=f"Leave {decision}",
        message=(
            f"Your leave {row.start_date.isoformat()} → {row.end_date.isoformat()} "
            f"was {decision}."
            + (f" Note: {notes}" if notes else "")
        ),
        priority=4 if approve else 3,
        tags="white_check_mark" if approve else "x",
        settings=get_settings(),
    )
    return row


def employee_on_leave(db: Session, *, employee_id: UUID, work_date: date) -> bool:
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee_id,
            AttendanceRecord.work_date == work_date,
            AttendanceRecord.status == AttendanceRecordStatus.ON_LEAVE.value,
        )
    )
    if record:
        return True
    approved = db.scalar(
        select(LeaveRequest).where(
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.status == LeaveRequestStatus.APPROVED.value,
            LeaveRequest.start_date <= work_date,
            LeaveRequest.end_date >= work_date,
        )
    )
    return approved is not None
