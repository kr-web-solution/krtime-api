"""Application settings loaded from environment."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# krtime-api/app/core/config.py → repo root .env (Dokploy / local also set env vars)
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ENV_CANDIDATES = (
    Path(".env"),
    _REPO_ROOT / ".env",
    Path(__file__).resolve().parents[2] / ".env",  # krtime-api/.env
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_CANDIDATES if p.is_file()) or (".env",),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "KRTime"
    app_env: str = "development"
    api_public_url: str = "http://localhost:8000"
    admin_public_url: str = "http://localhost:3000"
    cors_origins: str = (
        "http://localhost:3010,http://127.0.0.1:3010,"
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    database_url: str = Field(
        default="postgresql+psycopg://attendguard:attendguard@localhost:5432/attendguard"
    )

    jwt_secret: str = Field(default="dev-only-change-me-to-a-long-random-string-48chars")
    jwt_access_token_minutes: int = 15
    jwt_refresh_token_days: int = 14
    refresh_cookie_name: str = "attendguard_refresh"
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"

    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "ChangeMeNow!Admin1"
    bootstrap_admin_name: str = "KRTime Admin"

    embedding_encryption_key: str = ""

    default_geofence_radius_m: int = 30
    qr_window_seconds: int = 30
    challenge_ttl_seconds: int = 60
    face_match_threshold: float = 0.363
    # required | optional | off — off keeps Phase 3-style passthrough for labs without weights
    face_enforcement: str = "required"
    review_photo_dir: str = "data/review_photos"

    login_max_attempts: int = 5
    login_lockout_minutes: int = 15
    # IP login rate limit (Postgres bucket)
    login_rate_limit: int = 30
    login_rate_window_seconds: int = 300
    attendance_rate_limit: int = 60
    attendance_rate_window_seconds: int = 60

    business_timezone: str = "Asia/Kolkata"

    # Optional S3-compatible object storage (Dokploy MinIO / R2 / etc.)
    # Used by backup scripts; review photos stay on volume unless you sync them.
    s3_endpoint_url: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_bucket: str = ""
    s3_region: str = "auto"

    # Self-hosted ntfy / UnifiedPush (empty base URL disables outbound push)
    ntfy_base_url: str = ""
    ntfy_public_url: str = ""
    ntfy_admin_topic: str = "krtime-admin"
    ntfy_token: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_origins(cls, value: object) -> object:
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
