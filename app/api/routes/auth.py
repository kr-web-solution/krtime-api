"""Auth endpoints: login, refresh, logout, enroll-with-code."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials

from app.api.deps import CurrentUser, DbSession, bearer_scheme, client_meta
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.security import decode_token
from app.models import User
from app.schemas.auth import EnrollWithCodeRequest, LoginRequest, RefreshRequest
from app.schemas.common import MessageOut, TokenPairOut, UserBriefOut
from app.services import auth_service
from app.services.rate_limit import check_rate_limit
from uuid import UUID

router = APIRouter()


def _set_refresh_cookie(response: Response, refresh_raw: str, settings: Settings) -> None:
    # Lax is fine when admin origin and API share a host (localhost↔localhost).
    # Cross-host pairs like localhost ↔ 127.0.0.1 are different sites and drop Lax cookies.
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=refresh_raw,
        httponly=True,
        secure=settings.refresh_cookie_secure,
        samesite=settings.refresh_cookie_samesite,  # type: ignore[arg-type]
        max_age=settings.jwt_refresh_token_days * 24 * 3600,
        path="/api/v1/auth",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path="/api/v1/auth",
    )


def _optional_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
        return db.get(User, UUID(payload["sub"]))
    except Exception:  # noqa: BLE001
        return None


@router.post("/login", response_model=TokenPairOut)
def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPairOut:
    meta = client_meta(request)
    ip = meta.get("ip_address") or "unknown"
    check_rate_limit(
        db,
        bucket_key=f"login:{ip}",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
    tokens, refresh_raw = auth_service.login(
        db,
        email=str(payload.email),
        password=payload.password,
        settings=settings,
        **meta,
    )
    _set_refresh_cookie(response, refresh_raw, settings)
    return tokens


@router.post("/refresh", response_model=TokenPairOut)
def refresh(
    request: Request,
    response: Response,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    payload: RefreshRequest = RefreshRequest(),
) -> TokenPairOut:
    # Prefer body (mobile); fall back to httpOnly cookie (admin browser).
    refresh_raw = payload.refresh_token or request.cookies.get(settings.refresh_cookie_name)
    if not refresh_raw:
        raise AppError("missing_refresh", "Refresh token missing", status_code=401)
    meta = client_meta(request)
    tokens, new_refresh = auth_service.refresh_session(
        db,
        refresh_raw=refresh_raw,
        settings=settings,
        **meta,
    )
    _set_refresh_cookie(response, new_refresh, settings)
    return tokens


@router.post("/logout", response_model=MessageOut)
def logout(
    request: Request,
    response: Response,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
    user: Annotated[User | None, Depends(_optional_user)] = None,
) -> MessageOut:
    refresh_raw = request.cookies.get(settings.refresh_cookie_name)
    auth_service.logout(db, refresh_raw=refresh_raw, user=user)
    _clear_refresh_cookie(response, settings)
    return MessageOut(message="Logged out")


@router.post("/enroll-with-code", response_model=TokenPairOut)
def enroll_with_code(
    payload: EnrollWithCodeRequest,
    request: Request,
    response: Response,
    db: DbSession,
    settings: Annotated[Settings, Depends(get_settings)],
) -> TokenPairOut:
    meta = client_meta(request)
    tokens, refresh_raw = auth_service.enroll_with_code(
        db,
        enrollment_code=payload.enrollment_code,
        email=str(payload.email),
        password=payload.password,
        full_name=payload.full_name,
        settings=settings,
        **meta,
    )
    _set_refresh_cookie(response, refresh_raw, settings)
    return tokens


@router.get("/me", response_model=UserBriefOut)
def me(user: CurrentUser) -> UserBriefOut:
    return UserBriefOut.model_validate(user)
