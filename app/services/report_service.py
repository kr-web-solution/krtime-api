"""Daily / weekly / monthly attendance reports (JSON + Excel + PDF)."""

from __future__ import annotations

import io
from datetime import date, timedelta
from uuid import UUID

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AttendanceRecord, Employee, User


def report_rows(
    db: Session,
    *,
    start: date,
    end: date,
    employee_id: UUID | None = None,
    location_id: UUID | None = None,
) -> list[dict]:
    stmt = (
        select(AttendanceRecord, Employee, User)
        .join(Employee, Employee.id == AttendanceRecord.employee_id)
        .join(User, User.id == Employee.user_id)
        .where(
            AttendanceRecord.work_date >= start,
            AttendanceRecord.work_date <= end,
        )
        .order_by(AttendanceRecord.work_date, Employee.employee_code)
    )
    if employee_id:
        stmt = stmt.where(AttendanceRecord.employee_id == employee_id)
    if location_id:
        stmt = stmt.where(AttendanceRecord.location_id == location_id)

    rows = []
    for record, emp, user in db.execute(stmt).all():
        rows.append(
            {
                "work_date": record.work_date.isoformat(),
                "employee_id": str(emp.id),
                "employee_code": emp.employee_code,
                "full_name": user.full_name,
                "status": record.status,
                "check_in_at": record.check_in_at.isoformat() if record.check_in_at else None,
                "check_out_at": record.check_out_at.isoformat() if record.check_out_at else None,
                "worked_minutes": record.worked_minutes,
                "is_late": record.is_late,
                "is_early_departure": record.is_early_departure,
                "month_locked": record.month_locked,
                "location_id": str(record.location_id) if record.location_id else None,
            }
        )
    return rows


def summary_kpis(rows: list[dict]) -> dict:
    return {
        "row_count": len(rows),
        "present": sum(1 for r in rows if r["check_in_at"]),
        "on_leave": sum(1 for r in rows if r["status"] == "on_leave"),
        "missing_checkout": sum(1 for r in rows if r["status"] == "missing_checkout"),
        "late": sum(1 for r in rows if r["is_late"]),
        "early_departure": sum(1 for r in rows if r["is_early_departure"]),
        "corrected": sum(1 for r in rows if r["status"] == "corrected"),
    }


def period_bounds(kind: str, anchor: date) -> tuple[date, date]:
    kind = kind.lower()
    if kind == "daily":
        return anchor, anchor
    if kind == "weekly":
        start = anchor - timedelta(days=anchor.weekday())
        return start, start + timedelta(days=6)
    if kind == "monthly":
        start = anchor.replace(day=1)
        if start.month == 12:
            end = start.replace(year=start.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = start.replace(month=start.month + 1, day=1) - timedelta(days=1)
        return start, end
    raise ValueError("kind must be daily|weekly|monthly")


def build_xlsx(rows: list[dict], *, title: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Attendance"
    ws.append([title])
    headers = [
        "work_date",
        "employee_code",
        "full_name",
        "status",
        "check_in_at",
        "check_out_at",
        "worked_minutes",
        "is_late",
        "is_early_departure",
        "month_locked",
    ]
    ws.append(headers)
    for r in rows:
        ws.append([r.get(h) for h in headers])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_pdf(rows: list[dict], *, title: str, kpis: dict) -> bytes:
    """Minimal PDF without WeasyPrint system deps — simple text PDF."""
    lines = [
        title,
        f"Rows: {kpis.get('row_count', 0)}  Present: {kpis.get('present', 0)}  "
        f"Leave: {kpis.get('on_leave', 0)}  Late: {kpis.get('late', 0)}",
        "",
    ]
    for r in rows[:200]:
        lines.append(
            f"{r['work_date']}  {r.get('employee_code','')}  {r.get('status','')}  "
            f"in={r.get('check_in_at') or '-'}  out={r.get('check_out_at') or '-'}"
        )
    if len(rows) > 200:
        lines.append(f"... and {len(rows) - 200} more rows")
    return _simple_pdf("\n".join(lines))


def _simple_pdf(text: str) -> bytes:
    # Very small single-page PDF writer (Helvetica).
    content_lines = []
    y = 800
    for raw in text.splitlines()[:60]:
        safe = raw.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")[:110]
        content_lines.append(f"BT /F1 9 Tf 40 {y} Td ({safe}) Tj ET")
        y -= 12
        if y < 40:
            break
    stream = "\n".join(content_lines).encode("latin-1", errors="replace")
    objects: list[bytes] = []
    objects.append(b"1 0 obj<< /Type /Catalog /Pages 2 0 R >>endobj\n")
    objects.append(b"2 0 obj<< /Type /Pages /Kids [3 0 R] /Count 1 >>endobj\n")
    objects.append(
        b"3 0 obj<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources<< /Font<< /F1 5 0 R >> >> >>endobj\n"
    )
    objects.append(
        f"4 0 obj<< /Length {len(stream)} >>stream\n".encode() + stream + b"\nendstream\nendobj\n"
    )
    objects.append(b"5 0 obj<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>endobj\n")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(
        f"trailer<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    )
    return bytes(out)
