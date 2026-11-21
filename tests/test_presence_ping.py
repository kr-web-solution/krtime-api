"""Presence ping geofence-exit alerts while checked in."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.test_attendance_pipeline import _bootstrap_employee_with_device, _submit


def test_presence_ping_alerts_once_per_exit_episode(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    ctx = _bootstrap_employee_with_device(
        client, admin_headers, lat=13.0827, lng=80.2707, radius_m=30
    )
    # Check in on site
    checkin = _submit(client, ctx, purpose="check_in", lat=13.0827, lng=80.2707)
    assert checkin.status_code == 200, checkin.text
    accepted = checkin.json()
    assert accepted["outcome"] in {"ACCEPTED", "PENDING_REVIEW"}

    far = {"lat": 13.09, "lng": 80.28}  # well outside 30 m
    first = client.post(
        "/api/v1/attendance/presence-ping",
        headers=ctx["headers"],
        json={
            "device_id": ctx["device"]["id"],
            "lat": far["lat"],
            "lng": far["lng"],
            "accuracy_m": 5,
            "fix_age_ms": 200,
            "is_mocked": False,
        },
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["status"] == "outside"
    assert body["alerted"] is True

    second = client.post(
        "/api/v1/attendance/presence-ping",
        headers=ctx["headers"],
        json={
            "device_id": ctx["device"]["id"],
            "lat": far["lat"],
            "lng": far["lng"],
            "accuracy_m": 5,
            "fix_age_ms": 200,
            "is_mocked": False,
        },
    ).json()
    assert second["status"] == "outside"
    assert second["alerted"] is False

    events = client.get(
        "/api/v1/admin/security-events?event_type=geofence_exit&limit=20",
        headers=admin_headers,
    ).json()
    mine = [e for e in events if e.get("employee_id") == ctx["employee_id"]]
    assert len(mine) >= 1
    assert mine[0]["details"]["active"] is True

    # Return inside → close episode
    back = client.post(
        "/api/v1/attendance/presence-ping",
        headers=ctx["headers"],
        json={
            "device_id": ctx["device"]["id"],
            "lat": 13.0827,
            "lng": 80.2707,
            "accuracy_m": 5,
            "fix_age_ms": 200,
            "is_mocked": False,
        },
    ).json()
    assert back["status"] == "inside"

    events2 = client.get(
        "/api/v1/admin/security-events?event_type=geofence_exit&limit=20",
        headers=admin_headers,
    ).json()
    mine2 = [e for e in events2 if e.get("employee_id") == ctx["employee_id"]]
    assert mine2[0]["details"]["active"] is False


def test_presence_ping_ignored_when_not_checked_in(
    client: TestClient, admin_headers: dict[str, str]
) -> None:
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    res = client.post(
        "/api/v1/attendance/presence-ping",
        headers=ctx["headers"],
        json={
            "device_id": ctx["device"]["id"],
            "lat": 13.0827,
            "lng": 80.2707,
            "accuracy_m": 5,
            "fix_age_ms": 100,
            "is_mocked": False,
        },
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ignored"
