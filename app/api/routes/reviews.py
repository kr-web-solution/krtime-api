"""PENDING_REVIEW attendance queue."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, SuperAdminUser
from app.core.errors import AppError
from app.models import (
    AttendanceEvent,
    AttendanceOutcome,
    AttendanceRecord,
    AttendanceRecordStatus,
    FaceVerificationAttempt,
)
from app.services.audit import write_audit

router = APIRouter()


class ReviewItem(BaseModel):
    event_id: UUID
    employee_id: UUID
    outcome: str
    reason_code: str | None
    face_similarity: float | None
    spoof_score: float | None
    server_timestamp: datetime
    review_photo_path: str | None
    review_photo_url: str | None = None
    attempt_id: UUID | None = None


class ReviewDecision(BaseModel):
    approve: bool
    reason: str = Field(min_length=3, max_length=1000)


@router.get("", response_model=list[ReviewItem])
def list_reviews(db: DbSession, _: AdminUser) -> list[ReviewItem]:
    events = db.scalars(
        select(AttendanceEvent)
        .where(AttendanceEvent.outcome == AttendanceOutcome.PENDING_REVIEW.value)
        .order_by(AttendanceEvent.created_at.desc())
        .limit(100)
    ).all()
    items: list[ReviewItem] = []
    for event in events:
        attempt = db.scalar(
            select(FaceVerificationAttempt)
            .where(FaceVerificationAttempt.attendance_event_id == event.id)
            .order_by(FaceVerificationAttempt.created_at.desc())
        )
        photo = attempt.review_photo_path if attempt else None
        items.append(
            ReviewItem(
                event_id=event.id,
                employee_id=event.employee_id,
                outcome=event.outcome,
                reason_code=event.reason_code,
                face_similarity=event.face_similarity,
                spoof_score=event.spoof_score,
                server_timestamp=event.server_timestamp,
                review_photo_path=photo,
                review_photo_url=f"/api/v1/admin/reviews/{event.id}/photo" if photo else None,
                attempt_id=attempt.id if attempt else None,
            )
        )
    return items


@router.get("/{event_id}/photo")
def review_photo(event_id: UUID, db: DbSession, _: AdminUser) -> FileResponse:
    attempt = db.scalar(
        select(FaceVerificationAttempt)
        .where(FaceVerificationAttempt.attendance_event_id == event_id)
        .order_by(FaceVerificationAttempt.created_at.desc())
    )
    if attempt is None or not attempt.review_photo_path:
        raise AppError("photo_not_found", "Review photo not found", status_code=404)
    path = Path(attempt.review_photo_path)
    if not path.is_file():
        raise AppError("photo_missing", "Review photo file missing on disk", status_code=404)
    return FileResponse(path, media_type="image/jpeg", filename=f"{event_id}.jpg")


@router.post("/{event_id}/decide")
def decide_review(
    event_id: UUID,
    payload: ReviewDecision,
    db: DbSession,
    actor: SuperAdminUser,
) -> dict:
    """Events stay append-only. Sync daily summary + attempt outcome; audit decision."""
    event = db.get(AttendanceEvent, event_id)
    if event is None:
        raise AppError("event_not_found", "Attendance event not found", status_code=404)
    if event.outcome != AttendanceOutcome.PENDING_REVIEW.value:
        raise AppError("not_pending", "Event is not pending review", status_code=400)

    write_audit(
        db,
        actor_user_id=actor.id,
        action="review.decide",
        entity_type="attendance_event",
        entity_id=str(event_id),
        after={
            "approve": payload.approve,
            "reason": payload.reason,
            "decided_at": datetime.now(UTC).isoformat(),
        },
    )
    attempt = db.scalar(
        select(FaceVerificationAttempt).where(
            FaceVerificationAttempt.attendance_event_id == event_id
        )
    )
    if attempt:
        attempt.outcome = "APPROVED" if payload.approve else "REJECTED"
        attempt.reason_code = "manual_review"
        db.add(attempt)

    # Sync mutable daily summary (events untouched).
    record = db.scalar(
        select(AttendanceRecord).where(
            (AttendanceRecord.check_in_event_id == event_id)
            | (AttendanceRecord.check_out_event_id == event_id)
        )
    )
    if record is not None and not record.month_locked:
        if payload.approve:
            if record.check_out_at:
                record.status = AttendanceRecordStatus.COMPLETE.value
            elif record.check_in_at:
                record.status = AttendanceRecordStatus.OPEN.value
        else:
            if record.check_in_event_id == event_id and record.check_out_at is None:
                record.status = AttendanceRecordStatus.ABSENT.value
                record.check_in_at = None
            elif record.check_out_event_id == event_id:
                record.check_out_at = None
                record.check_out_event_id = None
                record.status = AttendanceRecordStatus.MISSING_CHECKOUT.value
        db.add(record)

    db.commit()
    return {
        "reason_code": "ok",
        "message": "Review decision recorded (events remain append-only)",
        "approve": payload.approve,
    }
