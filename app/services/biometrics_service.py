"""Face enrollment, consent, and admin re-enroll/delete."""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.models import BiometricConsentRecord, Employee, FaceEnrollment, User
from app.services.audit import write_audit
from app.services.embedding_crypto import encrypt_embedding, packing_float32
from app.services.face_engine import MODEL_VERSION, FaceEngineUnavailable, get_face_engine, with_face_slot


CONSENT_VERSION = "2026-03-face-v1"


def record_consent(
    db: Session,
    *,
    employee: Employee,
    consented: bool,
    ip_address: str | None,
    user_agent: str | None,
) -> BiometricConsentRecord:
    row = BiometricConsentRecord(
        employee_id=employee.id,
        consent_version=CONSENT_VERSION,
        consented=consented,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def latest_consent(db: Session, employee_id: UUID) -> BiometricConsentRecord | None:
    return db.scalar(
        select(BiometricConsentRecord)
        .where(BiometricConsentRecord.employee_id == employee_id)
        .order_by(BiometricConsentRecord.recorded_at.desc())
    )


def enrollment_status(db: Session, employee_id: UUID) -> dict:
    consent = latest_consent(db, employee_id)
    face = db.scalar(
        select(FaceEnrollment).where(
            FaceEnrollment.employee_id == employee_id,
            FaceEnrollment.is_active.is_(True),
            FaceEnrollment.deleted_at.is_(None),
        )
    )
    return {
        "consent_required_version": CONSENT_VERSION,
        "consent_given": bool(consent and consent.consented and consent.consent_version == CONSENT_VERSION),
        "enrolled": face is not None,
        "model_version": face.model_version if face else None,
        "frame_count": face.frame_count if face else 0,
        "enrolled_at": face.enrolled_at.isoformat() if face else None,
    }


def enroll_face(
    db: Session,
    *,
    employee: Employee,
    images_base64: list[str],
    settings: Settings,
    actor_user_id: UUID | None = None,
) -> FaceEnrollment:
    consent = latest_consent(db, employee.id)
    if not consent or not consent.consented or consent.consent_version != CONSENT_VERSION:
        raise AppError("consent_required", "Biometric consent is required before enrollment", status_code=403)
    if len(images_base64) < 3 or len(images_base64) > 5:
        raise AppError("invalid_frame_count", "Provide 3 to 5 enrollment frames", status_code=400)

    embeddings: list[list[float]] = []

    def _extract() -> None:
        engine = get_face_engine()
        for raw in images_base64:
            try:
                image_bytes = base64.b64decode(raw, validate=False)
            except Exception as exc:  # noqa: BLE001
                raise AppError("invalid_image", "Frame is not valid base64") from exc
            try:
                detected = engine.detect_and_embed(image_bytes)
            except FaceEngineUnavailable as exc:
                raise AppError(
                    "face_engine_unavailable",
                    "Face models are not installed on the server",
                    status_code=503,
                ) from exc
            except ValueError as exc:
                raise AppError("face_detect_failed", f"Could not detect face: {exc}") from exc
            embeddings.append(detected.embedding)

    try:
        with_face_slot(_extract)
    except TimeoutError as exc:
        raise AppError("face_queue_busy", "Face enrollment queue is busy", status_code=503) from exc

    engine = get_face_engine()
    avg = engine.average_embeddings(embeddings)
    packed = packing_float32(avg)
    nonce, ciphertext = encrypt_embedding(settings, packed)

    existing = db.scalar(select(FaceEnrollment).where(FaceEnrollment.employee_id == employee.id))
    if existing:
        existing.is_active = False
        existing.deleted_at = datetime.now(UTC)
        db.add(existing)

    row = FaceEnrollment(
        employee_id=employee.id,
        encrypted_embedding=ciphertext,
        embedding_nonce=nonce,
        model_version=MODEL_VERSION,
        frame_count=len(embeddings),
        is_active=True,
        enrolled_at=datetime.now(UTC),
    )
    db.add(row)
    write_audit(
        db,
        actor_user_id=actor_user_id or employee.user_id,
        action="biometrics.enroll",
        entity_type="face_enrollment",
        entity_id=str(employee.id),
        after={"model_version": MODEL_VERSION, "frame_count": len(embeddings)},
    )
    db.commit()
    db.refresh(row)
    return row


def delete_enrollment(
    db: Session,
    *,
    employee_id: UUID,
    actor: User,
) -> None:
    row = db.scalar(
        select(FaceEnrollment).where(
            FaceEnrollment.employee_id == employee_id,
            FaceEnrollment.is_active.is_(True),
        )
    )
    if row is None:
        raise AppError("face_not_enrolled", "No active enrollment", status_code=404)
    row.is_active = False
    row.deleted_at = datetime.now(UTC)
    # Wipe ciphertext bytes from row for deletion support (keep audit trail via soft delete flag)
    row.encrypted_embedding = b""
    row.embedding_nonce = b""
    db.add(row)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="biometrics.delete",
        entity_type="face_enrollment",
        entity_id=str(employee_id),
    )
    db.commit()
