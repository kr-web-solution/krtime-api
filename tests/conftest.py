"""Pytest fixtures for AttendGuard API."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

os.environ["DATABASE_URL"] = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg://attendguard:attendguard@localhost:5433/attendguard_test",
)
os.environ["JWT_SECRET"] = "test-jwt-secret-attendguard-please-change-48chars"
os.environ["BOOTSTRAP_ADMIN_EMAIL"] = "admin@example.com"
os.environ["BOOTSTRAP_ADMIN_PASSWORD"] = "ChangeMeNow!Admin1"
os.environ["APP_ENV"] = "test"
os.environ["REFRESH_COOKIE_SECURE"] = "false"
os.environ["FACE_ENFORCEMENT"] = "off"

from app.core.config import get_settings
from app.core.database import Base, get_db
from app.main import create_app
from app.services.bootstrap import ensure_bootstrap
import app.models  # noqa: F401

get_settings.cache_clear()


def _ensure_test_database(admin_url: str, db_name: str) -> None:
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": db_name},
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope="session")
def engine():
    settings = get_settings()
    url = settings.database_url
    if not url.endswith("/attendguard_test"):
        base = url.rsplit("/", 1)[0]
        url = f"{base}/attendguard_test"
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        settings = get_settings()

    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    try:
        _ensure_test_database(admin_url, "attendguard_test")
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL not available for tests: {exc}")

    eng = create_engine(settings.database_url, pool_pre_ping=True)
    Base.metadata.drop_all(bind=eng)
    Base.metadata.create_all(bind=eng)
    with eng.begin() as conn:
        conn.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION attendguard_forbid_attendance_event_mutation()
                RETURNS trigger AS $$
                BEGIN
                  RAISE EXCEPTION 'attendance_events is append-only';
                END;
                $$ LANGUAGE plpgsql;
                """
            )
        )
        conn.execute(text("DROP TRIGGER IF EXISTS trg_attendance_events_append_only ON attendance_events"))
        conn.execute(
            text(
                """
                CREATE TRIGGER trg_attendance_events_append_only
                BEFORE UPDATE OR DELETE ON attendance_events
                FOR EACH ROW
                EXECUTE PROCEDURE attendguard_forbid_attendance_event_mutation();
                """
            )
        )
    yield eng
    Base.metadata.drop_all(bind=eng)
    eng.dispose()


@pytest.fixture
def db(engine) -> Generator[Session, None, None]:
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    # Clean tables between tests (respect FK order via CASCADE)
    table_names = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    if table_names:
        session.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))
        session.commit()
    ensure_bootstrap(session, get_settings())
    from app.services.leave_service import ensure_leave_types

    ensure_leave_types(session)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db: Session, engine) -> Generator[TestClient, None, None]:
    # Point app SessionLocal at the same engine used by tests
    import app.core.database as database_module

    database_module.engine = engine
    database_module.SessionLocal = sessionmaker(
        bind=engine, autoflush=False, autocommit=False, class_=Session
    )

    app = create_app()

    def _override_db() -> Generator[Session, None, None]:
        yield db

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def admin_headers(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "admin@example.com",
            "password": "ChangeMeNow!Admin1",
        },
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ecdsa_p256_pem() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode("utf-8")
    )
