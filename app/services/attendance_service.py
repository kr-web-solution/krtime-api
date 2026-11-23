"""Attendance challenges and server-side verification pipeline."""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import Settings
from app.core.errors import AppError
from app.models import (
    AttendanceChallenge,
    AttendanceEvent,
    AttendanceEventType,
    AttendanceOutcome,
    AttendanceRecord,
    AttendanceRecordStatus,
    DeviceStatus,
    Employee,
    EmployeeLocation,
    FaceVerificationAttempt,
    Location,
    RegisteredDevice,
    SecurityEvent,
    SecurityEventSeverity,
    User,
)
from app.schemas.attendance import (
    AttendanceSubmitRequest,
    AttendanceSubmitOut,
    ChallengeOut,
    PresencePingOut,
    PresencePingRequest,
    TodayStatusOut,
)
from app.services import checkin_alert_service, leave_service, notification_service, qr_service, shift_service
from app.services.device_crypto import canonical_attendance_message, verify_ecdsa_p256_signature
from app.services.face_verifier import FaceCheckResult, StoredEmbeddingFaceVerifier
from app.services.geo import haversine_m


def _business_today(settings: Settings) -> date:
    try:
        tz = ZoneInfo(settings.business_timezone)
    except Exception:  # noqa: BLE001
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date()


def _log_security(
    db: Session,
    *,
    employee_id: UUID | None,
    device_id: UUID | None,
    event_type: str,
    message: str,
    severity: str = SecurityEventSeverity.WARNING.value,
    details: dict | None = None,
) -> None:
    db.add(
        SecurityEvent(
            employee_id=employee_id,
            device_id=device_id,
            event_type=event_type,
            severity=severity,
            message=message,
            details=details,
        )
    )


def create_challenge(
    db: Session,
    *,
    employee: Employee,
    device_id: UUID,
    purpose: str,
    settings: Settings,
) -> ChallengeOut:
    device = db.get(RegisteredDevice, device_id)
    if device is None or device.employee_id != employee.id:
        raise AppError("device_not_found", "Device not registered for this employee", status_code=404)
    if device.status != DeviceStatus.ACTIVE.value:
        raise AppError("device_inactive", "Device is not active", status_code=403)

    # Expire any prior unused challenges for this purpose
    now = datetime.now(UTC)
    open_challenges = db.scalars(
        select(AttendanceChallenge).where(
            AttendanceChallenge.employee_id == employee.id,
            AttendanceChallenge.device_id == device_id,
            AttendanceChallenge.purpose == purpose,
            AttendanceChallenge.consumed_at.is_(None),
            AttendanceChallenge.expires_at > now,
        )
    ).all()
    for row in open_challenges:
        row.expires_at = now
        db.add(row)

    challenge = AttendanceChallenge(
        employee_id=employee.id,
        device_id=device_id,
        nonce=secrets.token_urlsafe(24),
        purpose=purpose,
        expires_at=now + timedelta(seconds=settings.challenge_ttl_seconds),
    )
    db.add(challenge)
    db.commit()
    db.refresh(challenge)
    return ChallengeOut(
        challenge_id=challenge.id,
        nonce=challenge.nonce,
        purpose=challenge.purpose,
        expires_at=challenge.expires_at,
        expires_in=settings.challenge_ttl_seconds,
    )


def _reject(
    db: Session,
    *,
    employee: Employee,
    payload: AttendanceSubmitRequest,
    event_type: str,
    reason_code: str,
    message: str,
    distance_m: float | None = None,
    extra: dict | None = None,
) -> AttendanceSubmitOut:
    existing = db.scalar(
        select(AttendanceEvent).where(AttendanceEvent.idempotency_key == payload.idempotency_key)
    )
    if existing:
        return AttendanceSubmitOut(
            outcome=existing.outcome,
            reason_code=existing.reason_code,
            message="Idempotent replay of prior submission",
            event_id=existing.id,
            server_timestamp=existing.server_timestamp,
            distance_m=existing.distance_m,
        )

    evidence = {
        "message": message,
        "sample_count": payload.sample_count,
        "is_mocked": payload.is_mocked,
        "fix_age_ms": payload.fix_age_ms,
        **(extra or {}),
    }
    event = AttendanceEvent(
        employee_id=employee.id,
        location_id=payload.location_id,
        device_id=payload.device_id,
        challenge_id=payload.challenge_id,
        event_type=event_type,
        outcome=AttendanceOutcome.REJECTED.value,
        reason_code=reason_code,
        server_timestamp=datetime.now(UTC),
        lat=payload.lat,
        lng=payload.lng,
        accuracy_m=payload.accuracy_m,
        distance_m=distance_m,
        idempotency_key=payload.idempotency_key,
        evidence=evidence,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return AttendanceSubmitOut(
        outcome=AttendanceOutcome.REJECTED.value,
        reason_code=reason_code,
        message=message,
        event_id=event.id,
        server_timestamp=event.server_timestamp,
        distance_m=distance_m,
    )


def submit_attendance(
    db: Session,
    *,
    employee: Employee,
    payload: AttendanceSubmitRequest,
    settings: Settings,
    image_bytes: bytes = b"",
) -> AttendanceSubmitOut:
    # Idempotency short-circuit
    prior = db.scalar(
        select(AttendanceEvent).where(AttendanceEvent.idempotency_key == payload.idempotency_key)
    )
    if prior:
        return AttendanceSubmitOut(
            outcome=prior.outcome,
            reason_code=prior.reason_code,
            message="Idempotent replay of prior submission",
            event_id=prior.id,
            server_timestamp=prior.server_timestamp,
            distance_m=prior.distance_m,
        )

    challenge = db.get(AttendanceChallenge, payload.challenge_id)
    event_type = (
        AttendanceEventType.CHECK_IN.value
        if (challenge and challenge.purpose == "check_in")
        else AttendanceEventType.CHECK_OUT.value
    )

    # 1. Challenge
    if challenge is None:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="challenge_not_found",
            message="Attendance challenge not found",
        )
    event_type = (
        AttendanceEventType.CHECK_IN.value
        if challenge.purpose == "check_in"
        else AttendanceEventType.CHECK_OUT.value
    )
    if challenge.employee_id != employee.id or challenge.device_id != payload.device_id:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="challenge_mismatch",
            message="Challenge is not bound to this employee/device",
        )
    if challenge.consumed_at is not None:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="challenge_reused",
            message="Challenge already used",
        )
    if challenge.expires_at <= datetime.now(UTC):
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="challenge_expired",
            message="Challenge has expired",
        )

    # 2. Device + signature
    device = db.get(RegisteredDevice, payload.device_id)
    if device is None or device.employee_id != employee.id or device.status != DeviceStatus.ACTIVE.value:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="device_inactive",
            message="Device is not active",
        )
    if not employee.is_active:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="employee_inactive",
            message="Employee is inactive",
        )

    message = canonical_attendance_message(
        challenge_id=str(payload.challenge_id),
        employee_id=str(employee.id),
        lat=payload.lat,
        lng=payload.lng,
        accuracy=payload.accuracy_m,
        qr_token=payload.qr_token,
        image_sha256_hex=payload.image_sha256,
    )
    try:
        verify_ecdsa_p256_signature(
            public_key_pem=device.public_key_pem,
            message=message,
            signature_b64=payload.signature_b64,
        )
    except AppError as exc:
        _log_security(
            db,
            employee_id=employee.id,
            device_id=device.id,
            event_type="bad_device_signature",
            message=exc.message,
        )
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code=exc.reason_code,
            message=exc.message,
        )

    # 3. Assignment
    assigned = db.scalar(
        select(EmployeeLocation).where(
            EmployeeLocation.employee_id == employee.id,
            EmployeeLocation.location_id == payload.location_id,
        )
    )
    location = db.get(Location, payload.location_id)
    if location is None or not location.active:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="location_inactive",
            message="Location not found or inactive",
        )
    if assigned is None:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="site_not_assigned",
            message="Employee is not assigned to this site",
        )

    # 4. GPS quality
    if payload.is_mocked:
        _log_security(
            db,
            employee_id=employee.id,
            device_id=device.id,
            event_type="mock_location",
            message="Mocked GPS reported by client",
            severity=SecurityEventSeverity.CRITICAL.value,
        )
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="gps_mocked",
            message="Mocked location is not allowed",
        )
    if payload.accuracy_m > 15:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="gps_accuracy",
            message="GPS accuracy must be 15 m or better",
        )
    if payload.fix_age_ms >= 10_000:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="gps_stale",
            message="GPS fix is too old",
        )
    if payload.sample_count < 3:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="gps_samples",
            message="Need at least 3 good GPS samples",
        )
    good_samples = [
        s
        for s in payload.samples
        if s.accuracy_m <= 15 and not s.is_mocked and s.age_ms < 10_000
    ]
    if len(good_samples) < 3 and payload.samples:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="gps_samples",
            message="Fewer than 3 good GPS samples in evidence",
        )

    # 5. Geofence (distance + accuracy <= radius)
    distance_m = haversine_m(payload.lat, payload.lng, location.lat, location.lng)
    if distance_m + payload.accuracy_m > location.radius_m:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="outside_geofence",
            message="Outside the site geofence",
            distance_m=distance_m,
            extra={"radius_m": location.radius_m},
        )

    # 6. QR
    if not qr_service.verify_qr_token(location, payload.qr_token, settings):
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="qr_invalid",
            message="QR token is invalid or expired",
            distance_m=distance_m,
        )

    # 7. Shift / leave / duplicate rules
    today = _business_today(settings)
    if leave_service.employee_on_leave(db, employee_id=employee.id, work_date=today):
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code="on_leave",
            message="Employee is on approved leave today",
            distance_m=distance_m,
        )

    open_record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.work_date == today,
            AttendanceRecord.status == AttendanceRecordStatus.OPEN.value,
        )
    )
    assignment = shift_service.current_assignment(db, employee.id, on_date=today)
    window = shift_service.evaluate_shift_window(
        db,
        employee_id=employee.id,
        work_date=today,
        when=datetime.now(UTC),
        purpose=challenge.purpose,
        settings=settings,
        location_id=location.id,
        enforce_window=True,
    )
    if not window.allowed:
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code=window.reason_code or "outside_shift",
            message="Outside allowed shift window or holiday",
            distance_m=distance_m,
        )
    if window.assignment is not None:
        assignment = window.assignment

    if challenge.purpose == "check_in":
        if open_record is not None:
            return _reject(
                db,
                employee=employee,
                payload=payload,
                event_type=event_type,
                reason_code="duplicate_check_in",
                message="Already checked in for today",
                distance_m=distance_m,
            )
    else:
        if open_record is None or open_record.check_in_event_id is None:
            return _reject(
                db,
                employee=employee,
                payload=payload,
                event_type=event_type,
                reason_code="no_open_check_in",
                message="No open check-in to check out against",
                distance_m=distance_m,
            )

    # 8–9. Face + anti-spoof / liveness signals
    if payload.image_base64:
        try:
            image_bytes = base64.b64decode(payload.image_base64, validate=False)
        except Exception:
            return _reject(
                db,
                employee=employee,
                payload=payload,
                event_type=event_type,
                reason_code="invalid_image",
                message="Face image could not be decoded",
                distance_m=distance_m,
            )
        digest = hashlib.sha256(image_bytes).hexdigest()
        if digest != payload.image_sha256:
            return _reject(
                db,
                employee=employee,
                payload=payload,
                event_type=event_type,
                reason_code="image_hash_mismatch",
                message="image_sha256 does not match uploaded image",
                distance_m=distance_m,
            )

    enforcement = (settings.face_enforcement or "required").lower()
    if enforcement == "off":
        face = FaceCheckResult(
            passed=True,
            pending_review=False,
            similarity=None,
            spoof_score=None,
            reason_code=None,
            notes="face_enforcement_off",
        )
    else:
        if not image_bytes:
            return _reject(
                db,
                employee=employee,
                payload=payload,
                event_type=event_type,
                reason_code="face_image_missing",
                message="Face photo required",
                distance_m=distance_m,
            )
        face = StoredEmbeddingFaceVerifier(db, settings).verify(
            image_bytes=image_bytes,
            employee_id=str(employee.id),
            liveness_passed=payload.liveness_passed,
        )
        if enforcement == "optional" and face.reason_code in {
            "face_image_missing",
            "face_not_enrolled",
            "face_engine_unavailable",
        }:
            face = FaceCheckResult(
                passed=True,
                pending_review=False,
                similarity=face.similarity,
                spoof_score=face.spoof_score,
                reason_code=None,
                notes=f"optional_skip:{face.reason_code}",
            )

    if not face.passed and not face.pending_review:
        db.add(
            FaceVerificationAttempt(
                employee_id=employee.id,
                similarity_score=face.similarity,
                spoof_score=face.spoof_score,
                liveness_passed=payload.liveness_passed,
                model_version="phase4",
                outcome=AttendanceOutcome.REJECTED.value,
                reason_code=face.reason_code,
            )
        )
        return _reject(
            db,
            employee=employee,
            payload=payload,
            event_type=event_type,
            reason_code=face.reason_code or "face_rejected",
            message="Face verification failed",
            distance_m=distance_m,
            extra={"face_notes": face.notes},
        )

    outcome = (
        AttendanceOutcome.PENDING_REVIEW.value
        if face.pending_review
        else AttendanceOutcome.ACCEPTED.value
    )

    # Consume challenge
    challenge.consumed_at = datetime.now(UTC)
    db.add(challenge)

    device.last_seen_at = datetime.now(UTC)
    db.add(device)

    event = AttendanceEvent(
        employee_id=employee.id,
        location_id=location.id,
        device_id=device.id,
        challenge_id=challenge.id,
        event_type=event_type,
        outcome=outcome,
        reason_code=None if outcome == AttendanceOutcome.ACCEPTED.value else "pending_review",
        server_timestamp=datetime.now(UTC),
        lat=payload.lat,
        lng=payload.lng,
        accuracy_m=payload.accuracy_m,
        distance_m=distance_m,
        face_similarity=face.similarity,
        spoof_score=face.spoof_score,
        liveness_passed=payload.liveness_passed,
        open_event_id=open_record.check_in_event_id if open_record else None,
        shift_assignment_id=assignment.id if assignment else None,
        idempotency_key=payload.idempotency_key,
        evidence={
            "sample_count": payload.sample_count,
            "face_notes": face.notes,
            "client_app_version": payload.client_app_version,
        },
    )
    db.add(event)
    db.flush()

    review_path = None
    review_expires = None
    if face.pending_review and face.review_image_bytes:
        review_dir = Path(settings.review_photo_dir)
        review_dir.mkdir(parents=True, exist_ok=True)
        review_path = str(review_dir / f"{event.id}.jpg")
        Path(review_path).write_bytes(face.review_image_bytes[:120_000])
        review_expires = datetime.now(UTC) + timedelta(hours=72)

    db.add(
        FaceVerificationAttempt(
            employee_id=employee.id,
            attendance_event_id=event.id,
            similarity_score=face.similarity,
            spoof_score=face.spoof_score,
            liveness_passed=payload.liveness_passed,
            model_version="phase4",
            outcome=outcome,
            reason_code=face.reason_code,
            review_photo_path=review_path,
            review_photo_expires_at=review_expires,
        )
    )
    # Raw request image is not retained beyond this point (only optional review copy).

    if challenge.purpose == "check_in":
        record = AttendanceRecord(
            employee_id=employee.id,
            work_date=today,
            location_id=location.id,
            shift_assignment_id=assignment.id if assignment else None,
            check_in_event_id=event.id,
            check_in_at=event.server_timestamp,
            status=AttendanceRecordStatus.OPEN.value,
            is_late=window.is_late,
            last_presence_status="inside",
            last_presence_at=event.server_timestamp,
            last_presence_distance_m=round(distance_m, 2) if distance_m is not None else None,
            last_presence_lat=payload.lat,
            last_presence_lng=payload.lng,
            last_presence_accuracy_m=round(payload.accuracy_m, 2),
        )
        db.add(record)
    else:
        assert open_record is not None
        open_record.check_out_event_id = event.id
        open_record.check_out_at = event.server_timestamp
        open_record.status = AttendanceRecordStatus.COMPLETE.value
        open_record.is_early_departure = window.is_early_departure
        if open_record.check_in_at:
            delta = event.server_timestamp - open_record.check_in_at
            open_record.worked_minutes = int(delta.total_seconds() // 60)
        db.add(open_record)

    if (
        challenge.purpose == "check_in"
        and window.is_late
        and outcome in {AttendanceOutcome.ACCEPTED.value, AttendanceOutcome.PENDING_REVIEW.value}
    ):
        shift_name = window.shift.name if window.shift else None
        start_bound = None
        if window.shift is not None:
            start_bound, _ = shift_service.shift_bounds(window.shift, today, settings=settings)
        minutes_over = 0
        if start_bound is not None:
            check_ts = event.server_timestamp
            if check_ts.tzinfo is None:
                check_ts = check_ts.replace(tzinfo=start_bound.tzinfo)
            minutes_over = max(0, int((check_ts - start_bound).total_seconds() // 60))
        checkin_alert_service.log_late_checkin(
            db,
            employee=employee,
            shift_name=shift_name,
            check_in_at=event.server_timestamp,
            minutes_over=minutes_over,
            settings=settings,
        )

    db.commit()
    db.refresh(event)

    purpose_label = "Check-in" if challenge.purpose == "check_in" else "Check-out"
    if outcome == AttendanceOutcome.ACCEPTED.value:
        notification_service.notify_employee(
            db,
            employee_id=employee.id,
            title=f"{purpose_label} accepted",
            message=f"{purpose_label} at {location.name} was recorded.",
            priority=3,
            tags="white_check_mark",
            settings=settings,
        )
    else:
        notification_service.notify_employee(
            db,
            employee_id=employee.id,
            title=f"{purpose_label} pending review",
            message=f"Your {purpose_label.lower()} at {location.name} needs admin review.",
            priority=3,
            tags="hourglass",
            settings=settings,
        )
        notification_service.notify_admin(
            title="Face pending review",
            message=f"{employee.employee_code} — {purpose_label.lower()} at {location.name}",
            priority=4,
            tags="eye",
            settings=settings,
        )

    return AttendanceSubmitOut(
        outcome=outcome,
        reason_code=event.reason_code,
        message="Attendance accepted" if outcome == AttendanceOutcome.ACCEPTED.value else "Pending review",
        event_id=event.id,
        server_timestamp=event.server_timestamp,
        distance_m=distance_m,
    )


def today_status(db: Session, *, employee: Employee, settings: Settings) -> TodayStatusOut:
    today = _business_today(settings)
    on_leave = leave_service.employee_on_leave(db, employee_id=employee.id, work_date=today)
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.work_date == today,
        )
    )
    if record is None:
        return TodayStatusOut(
            work_date=today.isoformat(),
            status="on_leave" if on_leave else None,
            can_check_in=not on_leave,
            can_check_out=False,
        )
    blocked = on_leave or record.status == AttendanceRecordStatus.ON_LEAVE.value
    return TodayStatusOut(
        work_date=today.isoformat(),
        status=record.status,
        check_in_at=record.check_in_at,
        check_out_at=record.check_out_at,
        can_check_in=(
            not blocked
            and record.status
            not in {
                AttendanceRecordStatus.OPEN.value,
                AttendanceRecordStatus.COMPLETE.value,
                AttendanceRecordStatus.ON_LEAVE.value,
            }
        ),
        can_check_out=not blocked and record.status == AttendanceRecordStatus.OPEN.value,
        open_event_id=record.check_in_event_id,
        location_id=record.location_id,
    )


def history(db: Session, *, employee: Employee, limit: int = 30) -> list:
    rows = db.scalars(
        select(AttendanceRecord)
        .where(AttendanceRecord.employee_id == employee.id)
        .order_by(AttendanceRecord.work_date.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "work_date": r.work_date.isoformat(),
            "status": r.status,
            "check_in_at": r.check_in_at,
            "check_out_at": r.check_out_at,
            "worked_minutes": r.worked_minutes,
            "location_id": r.location_id,
            "is_late": r.is_late,
            "is_early_departure": r.is_early_departure,
        }
        for r in rows
    ]


def _active_geofence_exit(
    db: Session, *, employee_id: UUID, day_start: datetime
) -> SecurityEvent | None:
    rows = db.scalars(
        select(SecurityEvent)
        .where(
            SecurityEvent.employee_id == employee_id,
            SecurityEvent.event_type == "geofence_exit",
            SecurityEvent.created_at >= day_start,
        )
        .order_by(SecurityEvent.created_at.desc())
    ).all()
    for row in rows:
        details = row.details or {}
        if details.get("active") is True:
            return row
    return None


def presence_ping(
    db: Session,
    *,
    employee: Employee,
    payload: PresencePingRequest,
    settings: Settings,
) -> PresencePingOut:
    """While checked in, sample site presence and alert admin once per exit episode."""
    today = _business_today(settings)
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=UTC)

    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.employee_id == employee.id,
            AttendanceRecord.work_date == today,
            AttendanceRecord.status == AttendanceRecordStatus.OPEN.value,
        )
    )
    if record is None or record.location_id is None:
        return PresencePingOut(
            status="ignored",
            message="Not checked in; presence ping ignored",
        )

    device = db.get(RegisteredDevice, payload.device_id)
    if device is None or device.employee_id != employee.id:
        raise AppError("device_not_found", "Device not registered for this employee", status_code=404)
    if device.status != DeviceStatus.ACTIVE.value:
        raise AppError("device_inactive", "Device is not active", status_code=403)

    location = db.get(Location, record.location_id)
    if location is None or not location.active:
        return PresencePingOut(
            status="ignored",
            location_id=record.location_id,
            message="Check-in location inactive",
        )

    now = datetime.now(UTC)

    def _stamp_presence(status: str, distance: float | None) -> None:
        record.last_presence_status = status
        record.last_presence_at = now
        record.last_presence_distance_m = round(distance, 2) if distance is not None else None
        record.last_presence_lat = payload.lat
        record.last_presence_lng = payload.lng
        record.last_presence_accuracy_m = round(payload.accuracy_m, 2)
        db.add(record)

    if payload.is_mocked:
        _log_security(
            db,
            employee_id=employee.id,
            device_id=device.id,
            event_type="mock_location",
            message="Mocked GPS on presence ping",
            severity=SecurityEventSeverity.CRITICAL.value,
            details={"source": "presence_ping"},
        )
        _stamp_presence("mocked", None)
        db.commit()
        return PresencePingOut(
            status="mocked",
            location_id=location.id,
            message="Mocked location is not allowed",
        )

    distance_m = haversine_m(payload.lat, payload.lng, location.lat, location.lng)
    outside = distance_m + payload.accuracy_m > location.radius_m
    active_exit = _active_geofence_exit(db, employee_id=employee.id, day_start=day_start)

    if not outside:
        if active_exit is not None:
            details = dict(active_exit.details or {})
            details["active"] = False
            details["returned_at"] = now.isoformat()
            details["return_distance_m"] = round(distance_m, 2)
            active_exit.details = details
            flag_modified(active_exit, "details")
            db.add(active_exit)
        _stamp_presence("inside", distance_m)
        db.commit()
        return PresencePingOut(
            status="inside",
            distance_m=round(distance_m, 2),
            location_id=location.id,
            message="Inside site geofence",
        )

    _stamp_presence("outside", distance_m)
    if active_exit is not None:
        db.commit()
        return PresencePingOut(
            status="outside",
            distance_m=round(distance_m, 2),
            alerted=False,
            location_id=location.id,
            message="Still outside; exit alert already active",
        )

    user = db.get(User, employee.user_id)
    display = (user.full_name if user else None) or employee.employee_code
    exit_message = f"{display} left {location.name} while checked in"
    _log_security(
        db,
        employee_id=employee.id,
        device_id=device.id,
        event_type="geofence_exit",
        message=exit_message,
        severity=SecurityEventSeverity.WARNING.value,
        details={
            "active": True,
            "location_id": str(location.id),
            "location_name": location.name,
            "location_slug": location.slug,
            "distance_m": round(distance_m, 2),
            "accuracy_m": round(payload.accuracy_m, 2),
            "lat": payload.lat,
            "lng": payload.lng,
            "radius_m": location.radius_m,
            "employee_code": employee.employee_code,
        },
    )
    db.commit()
    notification_service.notify_admin(
        title="Geofence exit",
        message=f"{exit_message} (~{round(distance_m)} m)",
        priority=5,
        tags="warning,round_pushpin",
        settings=settings,
    )
    return PresencePingOut(
        status="outside",
        distance_m=round(distance_m, 2),
        alerted=True,
        location_id=location.id,
        message="Outside geofence; admin alerted",
    )
