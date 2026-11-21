"""Attendance reports (JSON / Excel / PDF)."""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query
from fastapi.responses import Response

from app.api.deps import AdminUser, DbSession
from app.core.errors import AppError
from app.services import report_service

router = APIRouter()


@router.get("")
def get_report(
    db: DbSession,
    _: AdminUser,
    period: Annotated[str, Query(pattern="^(daily|weekly|monthly)$")] = "daily",
    anchor: Annotated[date | None, Query()] = None,
    start: Annotated[date | None, Query()] = None,
    end: Annotated[date | None, Query()] = None,
    employee_id: UUID | None = None,
    location_id: UUID | None = None,
    format: Annotated[str, Query(pattern="^(json|xlsx|pdf)$")] = "json",
):
    if start and end:
        s, e = start, end
        if e < s:
            raise AppError("invalid_range", "end must be on or after start", status_code=400)
        title = f"Attendance {s.isoformat()} → {e.isoformat()}"
    else:
        day = anchor or date.today()
        try:
            s, e = report_service.period_bounds(period, day)
        except ValueError as exc:
            raise AppError("invalid_period", str(exc), status_code=400) from exc
        title = f"Attendance {period} ({s.isoformat()} → {e.isoformat()})"

    rows = report_service.report_rows(
        db, start=s, end=e, employee_id=employee_id, location_id=location_id
    )
    kpis = report_service.summary_kpis(rows)

    if format == "json":
        return {"title": title, "start": s.isoformat(), "end": e.isoformat(), "kpis": kpis, "rows": rows}

    if format == "xlsx":
        data = report_service.build_xlsx(rows, title=title)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="attendguard-report.xlsx"'},
        )

    data = report_service.build_pdf(rows, title=title, kpis=kpis)
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="attendguard-report.pdf"'},
    )
