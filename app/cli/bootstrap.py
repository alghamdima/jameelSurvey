from pathlib import Path
from app.core.config import settings
from app.core.auth import ensure_admin_user_exists
from app.db.session import SessionLocal
from app.services.employees import import_employee_csv

def main():
    settings.validate_runtime()
    with SessionLocal() as db:
        ensure_admin_user_exists(db)
        if settings.EMPLOYEE_CSV_PATH and Path(settings.EMPLOYEE_CSV_PATH).is_file():
            result = import_employee_csv(db, Path(settings.EMPLOYEE_CSV_PATH))
            print(f"Employee roster ready: {result['active_employees']} active employees")

if __name__ == "__main__":
    main()