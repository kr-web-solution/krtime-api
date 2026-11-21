"""Employee attendance endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from sqlalchemy.orm import Session

from fastapi import Request

from app.api.deps import CurrentEmployee, DbSession, client_meta
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models import AttendanceChallenge
from app.schemas.attendance import (
    AttendanceHistoryItem,
    AttendanceSubmitOut,
    AttendanceSubmitRequest,
    ChallengeOut,
    ChallengeRequest,
    PresencePingOut,
    PresencePingRequest,
    TodayStatusOut,
)
from app.services import attendance_service
from app.services.rate_limit import check_rate_limit

router = APIRouter()


def _assert_purpose(db: Session, challenge_id, expected: str) -> None:
    challenge = db.get(AttendanceChallenge, challenge_id)
    if challenge is None:
        raise AppError("challenge_not_found", "Attendance challenge not found", status_code=404)
    if challenge.purpose != expected:
        raise AppError(
            "challenge_purpose_mismatch",
            f"Challenge purpose must be {expected}",
            status_code=400,
        )


@router.post("/challenge", response_model=ChallengeOut)
def create_challenge(
    payload: ChallengeRequest,
    request: Request,
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> ChallengeOut:
    meta = client_meta(request)
    ip = meta.get("ip_address") or "unknown"
    check_rate_limit(
        db,
        bucket_key=f"attendance:{employee.id}:{ip}",
        limit=settings.attendance_rate_limit,
        window_seconds=settings.attendance_rate_window_seconds,
    )
    return attendance_service.create_challenge(
        db,
        employee=employee,
        device_id=payload.device_id,
        purpose=payload.purpose,
        settings=settings,
    )


@router.post("/check-in", response_model=AttendanceSubmitOut)
def check_in(
    payload: AttendanceSubmitRequest,
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AttendanceSubmitOut:
    _assert_purpose(db, payload.challenge_id, "check_in")
    return attendance_service.submit_attendance(
        db, employee=employee, payload=payload, settings=settings, image_bytes=b""
    )


@router.post("/check-out", response_model=AttendanceSubmitOut)
def check_out(
    payload: AttendanceSubmitRequest,
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AttendanceSubmitOut:
    _assert_purpose(db, payload.challenge_id, "check_out")
    return attendance_service.submit_attendance(
        db, employee=employee, payload=payload, settings=settings, image_bytes=b""
    )


@router.get("/today", response_model=TodayStatusOut)
def today(
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TodayStatusOut:
    return attendance_service.today_status(db, employee=employee, settings=settings)


@router.post("/presence-ping", response_model=PresencePingOut)
def presence_ping(
    payload: PresencePingRequest,
    request: Request,
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> PresencePingOut:
    meta = client_meta(request)
    ip = meta.get("ip_address") or "unknown"
    check_rate_limit(
        db,
        bucket_key=f"presence:{employee.id}:{ip}",
        limit=settings.attendance_rate_limit,
        window_seconds=settings.attendance_rate_window_seconds,
    )
    return attendance_service.presence_ping(
        db, employee=employee, payload=payload, settings=settings
    )


@router.get("/history", response_model=list[AttendanceHistoryItem])
def attendance_history(
    db: DbSession,
    employee: CurrentEmployee,
    limit: Annotated[int, Query(ge=1, le=90)] = 30,
) -> list[AttendanceHistoryItem]:
    rows = attendance_service.history(db, employee=employee, limit=limit)
    return [AttendanceHistoryItem.model_validate(r) for r in rows]
