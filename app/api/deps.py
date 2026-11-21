"""FastAPI dependencies: DB, current user, RBAC."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import decode_token
from app.models import Employee, User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AppError("unauthorized", "Missing or invalid access token", status_code=401)
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        user_id = UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise AppError("unauthorized", "Invalid or expired access token", status_code=401) from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AppError("unauthorized", "User is inactive or not found", status_code=401)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole | str) -> Callable[[User], User]:
    allowed = {r.value if isinstance(r, UserRole) else r for r in roles}

    def _checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise AppError("forbidden", "Insufficient permissions", status_code=403)
        return user

    return _checker


AdminUser = Annotated[
    User,
    Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN, UserRole.MANAGER)),
]
SuperAdminUser = Annotated[User, Depends(require_roles(UserRole.SUPER_ADMIN, UserRole.ADMIN))]


def get_current_employee(db: DbSession, user: CurrentUser) -> Employee:
    employee = db.scalar(select(Employee).where(Employee.user_id == user.id))
    if employee is None or not employee.is_active:
        raise AppError("employee_required", "No active employee profile for this user", status_code=403)
    return employee


CurrentEmployee = Annotated[Employee, Depends(get_current_employee)]


def client_meta(request: Request, user_agent: Annotated[str | None, Header(alias="User-Agent")] = None) -> dict:
    ip = request.client.host if request.client else None
    return {"ip_address": ip, "user_agent": user_agent}
