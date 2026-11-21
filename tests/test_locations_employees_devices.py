"""Locations, employees, enrollment, and device registration tests."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_create_and_list_locations(client: TestClient, admin_headers: dict[str, str]) -> None:
    create = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "Main Gate",
            "slug": "main-gate",
            "lat": 13.0827,
            "lng": 80.2707,
            "radius_m": 30,
            "notes": "Calibrate with real phones",
        },
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["slug"] == "main-gate"
    assert "qr_secret" not in body

    listed = client.get("/api/v1/locations", headers=admin_headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1


def test_employee_enrollment_and_device_register(
    client: TestClient,
    admin_headers: dict[str, str],
    ecdsa_p256_pem: str,
) -> None:
    location = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "Warehouse A",
            "slug": "warehouse-a",
            "lat": 13.09,
            "lng": 80.28,
            "radius_m": 40,
        },
    ).json()

    created = client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "email": "employee1@example.com",
            "full_name": "Riya Kumar",
            "employee_code": "EMP001",
            "location_ids": [location["id"]],
            "primary_location_id": location["id"],
            "create_enrollment_code": True,
        },
    )
    assert created.status_code == 201, created.text
    payload = created.json()
    assert payload["employee"]["employee_code"] == "EMP001"
    code = payload["enrollment_code"]["code"]
    assert len(code) == 8

    enroll = client.post(
        "/api/v1/auth/enroll-with-code",
        json={
            "enrollment_code": code,
            "email": "riya@example.com",
            "password": "SecurePass!1234",
            "full_name": "Riya Kumar",
        },
    )
    assert enroll.status_code == 200, enroll.text
    employee_token = enroll.json()["access_token"]
    emp_headers = {"Authorization": f"Bearer {employee_token}"}

    me = client.get("/api/v1/employees/me", headers=emp_headers)
    assert me.status_code == 200
    assert me.json()["employee_code"] == "EMP001"

    device = client.post(
        "/api/v1/devices/register",
        headers=emp_headers,
        json={
            "public_key_pem": ecdsa_p256_pem,
            "device_model": "Test Phone",
            "os_version": "14",
            "app_version": "0.1.0",
        },
    )
    assert device.status_code == 201, device.text
    assert device.json()["status"] == "active"

    # Bad key rejected (must pass schema min length, fail crypto parse)
    bogus_pem = (
        "-----BEGIN PUBLIC KEY-----\n"
        + ("A" * 200)
        + "\n-----END PUBLIC KEY-----\n"
    )
    bad = client.post(
        "/api/v1/devices/register",
        headers=emp_headers,
        json={"public_key_pem": bogus_pem},
    )
    assert bad.status_code == 400
    assert bad.json()["reason_code"] == "invalid_public_key"


def test_employee_cannot_create_location(client: TestClient, admin_headers: dict[str, str]) -> None:
    location = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "Site B",
            "slug": "site-b",
            "lat": 13.1,
            "lng": 80.3,
            "radius_m": 30,
        },
    ).json()
    created = client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "email": "emp2@example.com",
            "full_name": "Arun",
            "employee_code": "EMP002",
            "location_ids": [location["id"]],
            "create_enrollment_code": True,
            "temporary_password": "TempPass!12345",
        },
    )
    code = created.json()["enrollment_code"]["code"]
    enroll = client.post(
        "/api/v1/auth/enroll-with-code",
        json={
            "enrollment_code": code,
            "email": "arun@example.com",
            "password": "TempPass!12345",
            "full_name": "Arun",
        },
    )
    headers = {"Authorization": f"Bearer {enroll.json()['access_token']}"}
    forbidden = client.post(
        "/api/v1/locations",
        headers=headers,
        json={
            "name": "Hacker Site",
            "slug": "hacker",
            "lat": 0,
            "lng": 0,
            "radius_m": 30,
        },
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["reason_code"] == "forbidden"
