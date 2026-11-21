"""Attendance corrections and month lock."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.api.deps import AdminUser, DbSession, SuperAdminUser
from app.schemas.corrections import (
    CorrectionCreate,
    CorrectionDecision,
    CorrectionOut,
    MonthLockRequest,
)
from app.services import correction_service

router = APIRouter()


@router.get("", response_model=list[CorrectionOut])
def list_corrections(
    db: DbSession,
    _: AdminUser,
    status: Annotated[str | None, Query()] = "pending",
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[CorrectionOut]:
    rows = correction_service.list_corrections(db, status=status, limit=limit)
    return [CorrectionOut.model_validate(r) for r in rows]


@router.post("", response_model=CorrectionOut, status_code=201)
def create_correction(
    payload: CorrectionCreate,
    db: DbSession,
    actor: AdminUser,
) -> CorrectionOut:
    row = correction_service.request_correction(
        db,
        attendance_record_id=payload.attendance_record_id,
        reason=payload.reason,
        proposed_check_in_at=payload.proposed_check_in_at,
        proposed_check_out_at=payload.proposed_check_out_at,
        actor=actor,
    )
    return CorrectionOut.model_validate(row)


@router.post("/{correction_id}/decide", response_model=CorrectionOut)
def decide_correction(
    correction_id: UUID,
    payload: CorrectionDecision,
    db: DbSession,
    actor: SuperAdminUser,
) -> CorrectionOut:
    row = correction_service.decide_correction(
        db,
        correction_id=correction_id,
        approve=payload.approve,
        notes=payload.notes,
        actor=actor,
    )
    return CorrectionOut.model_validate(row)


@router.post("/month-lock")
def month_lock(payload: MonthLockRequest, db: DbSession, actor: SuperAdminUser) -> dict:
    return correction_service.lock_month(db, year=payload.year, month=payload.month, actor=actor)
