"""Face verification interface — Phase 3 stub (real models in Phase 4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class FaceCheckResult:
    passed: bool
    pending_review: bool
    similarity: float | None
    spoof_score: float | None
    reason_code: str | None
    notes: str


class FaceVerifier(Protocol):
    def verify(self, *, image_bytes: bytes, employee_id: str) -> FaceCheckResult: ...


class Phase3PassThroughFaceVerifier:
    """Skips face matching; documents that biometric checks are not active yet."""

    def verify(self, *, image_bytes: bytes, employee_id: str) -> FaceCheckResult:
        _ = (image_bytes, employee_id)
        return FaceCheckResult(
            passed=True,
            pending_review=False,
            similarity=None,
            spoof_score=None,
            reason_code=None,
            notes="phase3_face_stub_passthrough",
        )


face_verifier: FaceVerifier = Phase3PassThroughFaceVerifier()
