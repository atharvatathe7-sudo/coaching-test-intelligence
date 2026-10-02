"""
Start the application in local mode: one institute-owned computer, the
browser on the same machine.

    python scripts/run_local.py [--env-file PATH]

Applies migrations (with a safety backup when the database already has
data), serves the built frontend and the API on COACHING_HOST:COACHING_PORT
(default 127.0.0.1:8000, reachable only from this computer). To let other
computers on the network connect, set COACHING_HOST=0.0.0.0 explicitly;
see README "Local Prototype Setup".

Settings come from the environment; an optional --env-file of KEY=VALUE
lines (for example <data dir>/config/local.env) fills in any not already
set. Stop with Ctrl+C.

    python scripts/run_local.py --migrate-only

creates the data directory and applies migrations, then exits (use it
before scripts/manage.py on a brand-new installation).
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def load_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--env-file", help="KEY=VALUE settings file")
    parser.add_argument(
        "--migrate-only",
        action="store_true",
        help="prepare the database and exit without starting the server",
    )
    args = parser.parse_args()

    if args.env_file:
        load_env_file(Path(args.env_file))

    os.environ.setdefault("COACHING_APP_MODE", "local")

    try:
        from backend.app import config
    except RuntimeError as error:
        raise SystemExit(f"Configuration error: {error}")

    if not config.IS_LOCAL:
        raise SystemExit(
            f"run_local.py is for local mode, but the mode is {config.APP_MODE!r}. "
            "Unset COACHING_APP_MODE (or set it to 'local')."
        )

    print(f"Data directory : {config.DATA_DIR}")
    print(f"Database       : {config.DATABASE_PATH}")
    print(f"Address        : http://{config.HOST}:{config.PORT}/")

    if config.HOST not in LOOPBACK:
        print(
            "WARNING: bound to a non-loopback address. Other computers on the "
            "network can reach this app over plain, unencrypted HTTP.",
            file=sys.stderr,
        )

    if args.migrate_only:
        from backend.app.database.connection import engine
        from backend.app.database.startup import StartupError, prepare_local_runtime

        try:
            print(f"Database {prepare_local_runtime(engine)}.")
        except StartupError as error:
            raise SystemExit(f"Refused: {error}")
        return

    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=config.HOST,
        port=config.PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
