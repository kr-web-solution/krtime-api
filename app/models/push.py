"""Employee push subscriptions (ntfy topic / UnifiedPush endpoint)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base_mixins import TimestampMixin, UUIDPrimaryKeyMixin


class PushSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "push_subscriptions"
    __table_args__ = (
        UniqueConstraint("employee_id", "topic", name="uq_push_subscriptions_employee_topic"),
    )

    employee_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("employees.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    # Full UnifiedPush / ntfy publish URL when available; else API uses NTFY_BASE_URL/topic
    endpoint_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("registered_devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
