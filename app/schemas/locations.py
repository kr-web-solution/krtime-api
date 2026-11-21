"""Location schemas."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class LocationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    slug: str = Field(min_length=2, max_length=80, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    radius_m: int = Field(default=30, ge=5, le=500)
    notes: str | None = Field(default=None, max_length=2000)
    active: bool = True


class LocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int | None = Field(default=None, ge=5, le=500)
    notes: str | None = Field(default=None, max_length=2000)
    active: bool | None = None
    rotate_qr_secret: bool = False


class LocationOut(ORMModel):
    id: UUID
    name: str
    slug: str
    lat: float
    lng: float
    radius_m: int
    notes: str | None
    active: bool
    created_at: datetime
    updated_at: datetime
    # qr_secret intentionally omitted from list/detail for non-super-admin use;
    # admin tablet link uses a separate signed endpoint in Phase 2.
