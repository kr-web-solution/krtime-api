"""Shared response schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class MessageOut(BaseModel):
    reason_code: str = "ok"
    message: str


class TokenPairOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    user_id: UUID
    employee_id: UUID | None = None
    full_name: str
    # Returned for native mobile clients (cookie may be stripped by proxies).
    # Admin browser continues to use the httpOnly refresh cookie.
    refresh_token: str | None = None


class UserBriefOut(ORMModel):
    id: UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None
