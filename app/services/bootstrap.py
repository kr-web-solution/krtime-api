"""One-time bootstrap of super admin and default system settings."""

from __future__ import annotations

import logging

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.security import hash_password
from app.models import SystemSetting, User, UserRole

logger = logging.getLogger("attendguard.bootstrap")


def ensure_schema_patches(db: Session) -> None:
    """Idempotent column adds for local/Dokploy DBs without full migrations."""
    statements = [
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_status VARCHAR(32)",
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_at TIMESTAMPTZ",
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_distance_m DOUBLE PRECISION",
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_lat DOUBLE PRECISION",
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_lng DOUBLE PRECISION",
        "ALTER TABLE attendance_records ADD COLUMN IF NOT EXISTS last_presence_accuracy_m DOUBLE PRECISION",
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id UUID PRIMARY KEY,
            employee_id UUID NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            topic VARCHAR(128) NOT NULL,
            endpoint_url TEXT,
            device_id UUID REFERENCES registered_devices(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_push_subscriptions_employee_topic UNIQUE (employee_id, topic)
        )
        """,
        "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_employee_id ON push_subscriptions (employee_id)",
        "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_topic ON push_subscriptions (topic)",
        "CREATE INDEX IF NOT EXISTS ix_push_subscriptions_device_id ON push_subscriptions (device_id)",
    ]
    for sql in statements:
        db.execute(text(sql))
    db.commit()


DEFAULT_SETTINGS: list[tuple[str, dict, str]] = [
    (
        "face.match_threshold",
        {"value": 0.363},
        "Cosine similarity threshold for face accept",
    ),
    (
        "face.borderline_band",
        {"below_accept": 0.02},
        "Scores within this band below threshold become PENDING_REVIEW",
    ),
    (
        "face.spoof_min_score",
        {"value": 0.35},
        "Minimum basic anti-spoof/quality score (not MiniFASNet unless weights added)",
    ),
    (
        "face.enforcement",
        {"value": "required"},
        "required | optional | off",
    ),
    (
        "geofence.default_radius_m",
        {"value": 30},
        "Default site geofence radius in metres",
    ),
    (
        "gps.max_accuracy_m",
        {"value": 15},
        "Maximum accepted GPS accuracy in metres",
    ),
    (
        "review_photo.retention_hours",
        {"value": 72},
        "Hours to keep PENDING_REVIEW photos before purge",
    ),
    (
        "app.min_android_version",
        {"value": "0.1.0"},
        "Minimum KRTime Android app version",
    ),
]


def ensure_bootstrap(db: Session, settings: Settings) -> None:
    ensure_schema_patches(db)
    user_count = db.scalar(select(func.count()).select_from(User)) or 0
    if user_count == 0:
        admin = User(
            email=settings.bootstrap_admin_email.lower(),
            password_hash=hash_password(settings.bootstrap_admin_password),
            full_name=settings.bootstrap_admin_name,
            role=UserRole.SUPER_ADMIN.value,
            is_active=True,
        )
        db.add(admin)
        logger.warning(
            "Created bootstrap super_admin %s — change the password immediately",
            settings.bootstrap_admin_email,
        )

    for key, value, description in DEFAULT_SETTINGS:
        exists = db.scalar(select(SystemSetting).where(SystemSetting.key == key))
        if exists is None:
            db.add(SystemSetting(key=key, value=value, description=description))

    db.commit()
