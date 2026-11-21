"""Device registration endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import AdminUser, CurrentEmployee, DbSession, SuperAdminUser, client_meta
from app.core.config import get_settings
from app.core.errors import AppError
from app.schemas.devices import (
    DeviceOut,
    DeviceRegisterRequest,
    DeviceResetRequest,
    PushConfigOut,
    PushSubscribeOut,
    PushSubscribeRequest,
)
from app.services import device_service, notification_service

router = APIRouter()


@router.post("/register", response_model=DeviceOut, status_code=201)
def register_device(
    payload: DeviceRegisterRequest,
    request: Request,
    db: DbSession,
    employee: CurrentEmployee,
) -> DeviceOut:
    return device_service.register_device(
        db, employee, payload, **client_meta(request)
    )


@router.post("/reset-request", response_model=DeviceOut)
def reset_request(
    payload: DeviceResetRequest,
    request: Request,
    db: DbSession,
    employee: CurrentEmployee,
) -> DeviceOut:
    return device_service.request_device_reset(
        db, employee, payload, **client_meta(request)
    )


@router.get("/push-config", response_model=PushConfigOut)
def push_config(_: CurrentEmployee) -> PushConfigOut:
    settings = get_settings()
    return PushConfigOut(
        enabled=notification_service.push_enabled(settings),
        ntfy_public_url=notification_service.public_ntfy_url(settings),
        admin_topic=settings.ntfy_admin_topic,
    )


@router.post("/push-subscribe", response_model=PushSubscribeOut)
def push_subscribe(
    payload: PushSubscribeRequest,
    db: DbSession,
    employee: CurrentEmployee,
) -> PushSubscribeOut:
    try:
        row = notification_service.upsert_subscription(
            db,
            employee_id=employee.id,
            topic=payload.topic,
            endpoint_url=payload.endpoint_url,
            device_id=payload.device_id,
        )
    except ValueError as exc:
        raise AppError("invalid_topic", str(exc), status_code=400) from exc
    return PushSubscribeOut(
        id=row.id,
        topic=row.topic,
        endpoint_url=row.endpoint_url,
    )


@router.get("", response_model=list[DeviceOut])
def list_devices(db: DbSession, _: AdminUser) -> list[DeviceOut]:
    return device_service.list_devices_for_admin(db)


@router.post("/{device_id}/approve", response_model=DeviceOut)
def approve_device(device_id: UUID, db: DbSession, actor: SuperAdminUser) -> DeviceOut:
    return device_service.approve_device(db, device_id, actor=actor)
