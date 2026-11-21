"""Attendance corrections, month lock, forgotten check-out job."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.database import SessionLocal
from app.core.errors import AppError
from app.models import (
    AttendanceCorrection,
    AttendanceEvent,
    AttendanceEventType,
    AttendanceOutcome,
    AttendanceRecord,
    AttendanceRecordStatus,
    CorrectionStatus,
    Shift,
    User,
)
from app.services import shift_service
from app.services.audit import write_audit

logger = logging.getLogger("attendguard.corrections")


def list_corrections(db: Session, *, status: str | None = None, limit: int = 100) -> list[AttendanceCorrection]:
    stmt = select(AttendanceCorrection).order_by(AttendanceCorrection.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(AttendanceCorrection.status == status)
    return list(db.scalars(stmt).all())


def request_correction(
    db: Session,
    *,
    attendance_record_id: UUID,
    reason: str,
    proposed_check_in_at: datetime | None,
    proposed_check_out_at: datetime | None,
    actor: User,
) -> AttendanceCorrection:
    record = db.get(AttendanceRecord, attendance_record_id)
    if record is None:
        raise AppError("record_not_found", "Attendance record not found", status_code=404)
    if record.month_locked:
        raise AppError("month_locked", "This month is locked; corrections are closed", status_code=400)
    if not proposed_check_in_at and not proposed_check_out_at:
        raise AppError("invalid_correction", "Provide proposed check-in and/or check-out", status_code=400)

    pending = db.scalar(
        select(AttendanceCorrection).where(
            AttendanceCorrection.attendance_record_id == attendance_record_id,
            AttendanceCorrection.status == CorrectionStatus.PENDING.value,
        )
    )
    if pending:
        raise AppError("correction_pending", "A pending correction already exists", status_code=409)

    row = AttendanceCorrection(
        attendance_record_id=attendance_record_id,
        requested_by_user_id=actor.id,
        reason=reason.strip(),
        proposed_check_in_at=proposed_check_in_at,
        proposed_check_out_at=proposed_check_out_at,
        status=CorrectionStatus.PENDING.value,
    )
    db.add(row)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="correction.request",
        entity_type="attendance_correction",
        entity_id=str(attendance_record_id),
        after={"reason": reason},
    )
    db.commit()
    db.refresh(row)
    return row


def decide_correction(
    db: Session,
    *,
    correction_id: UUID,
    approve: bool,
    notes: str | None,
    actor: User,
) -> AttendanceCorrection:
    row = db.get(AttendanceCorrection, correction_id)
    if row is None:
        raise AppError("correction_not_found", "Correction not found", status_code=404)
    if row.status != CorrectionStatus.PENDING.value:
        raise AppError("correction_not_pending", "Correction is not pending", status_code=400)

    record = db.get(AttendanceRecord, row.attendance_record_id)
    if record is None:
        raise AppError("record_not_found", "Attendance record not found", status_code=404)
    if record.month_locked:
        raise AppError("month_locked", "This month is locked", status_code=400)

    if not approve:
        row.status = CorrectionStatus.REJECTED.value
        db.add(row)
        write_audit(
            db,
            actor_user_id=actor.id,
            action="correction.reject",
            entity_type="attendance_correction",
            entity_id=str(correction_id),
            after={"notes": notes},
        )
        db.commit()
        db.refresh(row)
        return row

    # Approve: append correction event + mutate daily summary only.
    event = AttendanceEvent(
        employee_id=record.employee_id,
        location_id=record.location_id,
        event_type=AttendanceEventType.CHECK_OUT.value
        if row.proposed_check_out_at and not row.proposed_check_in_at
        else AttendanceEventType.CHECK_IN.value,
        outcome=AttendanceOutcome.ACCEPTED.value,
        reason_code="manual_correction",
        server_timestamp=datetime.now(UTC),
        open_event_id=record.check_in_event_id,
        shift_assignment_id=record.shift_assignment_id,
        idempotency_key=f"correction:{correction_id}:{uuid4().hex[:8]}",
        evidence={
            "correction_id": str(correction_id),
            "proposed_check_in_at": row.proposed_check_in_at.isoformat() if row.proposed_check_in_at else None,
            "proposed_check_out_at": row.proposed_check_out_at.isoformat() if row.proposed_check_out_at else None,
            "notes": notes,
        },
    )
    db.add(event)
    db.flush()

    if row.proposed_check_in_at:
        record.check_in_at = row.proposed_check_in_at
        record.check_in_event_id = record.check_in_event_id or event.id
    if row.proposed_check_out_at:
        record.check_out_at = row.proposed_check_out_at
        record.check_out_event_id = event.id
    if record.check_in_at and record.check_out_at:
        delta = record.check_out_at - record.check_in_at
        record.worked_minutes = max(int(delta.total_seconds() // 60), 0)
        record.status = AttendanceRecordStatus.CORRECTED.value
    elif record.check_in_at and not record.check_out_at:
        record.status = AttendanceRecordStatus.OPEN.value
    db.add(record)

    row.status = CorrectionStatus.APPROVED.value
    row.linked_event_id = event.id
    db.add(row)

    write_audit(
        db,
        actor_user_id=actor.id,
        action="correction.approve",
        entity_type="attendance_correction",
        entity_id=str(correction_id),
        after={
            "notes": notes,
            "linked_event_id": str(event.id),
            "record_status": record.status,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def lock_month(db: Session, *, year: int, month: int, actor: User) -> dict:
    if month < 1 or month > 12:
        raise AppError("invalid_month", "month must be 1–12", status_code=400)
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)

    result = db.execute(
        update(AttendanceRecord)
        .where(
            AttendanceRecord.work_date >= start,
            AttendanceRecord.work_date < end,
            AttendanceRecord.month_locked.is_(False),
        )
        .values(month_locked=True)
    )
    write_audit(
        db,
        actor_user_id=actor.id,
        action="month.lock",
        entity_type="attendance_records",
        entity_id=f"{year:04d}-{month:02d}",
        after={"rows": result.rowcount},
    )
    db.commit()
    return {"year": year, "month": month, "locked_rows": result.rowcount}


def flag_forgotten_checkouts(db: Session, settings: Settings) -> int:
    """Mark open records whose shift ended as missing_checkout."""
    try:
        tz = ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    today = now.date()
    yesterday = today - timedelta(days=1)

    open_rows = db.scalars(
        select(AttendanceRecord).where(
            AttendanceRecord.status == AttendanceRecordStatus.OPEN.value,
            AttendanceRecord.work_date.in_([today, yesterday]),
            AttendanceRecord.check_out_at.is_(None),
        )
    ).all()

    flagged = 0
    for record in open_rows:
        assignment = None
        if record.shift_assignment_id:
            assignment = shift_service.current_assignment(db, record.employee_id, on_date=record.work_date)
        shift = None
        if assignment:
            shift = db.get(Shift, assignment.shift_id)
        if shift is None:
            # Without shift, flag yesterday's open rows after midnight+2h business time.
            if record.work_date < today and now.hour >= 2:
                record.status = AttendanceRecordStatus.MISSING_CHECKOUT.value
                db.add(record)
                flagged += 1
            continue
        _start, end = shift_service.shift_bounds(shift, record.work_date, settings=settings)
        grace_end = end + timedelta(minutes=max(shift.grace_early_minutes, 30))
        if now >= grace_end:
            record.status = AttendanceRecordStatus.MISSING_CHECKOUT.value
            db.add(record)
            flagged += 1

    if flagged:
        db.commit()
        logger.info("Flagged %s forgotten check-outs", flagged)
    return flagged


def run_forgotten_checkout_job() -> None:
    settings = None
    from app.core.config import get_settings

    settings = get_settings()
    db = SessionLocal()
    try:
        flag_forgotten_checkouts(db, settings)
    except Exception:  # noqa: BLE001
        logger.exception("forgotten checkout job failed")
        db.rollback()
    finally:
        db.close()
