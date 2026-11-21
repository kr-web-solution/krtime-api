"""Face enrollments, consent, verification attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixins import TimestampMixin, UUIDPrimaryKeyMixin


class FaceEnrollment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "face_enrollments"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    # AES-256-GCM: nonce || ciphertext || tag (opaque bytes)
    encrypted_embedding: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    embedding_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BiometricConsentRecord(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "biometric_consent_records"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    consent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    consented: Mapped[bool] = mapped_column(Boolean, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class FaceVerificationAttempt(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "face_verification_attempts"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    attendance_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    spoof_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    review_photo_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    review_photo_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
