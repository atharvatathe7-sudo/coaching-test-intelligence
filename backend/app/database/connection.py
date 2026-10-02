from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .. import config


# Re-exported for existing callers. Every path is decided in config.py.
PROJECT_ROOT = config.PROJECT_ROOT
DATABASE_PATH = config.DATABASE_PATH
DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

# Pragmas applied to every SQLite connection. foreign_keys must be set
# per connection: SQLite does not enforce foreign keys otherwise.
SQLITE_PRAGMAS = (
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA synchronous=NORMAL",
)


def apply_sqlite_pragmas(dbapi_connection, connection_record=None):
    cursor = dbapi_connection.cursor()
    try:
        for pragma in SQLITE_PRAGMAS:
            cursor.execute(pragma)
    finally:
        cursor.close()


def make_engine(url: str = DATABASE_URL, **kwargs):
    """
    Engine with the application's SQLite settings.

    hide_parameters keeps SQL parameter values (student names, roll
    numbers, answers) out of exception messages and therefore out of logs.
    """

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        hide_parameters=True,
        **kwargs,
    )
    event.listen(engine, "connect", apply_sqlite_pragmas)
    return engine


engine = make_engine()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Deterministic constraint/index names, required for SQLite batch-mode
# migrations and for comparing models with migrations.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def get_db():
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()
