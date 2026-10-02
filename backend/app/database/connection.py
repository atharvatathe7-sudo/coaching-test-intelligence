import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# Project root:
# coaching-test-intelligence/
PROJECT_ROOT = Path(__file__).resolve().parents[3]

# SQLite database. Defaults to data/coaching.db; set COACHING_DB_PATH
# to use a different file (the test suite uses this for a temp database).
DATABASE_PATH = Path(
    os.environ.get(
        "COACHING_DB_PATH",
        PROJECT_ROOT / "data" / "coaching.db",
    )
)
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"


engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
