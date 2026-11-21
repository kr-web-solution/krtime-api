"""Initial AttendGuard schema (all Phase 1–6 tables).

Revision ID: 20260321_0001
Revises:
Create Date: 2026-03-21

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.database import Base
import app.models  # noqa: F401

revision: str = "20260321_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


APPEND_ONLY_TRIGGER = """
CREATE OR REPLACE FUNCTION attendguard_forbid_attendance_event_mutation()
RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'attendance_events is append-only; updates and deletes are forbidden';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_attendance_events_append_only ON attendance_events;
CREATE TRIGGER trg_attendance_events_append_only
BEFORE UPDATE OR DELETE ON attendance_events
FOR EACH ROW
EXECUTE FUNCTION attendguard_forbid_attendance_event_mutation();
"""

DROP_APPEND_ONLY = """
DROP TRIGGER IF EXISTS trg_attendance_events_append_only ON attendance_events;
DROP FUNCTION IF EXISTS attendguard_forbid_attendance_event_mutation();
"""


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)
    # PostgreSQL 16 uses EXECUTE FUNCTION / EXECUTE PROCEDURE depending on version;
    # use EXECUTE PROCEDURE for broader compatibility, fall back handled below.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION attendguard_forbid_attendance_event_mutation()
            RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'attendance_events is append-only; updates and deletes are forbidden';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_attendance_events_append_only ON attendance_events"))
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_attendance_events_append_only
            BEFORE UPDATE OR DELETE ON attendance_events
            FOR EACH ROW
            EXECUTE PROCEDURE attendguard_forbid_attendance_event_mutation();
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text(DROP_APPEND_ONLY))
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
