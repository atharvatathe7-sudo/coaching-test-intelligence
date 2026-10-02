"""
Explicit, safe database preparation at startup.

Only used when migrations are applied automatically (local mode). The
rules, in order:

  * A database at head is left alone.
  * A missing or empty database is created by running the migrations.
  * A database from an older revision gets a safety backup first; if the
    backup cannot be made and checked, nothing is changed.
  * Anything else is refused and left untouched: a database with tables
    but no migration history, or one whose revision this code does not
    know (for example, written by a newer version of the application).

Nothing here deletes, resets or recreates an existing database.
"""

import logging
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from .. import config as settings
from ..ops import backup
from .schema_check import (
    ALEMBIC_INI,
    expected_revision,
    known_revisions,
    require_current_schema,
)

logger = logging.getLogger("coaching.startup")


class StartupError(RuntimeError):
    """Startup was refused; the message says what to do."""


def _inspect(database: Path) -> tuple[list[str], str | None]:
    """
    Table names and recorded revision, read through a read-only
    connection so that a database we may refuse is not modified even by
    the journal-mode pragma the application normally sets.
    """
    if not database.exists():
        return [], None

    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        revision = None
        if "alembic_version" in tables:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
            revision = row[0] if row else None
        return tables, revision
    finally:
        connection.close()


def _upgrade_to_head() -> None:
    alembic_config = Config(str(ALEMBIC_INI))
    # Leave the application's logging alone.
    alembic_config.attributes["configure_logger"] = False
    command.upgrade(alembic_config, "head")


def _safety_backup(database: Path, revision: str) -> Path:
    if not settings.BACKUP_DIR:
        raise StartupError(
            "The database needs a migration but no backup directory is "
            "configured, so it was left unchanged."
        )

    try:
        target = backup.create_backup(
            database, Path(settings.BACKUP_DIR), "pre-migration"
        )
        connection = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchall()
        finally:
            connection.close()
        if [row[0] for row in integrity] != ["ok"]:
            raise StartupError("the backup failed its integrity check")
        if not backup.manifest_path(target).exists():
            raise StartupError("the backup has no manifest")
    except (backup.BackupError, OSError, sqlite3.Error, StartupError) as error:
        raise StartupError(
            f"Could not make a safety backup before migrating ({error}); "
            "the database was left unchanged."
        ) from error

    logger.info("Safety backup before migration from %s: %s", revision, target.name)
    return target


def prepare_database(engine, database: Path | None = None) -> str:
    """
    Bring the database to the expected revision, or refuse.
    Returns "current", "created" or "upgraded".
    """
    database = Path(database or settings.DATABASE_PATH)

    try:
        tables, revision = _inspect(database)
    except sqlite3.Error as error:
        raise StartupError(
            f"The database cannot be opened ({type(error).__name__}). "
            "It was not modified."
        ) from error

    if revision == expected_revision():
        return "current"

    if revision is None:
        if tables:
            raise StartupError(
                "The database file contains tables but no migration history, "
                "so it will not be changed automatically. Restore a backup or "
                "point COACHING_DB_PATH at the right file."
            )
        action = "created"
    elif revision not in known_revisions():
        raise StartupError(
            f"The database is at schema revision {revision}, which this "
            "version of the application does not know (it may have been "
            "written by a newer version). It was not modified."
        )
    else:
        _safety_backup(database, revision)
        action = "upgraded"

    try:
        _upgrade_to_head()
    except Exception as error:
        raise StartupError(
            f"The database migration failed ({type(error).__name__}); "
            "startup was stopped. "
            + (
                "A safety backup was taken just before it."
                if action == "upgraded"
                else ""
            )
        ) from error

    # Fail closed: the result must be exactly the expected revision.
    require_current_schema(engine)
    logger.info("Database %s at revision %s", action, expected_revision())
    return action


def prepare_local_runtime(engine) -> str:
    """Create the data directory layout, then prepare the database."""
    try:
        settings.ensure_data_dirs()
    except OSError as error:
        raise StartupError(
            f"Cannot create the application data directories ({error}). "
            "Nothing was changed."
        ) from error

    return prepare_database(engine)
