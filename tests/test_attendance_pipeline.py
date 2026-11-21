"""Server-side attendance verification pipeline tests (Phase 3)."""

from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import RegisteredDevice
from app.services.device_crypto import canonical_attendance_message
from app.services.qr_service import compute_qr_token, _window_index


def _make_key() -> tuple[ec.EllipticCurvePrivateKey, str]:
    private = ec.generate_private_key(ec.SECP256R1())
    pem = (
        private.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
    return private, pem


def _sign(private: ec.EllipticCurvePrivateKey, message: bytes) -> str:
    sig = private.sign(message, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(sig).decode("ascii")


def _bootstrap_employee_with_device(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    lat: float = 13.0827,
    lng: float = 80.2707,
    radius_m: int = 50,
) -> dict:
    private, pem = _make_key()
    loc = client.post(
        "/api/v1/locations",
        headers=admin_headers,
        json={
            "name": "Gate",
            "slug": f"gate-{uuid.uuid4().hex[:6]}",
            "lat": lat,
            "lng": lng,
            "radius_m": radius_m,
        },
    ).json()
    created = client.post(
        "/api/v1/employees",
        headers=admin_headers,
        json={
            "email": f"emp-{uuid.uuid4().hex[:8]}@example.com",
            "full_name": "Test Emp",
            "employee_code": f"T{uuid.uuid4().hex[:6].upper()}",
            "location_ids": [loc["id"]],
            "primary_location_id": loc["id"],
            "create_enrollment_code": True,
        },
    ).json()
    code = created["enrollment_code"]["code"]
    enroll = client.post(
        "/api/v1/auth/enroll-with-code",
        json={
            "enrollment_code": code,
            "email": f"user-{uuid.uuid4().hex[:8]}@example.com",
            "password": "SecurePass!1234",
            "full_name": "Test Emp",
        },
    )
    token = enroll.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    device = client.post(
        "/api/v1/devices/register",
        headers=headers,
        json={"public_key_pem": pem, "device_model": "Test", "app_version": "0.3.0"},
    ).json()
    return {
        "headers": headers,
        "employee": created["employee"],
        "location": loc,
        "device": device,
        "private": private,
        "employee_id": created["employee"]["id"],
    }


def _submit(
    client: TestClient,
    ctx: dict,
    *,
    purpose: str,
    lat: float | None = None,
    lng: float | None = None,
    accuracy: float = 8.0,
    sample_count: int = 3,
    mocked: bool = False,
    qr_token: str | None = None,
    bad_signature: bool = False,
    idem: str | None = None,
) -> object:
    from app.core.database import SessionLocal
    from app.models import Location

    challenge = client.post(
        "/api/v1/attendance/challenge",
        headers=ctx["headers"],
        json={"device_id": ctx["device"]["id"], "purpose": purpose},
    )
    assert challenge.status_code == 200, challenge.text
    ch = challenge.json()

    lat = ctx["location"]["lat"] if lat is None else lat
    lng = ctx["location"]["lng"] if lng is None else lng

    db = SessionLocal()
    try:
        loc = db.get(Location, uuid.UUID(ctx["location"]["id"]))
        assert loc is not None
        settings = get_settings()
        window = _window_index(window_seconds=settings.qr_window_seconds)
        token = qr_token or compute_qr_token(
            qr_secret=loc.qr_secret, location_id=loc.id, window=window
        )
    finally:
        db.close()

    image_hash = hashlib.sha256(b"").hexdigest()
    message = canonical_attendance_message(
        challenge_id=ch["challenge_id"],
        employee_id=ctx["employee_id"],
        lat=lat,
        lng=lng,
        accuracy=accuracy,
        qr_token=token,
        image_sha256_hex=image_hash,
    )
    signature = _sign(ctx["private"], message)
    if bad_signature:
        signature = base64.b64encode(b"\x00" * 64).decode("ascii")

    samples = [
        {
            "lat": lat,
            "lng": lng,
            "accuracy_m": accuracy,
            "age_ms": 1000,
            "is_mocked": mocked,
        }
        for _ in range(max(sample_count, 3))
    ]
    path = "/api/v1/attendance/check-in" if purpose == "check_in" else "/api/v1/attendance/check-out"
    return client.post(
        path,
        headers=ctx["headers"],
        json={
            "challenge_id": ch["challenge_id"],
            "device_id": ctx["device"]["id"],
            "location_id": ctx["location"]["id"],
            "lat": lat,
            "lng": lng,
            "accuracy_m": accuracy,
            "fix_age_ms": 2000,
            "is_mocked": mocked,
            "sample_count": sample_count,
            "samples": samples,
            "qr_token": token,
            "image_sha256": image_hash,
            "signature_b64": signature,
            "idempotency_key": idem or str(uuid.uuid4()),
            "liveness_passed": True,
            "client_app_version": "0.3.0",
        },
    )


def test_accepted_check_in_and_check_out(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    # Point SessionLocal at test engine
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )

    ctx = _bootstrap_employee_with_device(client, admin_headers)
    cin = _submit(client, ctx, purpose="check_in")
    assert cin.status_code == 200, cin.text
    assert cin.json()["outcome"] == "ACCEPTED"

    today = client.get("/api/v1/attendance/today", headers=ctx["headers"])
    assert today.status_code == 200
    assert today.json()["can_check_out"] is True

    cout = _submit(client, ctx, purpose="check_out")
    assert cout.status_code == 200, cout.text
    assert cout.json()["outcome"] == "ACCEPTED"


def test_outside_geofence_rejected(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers, radius_m=30)
    # ~1 km away
    resp = _submit(client, ctx, purpose="check_in", lat=13.0927, lng=80.2707)
    assert resp.status_code == 200
    assert resp.json()["outcome"] == "REJECTED"
    assert resp.json()["reason_code"] == "outside_geofence"


def test_bad_signature_rejected(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    resp = _submit(client, ctx, purpose="check_in", bad_signature=True)
    assert resp.json()["outcome"] == "REJECTED"
    assert resp.json()["reason_code"] == "invalid_signature"


def test_duplicate_check_in_rejected(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    assert _submit(client, ctx, purpose="check_in").json()["outcome"] == "ACCEPTED"
    resp = _submit(client, ctx, purpose="check_in")
    assert resp.json()["reason_code"] == "duplicate_check_in"


def test_checkout_without_checkin(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    resp = _submit(client, ctx, purpose="check_out")
    assert resp.json()["reason_code"] == "no_open_check_in"


def test_poor_gps_accuracy(client: TestClient, admin_headers: dict[str, str], engine) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    resp = _submit(client, ctx, purpose="check_in", accuracy=25.0)
    assert resp.json()["reason_code"] == "gps_accuracy"


def test_challenge_reuse(client: TestClient, admin_headers: dict[str, str], engine, db: Session) -> None:
    import app.core.database as database_module
    from sqlalchemy.orm import sessionmaker, Session as SASession

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=SASession
    )
    ctx = _bootstrap_employee_with_device(client, admin_headers)
    challenge = client.post(
        "/api/v1/attendance/challenge",
        headers=ctx["headers"],
        json={"device_id": ctx["device"]["id"], "purpose": "check_in"},
    ).json()

    from app.models import Location
    from app.services.qr_service import compute_qr_token, _window_index

    loc = db.get(Location, uuid.UUID(ctx["location"]["id"]))
    assert loc is not None
    settings = get_settings()
    token = compute_qr_token(
        qr_secret=loc.qr_secret,
        location_id=loc.id,
        window=_window_index(window_seconds=settings.qr_window_seconds),
    )
    lat, lng, accuracy = loc.lat, loc.lng, 8.0
    image_hash = hashlib.sha256(b"").hexdigest()
    message = canonical_attendance_message(
        challenge_id=challenge["challenge_id"],
        employee_id=ctx["employee_id"],
        lat=lat,
        lng=lng,
        accuracy=accuracy,
        qr_token=token,
        image_sha256_hex=image_hash,
    )
    signature = _sign(ctx["private"], message)
    body = {
        "challenge_id": challenge["challenge_id"],
        "device_id": ctx["device"]["id"],
        "location_id": ctx["location"]["id"],
        "lat": lat,
        "lng": lng,
        "accuracy_m": accuracy,
        "fix_age_ms": 1000,
        "is_mocked": False,
        "sample_count": 3,
        "samples": [
            {"lat": lat, "lng": lng, "accuracy_m": accuracy, "age_ms": 500, "is_mocked": False}
        ]
        * 3,
        "qr_token": token,
        "image_sha256": image_hash,
        "signature_b64": signature,
        "idempotency_key": str(uuid.uuid4()),
    }
    first = client.post("/api/v1/attendance/check-in", headers=ctx["headers"], json=body)
    assert first.json()["outcome"] == "ACCEPTED"
    body["idempotency_key"] = str(uuid.uuid4())
    second = client.post("/api/v1/attendance/check-in", headers=ctx["headers"], json=body)
    assert second.json()["reason_code"] == "challenge_reused"
