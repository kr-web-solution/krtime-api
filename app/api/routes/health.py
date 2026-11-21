"""Health and version endpoints."""

from fastapi import APIRouter

from app import __version__
from app.core.config import get_settings

router = APIRouter()


@router.get("/health", include_in_schema=False)
@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "attendguard-api", "version": __version__}


@router.get("/version")
def version() -> dict[str, str]:
    settings = get_settings()
    return {
        "name": settings.app_name,
        "version": __version__,
        "env": settings.app_env,
    }
