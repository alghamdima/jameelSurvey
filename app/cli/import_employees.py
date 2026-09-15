import argparse
from pathlib import Path
from app.db.session import SessionLocal
from app.services.employees import import_employee_csv

def main():
    parser = argparse.ArgumentParser(description="Atomically replace the active employee roster")
    parser.add_argument("--file", required=True, type=Path)
    args = parser.parse_args()
    with SessionLocal() as db:
        result = import_employee_csv(db, args.file)
    print(f"Active employees: {result['active_employees']}; duplicate rows ignored: {result['duplicates_ignored']}")

if __name__ == "__main__":
    main()