"""Health check and append-only attendance_events trigger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import AttendanceEvent, AttendanceEventType, AttendanceOutcome, Employee, User, UserRole
from app.core.security import hash_password


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_attendance_events_append_only(db: Session) -> None:
    user = User(
        email="evt@example.com",
        password_hash=hash_password("Password!12345"),
        full_name="Event User",
        role=UserRole.EMPLOYEE.value,
    )
    db.add(user)
    db.flush()
    employee = Employee(user_id=user.id, employee_code="EVT001")
    db.add(employee)
    db.flush()

    event = AttendanceEvent(
        employee_id=employee.id,
        event_type=AttendanceEventType.CHECK_IN.value,
        outcome=AttendanceOutcome.REJECTED.value,
        reason_code="test",
        server_timestamp=datetime.now(UTC),
        idempotency_key=str(uuid.uuid4()),
    )
    db.add(event)
    db.commit()

    event.reason_code = "mutated"
    with pytest.raises(Exception):
        db.commit()
    db.rollback()
