"""
Database schema/revision checks shared by startup, /api/health and the
backup verification script.

The application never creates or upgrades the schema itself: migrations
are applied explicitly with `alembic upgrade head`.
"""

from functools import lru_cache

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .connection import PROJECT_ROOT

ALEMBIC_INI = PROJECT_ROOT / "alembic.ini"


@lru_cache(maxsize=1)
def expected_revision() -> str:
    """The head revision of the migration scripts shipped with the code."""
    config = Config(str(ALEMBIC_INI))
    return ScriptDirectory.from_config(config).get_current_head()


def current_revision(connection) -> str | None:
    """The revision recorded in the database, or None if unmigrated."""
    has_table = connection.execute(
        text(
            "SELECT 1 FROM sqlite_master "
            "WHERE type = 'table' AND name = 'alembic_version'"
        )
    ).first()

    if has_table is None:
        return None

    return connection.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar()


def schema_status(engine) -> str:
    """
    One of:
      "ok"           - database reachable and at the expected revision
      "unavailable"  - cannot query the database
      "not_migrated" - no migrations applied (run alembic upgrade head)
      "outdated"     - a different revision than the code expects
    """

    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar()
            revision = current_revision(connection)
    except SQLAlchemyError:
        return "unavailable"

    if revision is None:
        return "not_migrated"

    if revision != expected_revision():
        return "outdated"

    return "ok"


STATUS_MESSAGES = {
    "unavailable": "The database cannot be opened.",
    "not_migrated": (
        "The database has no schema. Run `alembic upgrade head` "
        "before starting the application."
    ),
    "outdated": (
        "The database schema is not at the expected revision. "
        "Back up the database, then run `alembic upgrade head`."
    ),
}


def require_current_schema(engine) -> None:
    """Raise with a clear message unless the schema is at head."""
    status = schema_status(engine)

    if status != "ok":
        raise RuntimeError(STATUS_MESSAGES[status])
