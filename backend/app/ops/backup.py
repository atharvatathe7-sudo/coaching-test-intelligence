"""
SQLite backups, restore and restore verification.

Backups use SQLite's online backup API, which produces a consistent
snapshot while the application is running (a raw file copy is not safe
in WAL mode: recent writes may still be in the -wal file).

Each backup is `coaching-<UTC timestamp>-<kind>.db` with a manifest
(`.json`) recording the schema revision, row counts of the key tables
and a SHA-256 of the file. Files are created with mode 0600.

"A backup exists" is not enough: verify_backup() restores the file into
a temporary directory and checks integrity, foreign keys, schema
revision, the health check and the recorded row counts.
"""

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config

logger = logging.getLogger(__name__)

# Tables whose row counts are recorded and re-checked after restore.
KEY_TABLES = (
    "institutes",
    "users",
    "batches",
    "students",
    "tests",
    "questions",
    "student_answers",
    "test_results",
    "teacher_actions",
    "audit_log",
)

NAME_PREFIX = "coaching-"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

# Retention for nightly backups: newest per day for the most recent
# DAILY_KEEP days, plus newest per ISO week for WEEKLY_KEEP weeks.
DAILY_KEEP = 14
WEEKLY_KEEP = 8
# Backups taken before migrations / destructive operations are kept by age.
PRE_OPERATION_KEEP_DAYS = 14


class BackupError(RuntimeError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    existing = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return {
        table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        for table in KEY_TABLES
        if table in existing
    }


def _revision(connection: sqlite3.Connection) -> str | None:
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.DatabaseError:
        return None
    return row[0] if row else None


def manifest_path(backup: Path) -> Path:
    return backup.with_suffix(".json")


def _online_copy(source: Path, destination: Path) -> None:
    """Consistent copy via SQLite's backup API."""
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


def create_backup(
    database: Path,
    backup_dir: Path,
    kind: str = "manual",
) -> Path:
    """Write a backup and its manifest; return the backup path."""
    database = Path(database)
    backup_dir = Path(backup_dir)

    if not database.exists():
        raise BackupError(f"Database {database} does not exist.")

    kind = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in kind)
    backup_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)

    stamp = _utcnow().strftime(TIMESTAMP_FORMAT)
    target = backup_dir / f"{NAME_PREFIX}{stamp}-{kind}.db"
    counter = 1
    while target.exists():
        target = backup_dir / f"{NAME_PREFIX}{stamp}-{kind}-{counter}.db"
        counter += 1

    partial = target.with_suffix(".partial")
    # Create the file with restrictive permissions before writing data.
    os.close(os.open(partial, os.O_CREAT | os.O_WRONLY, 0o600))

    try:
        _online_copy(database, partial)
        os.chmod(partial, 0o600)

        connection = sqlite3.connect(partial)
        try:
            counts = _counts(connection)
            revision = _revision(connection)
        finally:
            connection.close()

        os.replace(partial, target)
    except Exception:
        partial.unlink(missing_ok=True)
        raise

    manifest = {
        "file": target.name,
        "kind": kind,
        "created_at": _utcnow().isoformat(),
        "schema_revision": revision,
        "row_counts": counts,
        "sha256": _sha256(target),
        "size_bytes": target.stat().st_size,
    }
    path = manifest_path(target)
    path.write_text(json.dumps(manifest, indent=2))
    os.chmod(path, 0o600)

    logger.info("Backup written: %s", target.name)
    return target


@dataclass
class VerifyResult:
    backup: Path
    ok: bool = True
    checks: dict = field(default_factory=dict)
    problems: list = field(default_factory=list)

    def fail(self, problem: str) -> None:
        self.ok = False
        self.problems.append(problem)


def check_database_file(path: Path, expected_counts: dict | None = None) -> VerifyResult:
    """Integrity, foreign keys, revision, health and (optionally) counts."""
    from sqlalchemy import create_engine

    from ..database.schema_check import expected_revision, schema_status

    result = VerifyResult(backup=Path(path))
    connection = sqlite3.connect(path)
    try:
        integrity = connection.execute("PRAGMA integrity_check").fetchall()
        result.checks["integrity_check"] = [row[0] for row in integrity]
        if [row[0] for row in integrity] != ["ok"]:
            result.fail("PRAGMA integrity_check did not return ok.")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        result.checks["foreign_key_violations"] = len(violations)
        if violations:
            result.fail(f"{len(violations)} foreign-key violation(s).")

        revision = _revision(connection)
        result.checks["schema_revision"] = revision
        if revision != expected_revision():
            result.fail(
                f"Schema revision {revision!r} does not match the code's "
                f"{expected_revision()!r}."
            )

        counts = _counts(connection)
        result.checks["row_counts"] = counts
        if expected_counts is not None and counts != expected_counts:
            result.fail("Row counts differ from the backup manifest.")
    finally:
        connection.close()

    engine = create_engine(f"sqlite:///{path}")
    try:
        status = schema_status(engine)
    finally:
        engine.dispose()
    result.checks["health"] = status
    if status != "ok":
        result.fail(f"Health check reports {status!r}.")

    return result


def verify_backup(backup: Path) -> VerifyResult:
    """
    Restore the backup into a temporary directory and check it:
    checksum, integrity, foreign keys, revision, health, row counts.
    The original backup file is never opened for writing.
    """
    backup = Path(backup)
    manifest_file = manifest_path(backup)

    if not backup.exists():
        result = VerifyResult(backup=backup)
        result.fail("Backup file does not exist.")
        return result

    manifest = None
    if manifest_file.exists():
        manifest = json.loads(manifest_file.read_text())

    with tempfile.TemporaryDirectory(prefix="coaching-restore-test-") as tmp:
        restored = Path(tmp) / "restored.db"
        _online_copy(backup, restored)

        result = check_database_file(
            restored,
            expected_counts=manifest["row_counts"] if manifest else None,
        )
        result.backup = backup

    if manifest is None:
        result.fail("Manifest is missing.")
    elif _sha256(backup) != manifest["sha256"]:
        result.fail("Checksum does not match the manifest (file changed).")
    result.checks["checksum_matches_manifest"] = (
        manifest is not None and _sha256(backup) == manifest["sha256"]
    )

    return result


def restore_backup(backup: Path, target: Path) -> Path | None:
    """
    Replace the database at `target` with `backup` (stop the service
    first). The backup is verified before anything is touched. The
    current database, and its -wal/-shm files, are moved aside, not
    deleted. Returns the path of the moved-aside database (if any).
    """
    backup, target = Path(backup), Path(target)

    result = verify_backup(backup)
    if not result.ok:
        raise BackupError(
            "Refusing to restore an unverified backup: " + "; ".join(result.problems)
        )

    stamp = _utcnow().strftime(TIMESTAMP_FORMAT)
    moved = None

    for suffix in ("", "-wal", "-shm"):
        current = Path(f"{target}{suffix}")
        if current.exists():
            aside = Path(f"{target}.pre-restore-{stamp}{suffix}")
            os.replace(current, aside)
            if suffix == "":
                moved = aside

    partial = Path(f"{target}.restoring")
    os.close(os.open(partial, os.O_CREAT | os.O_WRONLY, 0o600))
    _online_copy(backup, partial)
    os.replace(partial, target)
    os.chmod(target, 0o600)

    after = check_database_file(target)
    if not after.ok:
        raise BackupError("Restored database failed checks: " + "; ".join(after.problems))

    return moved


def list_backups(backup_dir: Path) -> list[tuple[datetime, str, Path]]:
    """(timestamp, kind, path) for every backup, newest first."""
    found = []
    for path in Path(backup_dir).glob(f"{NAME_PREFIX}*.db"):
        stem = path.stem[len(NAME_PREFIX):]
        stamp, _, kind = stem.partition("-")
        try:
            when = datetime.strptime(stamp, TIMESTAMP_FORMAT)
        except ValueError:
            continue
        found.append((when, kind, path))
    return sorted(found, key=lambda item: item[0], reverse=True)


def select_for_pruning(
    backups: list[tuple[datetime, str, Path]],
    now: datetime | None = None,
) -> list[Path]:
    """
    Backups to delete under the retention policy:
    - nightly: keep the newest per day for the DAILY_KEEP most recent
      days, and the newest per ISO week for the WEEKLY_KEEP most recent
      weeks;
    - other kinds (pre-migration, pre-operation, manual): keep for
      PRE_OPERATION_KEEP_DAYS;
    - the newest backup of all is always kept.
    """
    now = now or _utcnow()
    keep: set[Path] = set()

    if backups:
        keep.add(backups[0][2])

    nightly = [b for b in backups if b[1].startswith("nightly")]

    days: dict = {}
    weeks: dict = {}
    for when, _, path in nightly:  # newest first
        days.setdefault(when.date(), path)
        weeks.setdefault(tuple(when.isocalendar()[:2]), path)

    keep.update(list(days.values())[:DAILY_KEEP])
    keep.update(list(weeks.values())[:WEEKLY_KEEP])

    cutoff = now - timedelta(days=PRE_OPERATION_KEEP_DAYS)
    for when, kind, path in backups:
        if not kind.startswith("nightly") and when >= cutoff:
            keep.add(path)

    return [path for _, _, path in backups if path not in keep]


def prune_backups(backup_dir: Path) -> list[Path]:
    removed = select_for_pruning(list_backups(backup_dir))
    for path in removed:
        path.unlink(missing_ok=True)
        manifest_path(path).unlink(missing_ok=True)
    return removed


def pre_operation_backup(reason: str) -> Path | None:
    """
    Back up the live database before a destructive admin operation.

    Returns None when no backup directory is configured (development).
    Raises BackupError if the backup fails: the operation must then not
    proceed.
    """
    if not config.BACKUP_DIR:
        return None

    from ..database.connection import DATABASE_PATH

    try:
        return create_backup(DATABASE_PATH, Path(config.BACKUP_DIR), f"pre-{reason}")
    except Exception as exc:
        logger.error("Pre-operation backup failed (%s)", type(exc).__name__)
        raise BackupError("The safety backup before this change failed.") from exc
