"""QR token and dashboard tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_qr_display_link_and_token(client: TestClient, admin_headers: dict[str, str]) -> None:
    loc = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "Front Desk",
            "slug": "front-desk",
            "lat": 13.08,
            "lng": 80.27,
            "radius_m": 30,
        },
    )
    assert loc.status_code == 201

    link = client.post(
        "/api/v1/qr/front-desk/display-link",
        headers=admin_headers,
    )
    assert link.status_code == 200, link.text
    body = link.json()
    assert "sig" in body and "exp" in body

    token = client.get(
        f"/api/v1/qr/front-desk/token?exp={body['exp']}&sig={body['sig']}"
    )
    assert token.status_code == 200, token.text
    assert len(token.json()["token"]) == 16

    bad = client.get("/api/v1/qr/front-desk/token?exp=9999999999&sig=deadbeefdeadbeefdeadbeefdeadbeef")
    assert bad.status_code == 401


def test_dashboard(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/admin/dashboard", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert "total_employees" in data
    assert "by_site" in data
    assert data["currently_checked_in"] == 0


def test_create_shift(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.post(
        "/api/v1/shifts",
        headers=admin_headers,
        json={
            "name": "General Day",
            "code": "DAY",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert response.status_code == 201, response.text
    listed = client.get("/api/v1/shifts", headers=admin_headers)
    assert listed.status_code == 200
    assert any(s["code"] == "DAY" for s in listed.json())
