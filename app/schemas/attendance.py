"""Attendance challenge and submission schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class ChallengeRequest(BaseModel):
    device_id: UUID
    purpose: str = Field(pattern="^(check_in|check_out)$")


class ChallengeOut(BaseModel):
    challenge_id: UUID
    nonce: str
    purpose: str
    expires_at: datetime
    expires_in: int


class GpsSampleIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=5000)
    age_ms: int = Field(ge=0, le=60_000)
    is_mocked: bool = False


class AttendanceSubmitRequest(BaseModel):
    challenge_id: UUID
    device_id: UUID
    location_id: UUID
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=5000)
    fix_age_ms: int = Field(ge=0, le=60_000)
    is_mocked: bool = False
    sample_count: int = Field(ge=1, le=100)
    samples: list[GpsSampleIn] = Field(default_factory=list, max_length=100)
    qr_token: str = Field(min_length=8, max_length=64)
    image_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$")
    # JPEG as base64 (about 50–100 KB). Raw bytes are deleted after verification;
    # only PENDING_REVIEW keeps a short-retention review copy on disk.
    image_base64: str | None = Field(default=None, max_length=400_000)
    signature_b64: str = Field(min_length=40, max_length=2000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    liveness_passed: bool | None = None
    client_app_version: str | None = Field(default=None, max_length=32)


class AttendanceSubmitOut(BaseModel):
    outcome: str
    reason_code: str | None = None
    message: str
    event_id: UUID
    server_timestamp: datetime
    distance_m: float | None = None


class TodayStatusOut(BaseModel):
    work_date: str
    status: str | None = None
    check_in_at: datetime | None = None
    check_out_at: datetime | None = None
    can_check_in: bool
    can_check_out: bool
    open_event_id: UUID | None = None
    location_id: UUID | None = None


class AttendanceHistoryItem(ORMModel):
    id: UUID
    work_date: str
    status: str
    check_in_at: datetime | None
    check_out_at: datetime | None
    worked_minutes: int | None
    location_id: UUID | None
    is_late: bool
    is_early_departure: bool


class PresencePingRequest(BaseModel):
    device_id: UUID
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    accuracy_m: float = Field(gt=0, le=5000)
    fix_age_ms: int = Field(ge=0, le=120_000)
    is_mocked: bool = False


class PresencePingOut(BaseModel):
    status: str  # ignored | inside | outside | mocked
    distance_m: float | None = None
    alerted: bool = False
    location_id: UUID | None = None
    message: str
