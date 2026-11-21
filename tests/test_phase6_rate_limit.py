"""Phase 6 rate limit bucket behaviour."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import RateLimitBucket
from app.services.rate_limit import check_rate_limit


def test_rate_limit_allows_then_blocks(db: Session) -> None:
    key = "test:bucket:phase6"
    for _ in range(3):
        check_rate_limit(db, bucket_key=key, limit=3, window_seconds=60)
    with pytest.raises(AppError) as exc:
        check_rate_limit(db, bucket_key=key, limit=3, window_seconds=60)
    assert exc.value.reason_code == "rate_limited"
    assert exc.value.status_code == 429

    row = db.query(RateLimitBucket).filter_by(bucket_key=key).one()
    assert row.locked_until is not None
    assert row.locked_until > datetime.now(UTC) - timedelta(seconds=1)


def test_security_events_endpoint(client, admin_headers) -> None:
    res = client.get("/api/v1/admin/security-events", headers=admin_headers)
    assert res.status_code == 200
    assert isinstance(res.json(), list)
