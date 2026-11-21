"""Phase 5: shift windows, leave, corrections, reports, month lock."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import AttendanceRecord, AttendanceRecordStatus, LeaveRequestStatus, Shift
from app.services import report_service, shift_service


def test_shift_bounds_same_day_and_cross_midnight():
    settings = Settings(business_timezone="Asia/Kolkata", app_env="test")
    day = date(2026, 3, 21)
    day_shift = Shift(
        name="Day",
        start_time=time(9, 0),
        end_time=time(18, 0),
        grace_late_minutes=10,
        grace_early_minutes=10,
        cross_midnight=False,
    )
    start, end = shift_service.shift_bounds(day_shift, day, settings=settings)
    assert start.hour == 9 and end.hour == 18
    assert end.date() == day

    night = Shift(
        name="Night",
        start_time=time(22, 0),
        end_time=time(6, 0),
        grace_late_minutes=15,
        grace_early_minutes=15,
        cross_midnight=True,
    )
    n_start, n_end = shift_service.shift_bounds(night, day, settings=settings)
    assert n_end.date() == day + timedelta(days=1)
    assert n_start.hour == 22


def test_period_bounds():
    d = date(2026, 3, 18)  # Wednesday
    assert report_service.period_bounds("daily", d) == (d, d)
    ws, we = report_service.period_bounds("weekly", d)
    assert ws == date(2026, 3, 16) and we == date(2026, 3, 22)
    ms, me = report_service.period_bounds("monthly", d)
    assert ms == date(2026, 3, 1) and me == date(2026, 3, 31)


def test_xlsx_and_pdf_builders():
    rows = [
        {
            "work_date": "2026-03-21",
            "employee_code": "E1",
            "full_name": "Ada",
            "status": "complete",
            "check_in_at": None,
            "check_out_at": None,
            "worked_minutes": 480,
            "is_late": False,
            "is_early_departure": False,
            "month_locked": False,
        }
    ]
    xlsx = report_service.build_xlsx(rows, title="Test")
    assert xlsx[:2] == b"PK"
    pdf = report_service.build_pdf(rows, title="Test", kpis={"row_count": 1})
    assert pdf.startswith(b"%PDF")


def _enroll_employee(client: TestClient, admin_headers: dict[str, str]) -> tuple[dict, dict[str, str]]:
    loc = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "P5 Site",
            "slug": f"p5-{uuid.uuid4().hex[:6]}",
            "lat": 13.08,
            "lng": 80.27,
            "radius_m": 40,
        },
    ).json()
    created = client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "email": f"p5-{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Phase Five",
            "employee_code": f"P5{uuid.uuid4().hex[:5].upper()}",
            "location_ids": [loc["id"]],
            "primary_location_id": loc["id"],
            "create_enrollment_code": True,
        },
    )
    assert created.status_code == 201, created.text
    code = created.json()["enrollment_code"]["code"]
    enroll = client.post(
        "/api/v1/auth/enroll-with-code",
        json={
            "enrollment_code": code,
            "email": f"user-p5-{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass!1234",
            "full_name": "Phase Five",
        },
    )
    assert enroll.status_code == 200, enroll.text
    headers = {"Authorization": f"Bearer {enroll.json()['access_token']}"}
    return created.json()["employee"], headers


def test_leave_approve_and_month_lock(
    client: TestClient, admin_headers: dict[str, str], db: Session
) -> None:
    emp, emp_headers = _enroll_employee(client, admin_headers)

    types = client.get("/api/v1/leave/types", headers=emp_headers)
    assert types.status_code == 200, types.text
    assert types.json(), "leave types should be seeded on app startup"
    leave_type_id = types.json()[0]["id"]

    start = date.today() + timedelta(days=3)
    end = start + timedelta(days=1)
    apply = client.post(
        "/api/v1/leave/apply",
        headers=emp_headers,
        json={
            "leave_type_id": leave_type_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reason": "Family event",
        },
    )
    assert apply.status_code == 201, apply.text
    req_id = apply.json()["id"]

    decide = client.post(
        f"/api/v1/leave/admin/{req_id}/decide",
        headers=admin_headers,
        json={"approve": True, "notes": "OK"},
    )
    assert decide.status_code == 200
    assert decide.json()["status"] == LeaveRequestStatus.APPROVED.value

    record = db.query(AttendanceRecord).filter_by(employee_id=emp["id"], work_date=start).one()
    assert record.status == AttendanceRecordStatus.ON_LEAVE.value

    lock = client.post(
        "/api/v1/corrections/month-lock",
        headers=admin_headers,
        json={"year": start.year, "month": start.month},
    )
    assert lock.status_code == 200
    db.refresh(record)
    assert record.month_locked is True

    corr = client.post(
        "/api/v1/corrections",
        headers=admin_headers,
        json={
            "attendance_record_id": str(record.id),
            "reason": "Should fail because locked",
            "proposed_check_out_at": datetime.utcnow().isoformat() + "Z",
        },
    )
    assert corr.status_code == 400
    assert corr.json()["reason_code"] == "month_locked"


def test_shift_my_endpoint(client: TestClient, admin_headers: dict[str, str]) -> None:
    emp, emp_headers = _enroll_employee(client, admin_headers)
    created = client.post(
        "/api/v1/shifts",
        headers=admin_headers,
        json={
            "name": f"Phase5-{uuid.uuid4().hex[:6]}",
            "code": "P5",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
            "grace_late_minutes": 10,
            "grace_early_minutes": 10,
            "cross_midnight": False,
        },
    )
    assert created.status_code == 201, created.text
    shift_id = created.json()["id"]
    assign = client.post(
        f"/api/v1/shifts/employees/{emp['id']}/assign",
        headers=admin_headers,
        json={"shift_id": shift_id},
    )
    assert assign.status_code == 200, assign.text

    mine = client.get("/api/v1/shifts/my", headers=emp_headers)
    assert mine.status_code == 200
    body = mine.json()
    assert body["shift_id"] == shift_id
    assert "today_window_start" in body


def test_reports_json(client: TestClient, admin_headers: dict[str, str]) -> None:
    res = client.get("/api/v1/admin/reports?period=daily&format=json", headers=admin_headers)
    assert res.status_code == 200
    body = res.json()
    assert "kpis" in body and "rows" in body


def test_holidays_crud(client: TestClient, admin_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/holidays",
        headers=admin_headers,
        json={"name": "Test Day", "holiday_date": "2026-08-15", "is_optional": False},
    )
    assert created.status_code == 201, created.text
    hid = created.json()["id"]
    listed = client.get("/api/v1/holidays", headers=admin_headers)
    assert any(h["id"] == hid for h in listed.json())
    deleted = client.delete(f"/api/v1/holidays/{hid}", headers=admin_headers)
    assert deleted.status_code == 204
