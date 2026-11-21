"""KRTime FastAPI application."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api.router import api_router
from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.errors import AppError, app_error_handler, http_exception_handler, validation_exception_handler
from app.core.logging import configure_logging
from app.core.security_headers import SecurityHeadersMiddleware
from app.services.bootstrap import ensure_bootstrap
from app.services.jobs import start_scheduler, stop_scheduler
from app.services.leave_service import ensure_leave_types


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    settings = get_settings()
    if settings.is_production:
        if not settings.embedding_encryption_key:
            raise RuntimeError("EMBEDDING_ENCRYPTION_KEY is required when APP_ENV=production")
        if settings.jwt_secret.startswith("dev-only") or len(settings.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be a strong secret in production")
    db = SessionLocal()
    try:
        ensure_bootstrap(db, settings)
        ensure_leave_types(db)
    finally:
        db.close()
    if settings.app_env.lower() != "test":
        start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


def create_app() -> FastAPI:
    settings = get_settings()
    docs = None if settings.is_production else "/docs"
    redoc = None if settings.is_production else "/redoc"
    openapi = None if settings.is_production else "/openapi.json"
    application = FastAPI(
        title=settings.app_name,
        version=__version__,
        docs_url=docs,
        redoc_url=redoc,
        openapi_url=openapi,
        lifespan=lifespan,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.add_exception_handler(AppError, app_error_handler)
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)

    @application.get("/health")
    def root_health() -> dict[str, str]:
        return {"status": "ok", "service": "attendguard-api", "version": __version__}

    application.include_router(api_router)
    return application


app = create_app()
