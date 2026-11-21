"""Device registration and reset requests."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import DeviceStatus, Employee, RegisteredDevice, User
from app.schemas.devices import DeviceOut, DeviceRegisterRequest, DeviceResetRequest
from app.services.audit import write_audit
from app.services.crypto_keys import validate_ecdsa_p256_public_key_pem


def register_device(
    db: Session,
    employee: Employee,
    payload: DeviceRegisterRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> DeviceOut:
    pem = validate_ecdsa_p256_public_key_pem(payload.public_key_pem)

    active = db.scalars(
        select(RegisteredDevice).where(
            RegisteredDevice.employee_id == employee.id,
            RegisteredDevice.status.in_(
                [DeviceStatus.ACTIVE.value, DeviceStatus.PENDING.value]
            ),
        )
    ).all()
    for device in active:
        device.status = DeviceStatus.REVOKED.value
        device.revoked_at = datetime.now(UTC)
        db.add(device)

    device = RegisteredDevice(
        employee_id=employee.id,
        public_key_pem=pem,
        device_model=payload.device_model,
        os_version=payload.os_version,
        app_version=payload.app_version,
        # Phase 1: auto-activate for pilot simplicity; Phase 2 admin can require approve.
        status=DeviceStatus.ACTIVE.value,
        approved_at=datetime.now(UTC),
    )
    db.add(device)
    write_audit(
        db,
        actor_user_id=employee.user_id,
        action="device.register",
        entity_type="registered_device",
        entity_id=str(employee.id),
        after={"device_model": payload.device_model, "status": device.status},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(device)
    return DeviceOut.model_validate(device)


def request_device_reset(
    db: Session,
    employee: Employee,
    payload: DeviceResetRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> DeviceOut:
    device = db.scalar(
        select(RegisteredDevice)
        .where(
            RegisteredDevice.employee_id == employee.id,
            RegisteredDevice.status.in_(
                [DeviceStatus.ACTIVE.value, DeviceStatus.PENDING.value]
            ),
        )
        .order_by(RegisteredDevice.registered_at.desc())
    )
    if device is None:
        raise AppError("device_not_found", "No active device to reset", status_code=404)

    device.status = DeviceStatus.RESET_REQUESTED.value
    device.reset_requested_at = datetime.now(UTC)
    device.reset_reason = payload.reason
    db.add(device)
    write_audit(
        db,
        actor_user_id=employee.user_id,
        action="device.reset_request",
        entity_type="registered_device",
        entity_id=str(device.id),
        after={"reason": payload.reason},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    db.refresh(device)
    return DeviceOut.model_validate(device)


def list_devices_for_admin(db: Session) -> list[DeviceOut]:
    rows = db.scalars(select(RegisteredDevice).order_by(RegisteredDevice.registered_at.desc())).all()
    return [DeviceOut.model_validate(row) for row in rows]


def approve_device(db: Session, device_id, *, actor: User) -> DeviceOut:
    device = db.get(RegisteredDevice, device_id)
    if device is None:
        raise AppError("device_not_found", "Device not found", status_code=404)
    device.status = DeviceStatus.ACTIVE.value
    device.approved_at = datetime.now(UTC)
    device.approved_by_user_id = actor.id
    db.add(device)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="device.approve",
        entity_type="registered_device",
        entity_id=str(device.id),
    )
    db.commit()
    db.refresh(device)
    return DeviceOut.model_validate(device)


def revoke_device(db: Session, device_id, *, actor: User) -> DeviceOut:
    device = db.get(RegisteredDevice, device_id)
    if device is None:
        raise AppError("device_not_found", "Device not found", status_code=404)
    if device.status == DeviceStatus.REVOKED.value:
        raise AppError("device_revoked", "Device is already revoked", status_code=400)
    before = {"status": device.status}
    device.status = DeviceStatus.REVOKED.value
    device.revoked_at = datetime.now(UTC)
    db.add(device)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="device.revoke",
        entity_type="registered_device",
        entity_id=str(device.id),
        before=before,
        after={"status": DeviceStatus.REVOKED.value},
    )
    db.commit()
    db.refresh(device)
    return DeviceOut.model_validate(device)
