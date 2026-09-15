from pathlib import Path
from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from app.core.config import settings, BASE_DIR

url = make_url(settings.DATABASE_URL)
if url.get_backend_name() != "sqlite":
    raise ValueError("This deployment supports SQLite databases only")
if url.database and url.database != ":memory:":
    db_path = Path(url.database)
    if not db_path.is_absolute():
        db_path = BASE_DIR / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    url = url.set(database=str(db_path.resolve()))
    settings.DATABASE_URL = url.render_as_string(hide_password=False)

engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, echo=settings.DEBUG)

@event.listens_for(engine, "connect")
def set_sqlite_pragma(connection, _):
    cursor = connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

class Base(DeclarativeBase):
    pass

def get_db():
    with SessionLocal() as db:
        yield db