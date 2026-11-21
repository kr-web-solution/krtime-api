"""Biometrics schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ConsentRequest(BaseModel):
    consented: bool = True


class ConsentOut(BaseModel):
    consent_version: str
    consented: bool
    recorded_at: str


class BiometricsStatusOut(BaseModel):
    consent_required_version: str
    consent_given: bool
    enrolled: bool
    model_version: str | None = None
    frame_count: int = 0
    enrolled_at: str | None = None


class EnrollRequest(BaseModel):
    images_base64: list[str] = Field(min_length=3, max_length=5)
