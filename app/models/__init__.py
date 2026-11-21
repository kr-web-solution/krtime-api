"""SQLAlchemy models for AttendGuard."""

from app.models.admin import AuditLog, RateLimitBucket, SecurityEvent, SystemSetting
from app.models.attendance import (
    AttendanceApproval,
    AttendanceChallenge,
    AttendanceCorrection,
    AttendanceEvent,
    AttendanceRecord,
)
from app.models.biometrics import BiometricConsentRecord, FaceEnrollment, FaceVerificationAttempt
from app.models.devices import RegisteredDevice
from app.models.push import PushSubscription
from app.models.enums import (
    ApprovalStatus,
    AttendanceEventType,
    AttendanceOutcome,
    AttendanceRecordStatus,
    CorrectionStatus,
    DeviceStatus,
    EnrollmentCodeStatus,
    LeaveRequestStatus,
    SecurityEventSeverity,
    UserRole,
)
from app.models.organisation import Department, EmployeeLocation, Location
from app.models.people import Employee, EnrollmentCode, User, UserSession
from app.models.shifts import Holiday, LeaveRequest, LeaveType, Shift, ShiftAssignment

__all__ = [
    "ApprovalStatus",
    "AttendanceApproval",
    "AttendanceChallenge",
    "AttendanceCorrection",
    "AttendanceEvent",
    "AttendanceEventType",
    "AttendanceOutcome",
    "AttendanceRecord",
    "AttendanceRecordStatus",
    "AuditLog",
    "BiometricConsentRecord",
    "CorrectionStatus",
    "Department",
    "DeviceStatus",
    "Employee",
    "EmployeeLocation",
    "EnrollmentCode",
    "EnrollmentCodeStatus",
    "FaceEnrollment",
    "FaceVerificationAttempt",
    "Holiday",
    "LeaveRequest",
    "LeaveRequestStatus",
    "LeaveType",
    "Location",
    "RateLimitBucket",
    "PushSubscription",
    "RegisteredDevice",
    "SecurityEvent",
    "SecurityEventSeverity",
    "Shift",
    "ShiftAssignment",
    "SystemSetting",
    "User",
    "UserRole",
    "UserSession",
]
