"""Face verification against stored AES-GCM embeddings."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import FaceEnrollment, SystemSetting
from app.services.embedding_crypto import decrypt_embedding, unpacking_float32
from app.services.face_engine import (
    FaceEngineUnavailable,
    get_face_engine,
    load_thresholds,
    with_face_slot,
)

logger = logging.getLogger("attendguard.face")


@dataclass
class FaceCheckResult:
    passed: bool
    pending_review: bool
    similarity: float | None
    spoof_score: float | None
    reason_code: str | None
    notes: str
    review_image_bytes: bytes | None = None


def _settings_map(db: Session) -> dict[str, dict]:
    rows = db.scalars(select(SystemSetting)).all()
    return {r.key: r.value for r in rows}


class StoredEmbeddingFaceVerifier:
    def __init__(self, db: Session, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    def verify(
        self,
        *,
        image_bytes: bytes,
        employee_id: str,
        liveness_passed: bool | None,
    ) -> FaceCheckResult:
        if not image_bytes:
            return FaceCheckResult(
                passed=False,
                pending_review=False,
                similarity=None,
                spoof_score=None,
                reason_code="face_image_missing",
                notes="No face image provided",
            )

        enrollment = self.db.scalar(
            select(FaceEnrollment).where(
                FaceEnrollment.employee_id == UUID(employee_id),
                FaceEnrollment.is_active.is_(True),
                FaceEnrollment.deleted_at.is_(None),
            )
        )
        if enrollment is None:
            return FaceCheckResult(
                passed=False,
                pending_review=False,
                similarity=None,
                spoof_score=None,
                reason_code="face_not_enrolled",
                notes="No active face enrollment",
            )

        thresholds = load_thresholds(self.settings, _settings_map(self.db))

        def _run() -> FaceCheckResult:
            engine = get_face_engine()
            try:
                detected = engine.detect_and_embed(image_bytes)
            except FaceEngineUnavailable:
                # Honest fallback: if models missing in this environment, reject with clear code.
                return FaceCheckResult(
                    passed=False,
                    pending_review=False,
                    similarity=None,
                    spoof_score=None,
                    reason_code="face_engine_unavailable",
                    notes="Face models not installed on server",
                )
            except ValueError as exc:
                code = str(exc)
                return FaceCheckResult(
                    passed=False,
                    pending_review=False,
                    similarity=None,
                    spoof_score=None,
                    reason_code=code if code in {"no_face", "invalid_image"} else "face_detect_failed",
                    notes=code,
                )

            if liveness_passed is False:
                return FaceCheckResult(
                    passed=False,
                    pending_review=False,
                    similarity=None,
                    spoof_score=detected.spoof_score,
                    reason_code="liveness_failed",
                    notes="Phone active-liveness reported failure",
                )

            if detected.spoof_score < thresholds["spoof_min"]:
                return FaceCheckResult(
                    passed=False,
                    pending_review=True,
                    similarity=None,
                    spoof_score=detected.spoof_score,
                    reason_code="spoof_suspect",
                    notes="Low anti-spoof/quality score",
                    review_image_bytes=image_bytes,
                )

            plain = decrypt_embedding(
                self.settings,
                nonce=enrollment.embedding_nonce,
                ciphertext=enrollment.encrypted_embedding,
            )
            stored = unpacking_float32(plain)
            similarity = engine.cosine_similarity(stored, detected.embedding)
            match = thresholds["match"]
            band = thresholds["band"]

            if similarity >= match:
                return FaceCheckResult(
                    passed=True,
                    pending_review=False,
                    similarity=similarity,
                    spoof_score=detected.spoof_score,
                    reason_code=None,
                    notes=f"match ok model={enrollment.model_version}",
                )
            if similarity >= (match - band):
                return FaceCheckResult(
                    passed=True,
                    pending_review=True,
                    similarity=similarity,
                    spoof_score=detected.spoof_score,
                    reason_code="face_borderline",
                    notes="Borderline match — pending review",
                    review_image_bytes=image_bytes,
                )
            return FaceCheckResult(
                passed=False,
                pending_review=False,
                similarity=similarity,
                spoof_score=detected.spoof_score,
                reason_code="face_mismatch",
                notes="Similarity below threshold",
            )

        try:
            return with_face_slot(_run)
        except TimeoutError:
            return FaceCheckResult(
                passed=False,
                pending_review=False,
                similarity=None,
                spoof_score=None,
                reason_code="face_queue_busy",
                notes="Face verification queue busy",
            )
