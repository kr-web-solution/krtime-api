"""Shared enumerations stored as strings in PostgreSQL."""

from enum import StrEnum


class UserRole(StrEnum):
    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    MANAGER = "manager"
    EMPLOYEE = "employee"


class DeviceStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    REVOKED = "revoked"
    RESET_REQUESTED = "reset_requested"


class EnrollmentCodeStatus(StrEnum):
    ACTIVE = "active"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AttendanceEventType(StrEnum):
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"


class AttendanceOutcome(StrEnum):
    ACCEPTED = "ACCEPTED"
    PENDING_REVIEW = "PENDING_REVIEW"
    REJECTED = "REJECTED"


class AttendanceRecordStatus(StrEnum):
    OPEN = "open"
    COMPLETE = "complete"
    MISSING_CHECKOUT = "missing_checkout"
    CORRECTED = "corrected"
    ON_LEAVE = "on_leave"
    ABSENT = "absent"


class LeaveRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class CorrectionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class SecurityEventSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
