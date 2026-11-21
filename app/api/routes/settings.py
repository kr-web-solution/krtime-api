"""System settings (face thresholds, etc.)."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import AdminUser, DbSession, SuperAdminUser
from app.core.errors import AppError
from app.models import SystemSetting
from app.services.audit import write_audit

router = APIRouter()


class SettingOut(BaseModel):
    key: str
    value: dict
    description: str | None = None


class SettingUpdate(BaseModel):
    value: dict = Field(default_factory=dict)


@router.get("", response_model=list[SettingOut])
def list_settings(db: DbSession, _: AdminUser) -> list[SettingOut]:
    rows = db.scalars(select(SystemSetting).order_by(SystemSetting.key)).all()
    return [
        SettingOut(key=r.key, value=r.value, description=r.description) for r in rows
    ]


@router.patch("/{key:path}", response_model=SettingOut)
def update_setting(
    key: str,
    payload: SettingUpdate,
    db: DbSession,
    actor: SuperAdminUser,
) -> SettingOut:
    row = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
    if row is None:
        raise AppError("setting_not_found", "Setting not found", status_code=404)
    before = dict(row.value)
    row.value = payload.value
    row.updated_by_user_id = actor.id
    db.add(row)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="settings.update",
        entity_type="system_setting",
        entity_id=key,
        before=before,
        after=payload.value,
    )
    db.commit()
    db.refresh(row)
    return SettingOut(key=row.key, value=row.value, description=row.description)
