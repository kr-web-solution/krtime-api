"""PostgreSQL-backed sliding window rate limits."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import RateLimitBucket


def check_rate_limit(
    db: Session,
    *,
    bucket_key: str,
    limit: int,
    window_seconds: int,
) -> None:
    now = datetime.now(UTC)
    row = db.scalar(select(RateLimitBucket).where(RateLimitBucket.bucket_key == bucket_key))
    if row is None:
        db.add(
            RateLimitBucket(
                bucket_key=bucket_key,
                hit_count=1,
                window_started_at=now,
                locked_until=None,
            )
        )
        db.commit()
        return

    if row.locked_until and row.locked_until > now:
        raise AppError(
            "rate_limited",
            "Too many attempts. Try again later.",
            status_code=429,
            details={"retry_after": int((row.locked_until - now).total_seconds())},
        )

    if now - row.window_started_at > timedelta(seconds=window_seconds):
        row.window_started_at = now
        row.hit_count = 1
        row.locked_until = None
    else:
        row.hit_count += 1
        if row.hit_count > limit:
            row.locked_until = now + timedelta(seconds=window_seconds)
            db.add(row)
            db.commit()
            raise AppError(
                "rate_limited",
                "Too many attempts. Try again later.",
                status_code=429,
                details={"retry_after": window_seconds},
            )

    db.add(row)
    db.commit()
