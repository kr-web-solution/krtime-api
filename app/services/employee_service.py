"""Employee CRUD helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.core.security import generate_enrollment_code, hash_password
from app.models import (
    Employee,
    EmployeeLocation,
    EnrollmentCode,
    EnrollmentCodeStatus,
    Location,
    User,
    UserRole,
)
from app.schemas.employees import EmployeeCreate, EmployeeOut, EmployeeUpdate, EnrollmentCodeOut
from app.services.audit import write_audit
from app.services import shift_service


def _to_out(db: Session, employee: Employee) -> EmployeeOut:
    location_ids = [link.location_id for link in employee.location_links]
    primary = next((link.location_id for link in employee.location_links if link.is_primary), None)
    assignment = shift_service.current_assignment(db, employee.id)
    return EmployeeOut(
        id=employee.id,
        user_id=employee.user_id,
        employee_code=employee.employee_code,
        full_name=employee.user.full_name,
        email=employee.user.email,
        phone=employee.phone,
        job_title=employee.job_title,
        department_id=employee.department_id,
        is_active=employee.is_active,
        notes=employee.notes,
        location_ids=location_ids,
        primary_location_id=primary,
        current_shift_id=assignment.shift_id if assignment else None,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


def _load_employee(db: Session, employee_id: UUID) -> Employee:
    employee = db.scalar(
        select(Employee)
        .options(selectinload(Employee.user), selectinload(Employee.location_links))
        .where(Employee.id == employee_id)
    )
    if employee is None:
        raise AppError("employee_not_found", "Employee not found", status_code=404)
    return employee


def _set_locations(
    db: Session,
    employee: Employee,
    location_ids: list[UUID],
    primary_location_id: UUID | None,
) -> None:
    if primary_location_id and primary_location_id not in location_ids:
        raise AppError("invalid_location", "Primary location must be in assigned locations")

    for loc_id in location_ids:
        if db.get(Location, loc_id) is None:
            raise AppError("location_not_found", f"Location {loc_id} not found", status_code=404)

    employee.location_links.clear()
    db.flush()
    for loc_id in location_ids:
        employee.location_links.append(
            EmployeeLocation(
                location_id=loc_id,
                is_primary=(loc_id == primary_location_id)
                or (primary_location_id is None and loc_id == location_ids[0]),
            )
        )


def create_employee(
    db: Session,
    payload: EmployeeCreate,
    *,
    actor: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> tuple[EmployeeOut, EnrollmentCodeOut | None]:
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError("email_taken", "Email is already registered", status_code=409)
    if db.scalar(select(Employee).where(Employee.employee_code == payload.employee_code)):
        raise AppError("employee_code_taken", "Employee code already exists", status_code=409)

    temp_password = payload.temporary_password or generate_enrollment_code(12)
    user = User(
        email=email,
        password_hash=hash_password(temp_password),
        full_name=payload.full_name.strip(),
        role=UserRole.EMPLOYEE.value,
        is_active=True,
    )
    db.add(user)
    db.flush()

    employee = Employee(
        user_id=user.id,
        employee_code=payload.employee_code.strip(),
        department_id=payload.department_id,
        phone=payload.phone,
        job_title=payload.job_title,
        is_active=True,
    )
    db.add(employee)
    db.flush()

    if payload.location_ids:
        _set_locations(db, employee, payload.location_ids, payload.primary_location_id)

    enrollment_out: EnrollmentCodeOut | None = None
    if payload.create_enrollment_code:
        code = EnrollmentCode(
            employee_id=employee.id,
            code=generate_enrollment_code(8),
            status=EnrollmentCodeStatus.ACTIVE.value,
            expires_at=datetime.now(UTC) + timedelta(hours=payload.enrollment_code_hours),
            created_by_user_id=actor.id,
        )
        db.add(code)
        db.flush()
        enrollment_out = EnrollmentCodeOut.model_validate(code)

    write_audit(
        db,
        actor_user_id=actor.id,
        action="employee.create",
        entity_type="employee",
        entity_id=str(employee.id),
        after={"employee_code": employee.employee_code, "email": email},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    if payload.shift_id is not None:
        shift_service.assign_shift(
            db,
            employee_id=employee.id,
            shift_id=payload.shift_id,
            effective_from=date.today(),
            actor=actor,
        )

    employee = _load_employee(db, employee.id)
    return _to_out(db, employee), enrollment_out


def list_employees(db: Session, *, active_only: bool = False) -> list[EmployeeOut]:
    stmt = select(Employee).options(
        selectinload(Employee.user),
        selectinload(Employee.location_links),
    )
    if active_only:
        stmt = stmt.where(Employee.is_active.is_(True))
    rows = db.scalars(stmt.order_by(Employee.employee_code)).all()
    return [_to_out(db, row) for row in rows]


def get_employee(db: Session, employee_id: UUID) -> EmployeeOut:
    return _to_out(db, _load_employee(db, employee_id))


def update_employee(
    db: Session,
    employee_id: UUID,
    payload: EmployeeUpdate,
    *,
    actor: User,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> EmployeeOut:
    employee = _load_employee(db, employee_id)
    before = {"is_active": employee.is_active, "full_name": employee.user.full_name}

    if payload.full_name is not None:
        employee.user.full_name = payload.full_name.strip()
    if payload.phone is not None:
        employee.phone = payload.phone
    if payload.job_title is not None:
        employee.job_title = payload.job_title
    if payload.department_id is not None:
        employee.department_id = payload.department_id
    if payload.is_active is not None:
        employee.is_active = payload.is_active
        employee.user.is_active = payload.is_active
    if payload.notes is not None:
        employee.notes = payload.notes
    if payload.location_ids is not None:
        _set_locations(db, employee, payload.location_ids, payload.primary_location_id)

    db.add(employee)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="employee.update",
        entity_type="employee",
        entity_id=str(employee.id),
        before=before,
        after={"is_active": employee.is_active, "full_name": employee.user.full_name},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    if payload.shift_id is not None:
        shift_service.assign_shift(
            db,
            employee_id=employee_id,
            shift_id=payload.shift_id,
            effective_from=date.today(),
            actor=actor,
        )

    return _to_out(db, _load_employee(db, employee_id))


def create_enrollment_code_for_employee(
    db: Session,
    employee_id: UUID,
    *,
    actor: User,
    hours: int = 72,
) -> EnrollmentCodeOut:
    employee = _load_employee(db, employee_id)
    # Revoke prior active codes
    active = db.scalars(
        select(EnrollmentCode).where(
            EnrollmentCode.employee_id == employee.id,
            EnrollmentCode.status == EnrollmentCodeStatus.ACTIVE.value,
        )
    ).all()
    for row in active:
        row.status = EnrollmentCodeStatus.REVOKED.value
        db.add(row)

    code = EnrollmentCode(
        employee_id=employee.id,
        code=generate_enrollment_code(8),
        status=EnrollmentCodeStatus.ACTIVE.value,
        expires_at=datetime.now(UTC) + timedelta(hours=hours),
        created_by_user_id=actor.id,
    )
    db.add(code)
    write_audit(
        db,
        actor_user_id=actor.id,
        action="employee.enrollment_code",
        entity_type="enrollment_code",
        entity_id=str(employee.id),
    )
    db.commit()
    db.refresh(code)
    return EnrollmentCodeOut.model_validate(code)
