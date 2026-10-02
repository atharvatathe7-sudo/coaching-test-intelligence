"""
Database backup operations (run from the project root, as the service
user). Paths come from COACHING_DB_PATH and COACHING_BACKUP_DIR.

  python scripts/backup.py create --kind nightly   # online backup + manifest
  python scripts/backup.py list
  python scripts/backup.py verify PATH             # restore to temp + checks
  python scripts/backup.py test-restore            # verify the newest backup
  python scripts/backup.py prune                   # apply retention
  python scripts/backup.py restore PATH --yes      # replace the live DB
                                                   # (stop the service first)

verify / test-restore exit with status 1 if any check fails, so a
scheduled run can alert.
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.app import config  # noqa: E402
from backend.app.database.connection import DATABASE_PATH  # noqa: E402
from backend.app.ops import backup  # noqa: E402


def backup_dir(args) -> Path:
    directory = args.backup_dir or config.BACKUP_DIR
    if not directory:
        raise SystemExit("Set COACHING_BACKUP_DIR (or pass --backup-dir).")
    return Path(directory)


def print_result(result) -> int:
    print(json.dumps(
        {
            "backup": str(result.backup),
            "ok": result.ok,
            "checks": result.checks,
            "problems": result.problems,
        },
        indent=2,
        default=str,
    ))
    return 0 if result.ok else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Database backups")
    parser.add_argument("--backup-dir", help="overrides COACHING_BACKUP_DIR")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create")
    p.add_argument("--kind", default="manual",
                   help="nightly | pre-migration | manual | ...")
    sub.add_parser("list")
    p = sub.add_parser("verify")
    p.add_argument("path")
    sub.add_parser("test-restore")
    sub.add_parser("prune")
    p = sub.add_parser("restore")
    p.add_argument("path")
    p.add_argument("--yes", action="store_true",
                   help="confirm the service is stopped and the live DB may be replaced")

    args = parser.parse_args(argv)

    if args.command == "create":
        path = backup.create_backup(DATABASE_PATH, backup_dir(args), args.kind)
        print(path)
        return 0

    if args.command == "list":
        for when, kind, path in backup.list_backups(backup_dir(args)):
            print(f"{when.isoformat()}Z\t{kind}\t{path.name}")
        return 0

    if args.command == "verify":
        return print_result(backup.verify_backup(Path(args.path)))

    if args.command == "test-restore":
        backups = backup.list_backups(backup_dir(args))
        if not backups:
            print("No backups found.", file=sys.stderr)
            return 1
        return print_result(backup.verify_backup(backups[0][2]))

    if args.command == "prune":
        for path in backup.prune_backups(backup_dir(args)):
            print(f"removed {path.name}")
        return 0

    if args.command == "restore":
        if not args.yes:
            raise SystemExit(
                "Stop the API service first, then re-run with --yes. The "
                "current database is moved aside, not deleted."
            )
        moved = backup.restore_backup(Path(args.path), DATABASE_PATH)
        print(f"Restored {args.path} -> {DATABASE_PATH}")
        if moved:
            print(f"Previous database kept at {moved}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
