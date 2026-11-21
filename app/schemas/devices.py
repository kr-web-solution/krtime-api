"""Device registration schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class DeviceRegisterRequest(BaseModel):
    public_key_pem: str = Field(min_length=100, max_length=4000)
    device_model: str | None = Field(default=None, max_length=120)
    os_version: str | None = Field(default=None, max_length=64)
    app_version: str | None = Field(default=None, max_length=32)


class DeviceResetRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class DeviceOut(ORMModel):
    id: UUID
    employee_id: UUID
    device_model: str | None
    os_version: str | None
    app_version: str | None
    status: str
    registered_at: datetime
    approved_at: datetime | None
    last_seen_at: datetime | None


class PushSubscribeRequest(BaseModel):
    topic: str = Field(min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_-]+$")
    endpoint_url: str | None = Field(default=None, max_length=2000)
    device_id: UUID | None = None


class PushSubscribeOut(BaseModel):
    id: UUID
    topic: str
    endpoint_url: str | None = None


class PushConfigOut(BaseModel):
    enabled: bool
    ntfy_public_url: str
    admin_topic: str
