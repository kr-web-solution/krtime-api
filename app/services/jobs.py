"""APScheduler jobs: forgotten checkout + review photo purge."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models import FaceVerificationAttempt, SystemSetting
from app.services.correction_service import flag_forgotten_checkouts

logger = logging.getLogger("attendguard.jobs")

_scheduler: BackgroundScheduler | None = None


def purge_expired_review_photos() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        retention = 72
        row = db.scalar(
            select(SystemSetting).where(SystemSetting.key == "review_photo.retention_hours")
        )
        if row and isinstance(row.value, dict) and "value" in row.value:
            retention = int(row.value["value"])
        now = datetime.now(UTC)
        attempts = db.scalars(
            select(FaceVerificationAttempt).where(
                FaceVerificationAttempt.review_photo_path.is_not(None)
            )
        ).all()
        removed = 0
        for attempt in attempts:
            expired = False
            if attempt.review_photo_expires_at and attempt.review_photo_expires_at <= now:
                expired = True
            elif attempt.created_at and (now - attempt.created_at).total_seconds() > retention * 3600:
                expired = True
            if not expired:
                continue
            path = Path(attempt.review_photo_path) if attempt.review_photo_path else None
            if path and path.is_file():
                path.unlink(missing_ok=True)
                removed += 1
            attempt.review_photo_path = None
            attempt.review_photo_expires_at = None
            db.add(attempt)
        if removed:
            db.commit()
            logger.info("Purged %s review photos", removed)
    except Exception:  # noqa: BLE001
        logger.exception("review photo purge failed")
        db.rollback()
    finally:
        db.close()


def forgotten_checkout_tick() -> None:
    settings = get_settings()
    db = SessionLocal()
    try:
        flag_forgotten_checkouts(db, settings)
    except Exception:  # noqa: BLE001
        logger.exception("forgotten checkout job failed")
        db.rollback()
    finally:
        db.close()


def start_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    sched = BackgroundScheduler(timezone="UTC")
    sched.add_job(forgotten_checkout_tick, "interval", minutes=15, id="forgotten_checkout")
    sched.add_job(purge_expired_review_photos, "interval", hours=6, id="purge_review_photos")
    sched.start()
    _scheduler = sched
    logger.info("APScheduler started (forgotten checkout + review purge)")
    return sched


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
