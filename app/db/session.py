from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from app.core.config import settings

# ضمان وجود مجلد البيانات
db_path = settings.DATABASE_URL.replace("sqlite:///", "")
if db_path.startswith("./") or not db_path.startswith("/"):
    full_path = (Path(__file__).resolve().parent.parent.parent / db_path).resolve()
    full_path.parent.mkdir(parents=True, exist_ok=True)
else:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=settings.DEBUG
)

# تفعيل وضع WAL و Foreign Keys في SQLite لتحقيق أعلى أداء وأمان في المعاملات المتزامنة
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
