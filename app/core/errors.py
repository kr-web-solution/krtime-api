"""Consistent API error body: {reason_code, message}."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppError(Exception):
    def __init__(
        self,
        reason_code: str,
        message: str,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.reason_code = reason_code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def error_body(reason_code: str, message: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"reason_code": reason_code, "message": message}
    if extra:
        body.update(extra)
    return body


async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
    payload = error_body(exc.reason_code, exc.message)
    if exc.details:
        payload["details"] = exc.details
    return JSONResponse(status_code=exc.status_code, content=payload)


async def http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and "reason_code" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)
    message = exc.detail if isinstance(exc.detail, str) else "Request failed"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body("http_error", message),
    )


async def validation_exception_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=error_body(
            "validation_error",
            "Request validation failed",
            errors=exc.errors(),
        ),
    )
