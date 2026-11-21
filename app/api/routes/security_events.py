"""Admin security events feed."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession
from app.models import SecurityEvent

router = APIRouter()


class SecurityEventOut(BaseModel):
    id: UUID
    employee_id: UUID | None
    user_id: UUID | None
    device_id: UUID | None
    event_type: str
    severity: str
    message: str
    details: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[SecurityEventOut])
def list_security_events(
    db: DbSession,
    _: AdminUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    severity: Annotated[str | None, Query()] = None,
    event_type: Annotated[str | None, Query()] = None,
) -> list[SecurityEventOut]:
    stmt = select(SecurityEvent).order_by(SecurityEvent.created_at.desc()).limit(limit)
    if severity:
        stmt = stmt.where(SecurityEvent.severity == severity)
    if event_type:
        stmt = stmt.where(SecurityEvent.event_type == event_type)
    return [SecurityEventOut.model_validate(r) for r in db.scalars(stmt).all()]
