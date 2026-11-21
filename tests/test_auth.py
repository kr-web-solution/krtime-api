"""Auth endpoint tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_login_success(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "ChangeMeNow!Admin1"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "super_admin"
    assert "access_token" in body
    assert "attendguard_refresh" in response.cookies


def test_login_invalid_password(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "wrong-password-here"},
    )
    assert response.status_code == 401
    assert response.json()["reason_code"] == "invalid_credentials"


def test_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_me_with_token(client: TestClient, admin_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/auth/me", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "admin@example.com"


def test_refresh_and_logout(client: TestClient) -> None:
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "ChangeMeNow!Admin1"},
    )
    assert login.status_code == 200
    refresh = client.post("/api/v1/auth/refresh")
    assert refresh.status_code == 200
    assert "access_token" in refresh.json()

    logout = client.post("/api/v1/auth/logout")
    assert logout.status_code == 200
    again = client.post("/api/v1/auth/refresh")
    assert again.status_code == 401
