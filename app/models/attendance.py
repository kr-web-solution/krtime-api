"""Attendance challenges, append-only events, daily records, corrections."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.enums import (
    ApprovalStatus,
    AttendanceEventType,
    AttendanceOutcome,
    AttendanceRecordStatus,
    CorrectionStatus,
)


class AttendanceChallenge(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "attendance_challenges"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registered_devices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    nonce: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)  # check_in | check_out
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AttendanceEvent(Base, UUIDPrimaryKeyMixin):
    """Append-only. Application code must never UPDATE or DELETE rows."""

    __tablename__ = "attendance_events"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_attendance_events_idempotency"),
        Index("ix_attendance_events_employee_created", "employee_id", "created_at"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registered_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    challenge_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_challenges.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default=AttendanceOutcome.REJECTED.value)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    qr_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    face_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    spoof_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    open_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class AttendanceRecord(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Daily summary row (mutable summary; events remain append-only)."""

    __tablename__ = "attendance_records"
    __table_args__ = (
        UniqueConstraint("employee_id", "work_date", name="uq_attendance_record_day"),
        Index(
            "uq_open_checkin_per_employee_shift",
            "employee_id",
            "shift_assignment_id",
            unique=True,
            postgresql_where=text("status = 'open' AND shift_assignment_id IS NOT NULL"),
        ),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    shift_assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shift_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_in_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_out_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worked_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AttendanceRecordStatus.OPEN.value,
    )
    is_late: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_early_departure: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    month_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Last presence-ping snapshot (updated while status=open)
    last_presence_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_presence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_presence_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_presence_lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_presence_lng: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_presence_accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)


class AttendanceCorrection(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_corrections"

    attendance_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    proposed_check_in_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    proposed_check_out_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    linked_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("attendance_events.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CorrectionStatus.PENDING.value,
    )


class AttendanceApproval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "attendance_approvals"

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=AttendanceEventType.CHECK_IN.value,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=ApprovalStatus.PENDING.value,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
