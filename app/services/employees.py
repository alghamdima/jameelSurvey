import csv
import hashlib
import io
from pathlib import Path
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session
from app.core.security import normalize_employee_id, valid_employee_id
from app.models import Employee, EmployeeImport

HEADERS = {"employee no.", "employee no", "employee_id", "employee id", "employee number",
           "رقم الموظف", "الرقم الوظيفي"}

def read_employee_csv(path: Path) -> tuple[set[str], str, int]:
    return parse_employee_csv(path.read_bytes())

def parse_employee_csv(raw: bytes) -> tuple[set[str], str, int]:
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("Employee CSV exceeds 20 MB")
    text = raw.decode("utf-8-sig")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = csv.reader(io.StringIO(text), dialect)
    header = next(rows, None)
    if not header:
        raise ValueError("Empty employee CSV")
    matches = [i for i, h in enumerate(header) if h.strip().lower() in HEADERS]
    if len(matches) != 1:
        raise ValueError("CSV must contain one recognized employee number column")
    column = matches[0]
    ids, duplicates = set(), 0
    for line, row in enumerate(rows, start=2):
        if not row or not any(v.strip() for v in row):
            continue
        if column >= len(row):
            raise ValueError(f"Missing employee number at CSV row {line}")
        value = normalize_employee_id(row[column])
        if not valid_employee_id(value):
            raise ValueError(f"Invalid employee number at CSV row {line}; use digit strings, not Excel formulas")
        if value in ids:
            duplicates += 1
        ids.add(value)
    if not ids:
        raise ValueError("CSV contains no employee numbers")
    return ids, hashlib.sha256(raw).hexdigest(), duplicates

def import_employee_csv(db: Session, path: Path) -> dict:
    ids, digest, duplicates = read_employee_csv(path)
    # One transaction replaces the active roster, preserving history and leading zeros.
    db.execute(update(Employee).values(active=False))
    ordered = sorted(ids)
    for offset in range(0, len(ordered), 250):
        stmt = insert(Employee).values([{"employee_id": x, "active": True} for x in ordered[offset:offset + 250]])
        db.execute(stmt.on_conflict_do_update(index_elements=["employee_id"], set_={"active": True}))
    db.execute(delete(EmployeeImport))
    db.add(EmployeeImport(id=1, fingerprint=digest, row_count=len(ids)))
    db.commit()
    return {"active_employees": len(ids), "duplicates_ignored": duplicates}

def is_active_employee(db: Session, employee_id: str) -> bool:
    return db.scalar(select(Employee.employee_id).where(
        Employee.employee_id == employee_id, Employee.active.is_(True))) is not None