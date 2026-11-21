"""Biometric consent and face enrollment."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request

from app.api.deps import CurrentEmployee, DbSession, SuperAdminUser, client_meta
from app.core.config import Settings, get_settings
from app.schemas.biometrics import (
    BiometricsStatusOut,
    ConsentOut,
    ConsentRequest,
    EnrollRequest,
)
from app.schemas.common import MessageOut
from app.services import biometrics_service

router = APIRouter()


@router.get("/status", response_model=BiometricsStatusOut)
def status(db: DbSession, employee: CurrentEmployee) -> BiometricsStatusOut:
    return BiometricsStatusOut(**biometrics_service.enrollment_status(db, employee.id))


@router.post("/consent", response_model=ConsentOut)
def consent(
    payload: ConsentRequest,
    request: Request,
    db: DbSession,
    employee: CurrentEmployee,
) -> ConsentOut:
    meta = client_meta(request)
    row = biometrics_service.record_consent(
        db,
        employee=employee,
        consented=payload.consented,
        ip_address=meta.get("ip_address"),
        user_agent=meta.get("user_agent"),
    )
    return ConsentOut(
        consent_version=row.consent_version,
        consented=row.consented,
        recorded_at=row.recorded_at.isoformat(),
    )


@router.post("/enroll", response_model=BiometricsStatusOut)
def enroll(
    payload: EnrollRequest,
    db: DbSession,
    employee: CurrentEmployee,
    settings: Annotated[Settings, Depends(get_settings)],
) -> BiometricsStatusOut:
    biometrics_service.enroll_face(
        db,
        employee=employee,
        images_base64=payload.images_base64,
        settings=settings,
    )
    return BiometricsStatusOut(**biometrics_service.enrollment_status(db, employee.id))


@router.delete("/employees/{employee_id}", response_model=MessageOut)
def admin_delete_enrollment(
    employee_id: UUID,
    db: DbSession,
    actor: SuperAdminUser,
) -> MessageOut:
    biometrics_service.delete_enrollment(db, employee_id=employee_id, actor=actor)
    return MessageOut(message="Face enrollment deleted")
