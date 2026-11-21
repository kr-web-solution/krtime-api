"""Authentication flows: login, refresh, logout, enroll-with-code."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    needs_rehash,
    verify_password,
)
from app.models import Employee, EnrollmentCode, EnrollmentCodeStatus, User, UserSession
from app.schemas.common import TokenPairOut
from app.services.audit import write_audit


def _employee_id_for_user(db: Session, user: User) -> UUID | None:
    employee = db.scalar(select(Employee.id).where(Employee.user_id == user.id))
    return employee


def build_token_pair(db: Session, user: User, settings: Settings) -> tuple[TokenPairOut, str]:
    employee_id = _employee_id_for_user(db, user)
    access = create_access_token(subject=user.id, role=user.role, employee_id=employee_id)
    refresh_raw = generate_refresh_token()
    session = UserSession(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh_raw),
        expires_at=datetime.now(UTC) + timedelta(days=settings.jwt_refresh_token_days),
    )
    db.add(session)
    db.flush()
    out = TokenPairOut(
        access_token=access,
        expires_in=settings.jwt_access_token_minutes * 60,
        role=user.role,
        user_id=user.id,
        employee_id=employee_id,
        full_name=user.full_name,
        refresh_token=refresh_raw,
    )
    return out, refresh_raw


def _assert_not_locked(user: User) -> None:
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise AppError(
            "account_locked",
            "Account temporarily locked due to failed logins",
            status_code=423,
            details={"locked_until": user.locked_until.isoformat()},
        )


def login(
    db: Session,
    *,
    email: str,
    password: str,
    settings: Settings,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[TokenPairOut, str]:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if user is None:
        raise AppError("invalid_credentials", "Invalid email or password", status_code=401)

    _assert_not_locked(user)

    if not verify_password(password, user.password_hash):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_attempts:
            user.locked_until = datetime.now(UTC) + timedelta(minutes=settings.login_lockout_minutes)
            user.failed_login_count = 0
        db.add(user)
        db.commit()
        raise AppError("invalid_credentials", "Invalid email or password", status_code=401)

    if not user.is_active:
        raise AppError("account_disabled", "Account is disabled", status_code=403)

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(UTC)
    db.add(user)

    tokens, refresh_raw = build_token_pair(db, user, settings)
    write_audit(
        db,
        actor_user_id=user.id,
        action="auth.login",
        entity_type="user",
        entity_id=str(user.id),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return tokens, refresh_raw


def refresh_session(
    db: Session,
    *,
    refresh_raw: str,
    settings: Settings,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[TokenPairOut, str]:
    token_hash = hash_token(refresh_raw)
    session = db.scalar(
        select(UserSession)
        .options(joinedload(UserSession.user))
        .where(UserSession.refresh_token_hash == token_hash)
    )
    if session is None or session.revoked_at is not None:
        raise AppError("invalid_refresh", "Refresh token is invalid", status_code=401)
    if session.expires_at <= datetime.now(UTC):
        raise AppError("refresh_expired", "Refresh token has expired", status_code=401)

    user = session.user
    if not user.is_active:
        raise AppError("account_disabled", "Account is disabled", status_code=403)

    session.revoked_at = datetime.now(UTC)
    db.add(session)

    tokens, new_refresh = build_token_pair(db, user, settings)
    # Link rotation chain
    new_session = db.scalar(
        select(UserSession).where(UserSession.refresh_token_hash == hash_token(new_refresh))
    )
    if new_session:
        new_session.rotated_from_id = session.id
        new_session.ip_address = ip_address
        new_session.user_agent = user_agent
        db.add(new_session)

    write_audit(
        db,
        actor_user_id=user.id,
        action="auth.refresh",
        entity_type="user_session",
        entity_id=str(session.id),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return tokens, new_refresh


def logout(db: Session, *, refresh_raw: str | None, user: User | None) -> None:
    if refresh_raw:
        token_hash = hash_token(refresh_raw)
        session = db.scalar(select(UserSession).where(UserSession.refresh_token_hash == token_hash))
        if session and session.revoked_at is None:
            session.revoked_at = datetime.now(UTC)
            db.add(session)
            write_audit(
                db,
                actor_user_id=user.id if user else session.user_id,
                action="auth.logout",
                entity_type="user_session",
                entity_id=str(session.id),
            )
            db.commit()
            return
    if user:
        write_audit(
            db,
            actor_user_id=user.id,
            action="auth.logout",
            entity_type="user",
            entity_id=str(user.id),
        )
        db.commit()


def enroll_with_code(
    db: Session,
    *,
    enrollment_code: str,
    email: str,
    password: str,
    full_name: str,
    settings: Settings,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[TokenPairOut, str]:
    code = enrollment_code.strip().upper()
    row = db.scalar(select(EnrollmentCode).where(EnrollmentCode.code == code))
    if row is None:
        raise AppError("invalid_enrollment_code", "Enrollment code is invalid", status_code=400)
    if row.status != EnrollmentCodeStatus.ACTIVE.value:
        raise AppError("enrollment_code_inactive", "Enrollment code is not active", status_code=400)
    if row.expires_at <= datetime.now(UTC):
        row.status = EnrollmentCodeStatus.EXPIRED.value
        db.add(row)
        db.commit()
        raise AppError("enrollment_code_expired", "Enrollment code has expired", status_code=400)

    employee = db.get(Employee, row.employee_id)
    if employee is None or not employee.is_active:
        raise AppError("employee_inactive", "Employee is inactive", status_code=400)

    existing = db.scalar(select(User).where(User.email == email.lower()))
    user = db.get(User, employee.user_id)
    if user is None:
        raise AppError("employee_inactive", "Employee user record missing", status_code=400)

    if existing and existing.id != user.id:
        raise AppError("email_taken", "Email is already registered", status_code=409)

    user.email = email.lower()
    user.full_name = full_name.strip()
    user.password_hash = hash_password(password)
    user.is_active = True
    user.failed_login_count = 0
    user.locked_until = None
    db.add(user)

    row.status = EnrollmentCodeStatus.USED.value
    row.used_at = datetime.now(UTC)
    db.add(row)

    tokens, refresh_raw = build_token_pair(db, user, settings)
    write_audit(
        db,
        actor_user_id=user.id,
        action="auth.enroll_with_code",
        entity_type="employee",
        entity_id=str(employee.id),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()
    return tokens, refresh_raw
