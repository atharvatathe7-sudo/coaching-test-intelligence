"""
Application settings, read from environment variables. This is the one
place that decides the mode, the data directory and every path derived
from it; other modules import the results instead of re-reading the
environment.

COACHING_APP_MODE     "development" (default), "local" or "production".
                      COACHING_ENV is accepted as the older name.
                        development  source-tree defaults, Vite dev server
                        local        one institute-owned computer: data in
                                     the data directory, migrations applied
                                     at startup, built frontend served by
                                     FastAPI, plain-HTTP cookies
                        production   server deployment behind a TLS proxy
COACHING_DATA_DIR     application data directory (see below)
COACHING_DB_PATH      SQLite file; overrides the path inside the data dir
COACHING_BACKUP_DIR   backup directory; overrides <data dir>/backups
                      (required in production)
COACHING_HOST         address the local launcher binds (default 127.0.0.1)
COACHING_PORT         port the local launcher binds (default 8000)
COACHING_COOKIE_SECURE  "1" sends the session cookie only over HTTPS.
                      Always on in production; off by default otherwise.
COACHING_SERVE_FRONTEND  "1"/"0" overrides whether FastAPI serves the
                      built frontend (default: on in local mode only)
COACHING_FRONTEND_DIST   built frontend directory (default frontend/dist)
COACHING_AUTO_MIGRATE  "1"/"0" overrides whether startup applies
                      migrations (default: on in local mode only)

Data directory layout (created on demand):
  data/ backups/ uploads/ logs/ exports/ config/
Default location: development uses the source tree (data/coaching.db);
local/production use %LOCALAPPDATA%\\CoachingIntel on Windows and
$XDG_DATA_HOME/CoachingIntel (~/.local/share) elsewhere.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODES = ("development", "local", "production")
DATA_SUBDIRS = ("data", "backups", "uploads", "logs", "exports", "config")


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _text(name: str) -> str | None:
    return os.environ.get(name, "").strip() or None


def _default_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "CoachingIntel"
        return Path.home() / "AppData" / "Local" / "CoachingIntel"

    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "CoachingIntel"


APP_MODE = (
    _text("COACHING_APP_MODE") or _text("COACHING_ENV") or "development"
).lower()
if APP_MODE not in MODES:
    raise RuntimeError(
        f"Unknown application mode {APP_MODE!r}; "
        f"set COACHING_APP_MODE to one of: {', '.join(MODES)}."
    )

IS_PRODUCTION = APP_MODE == "production"
IS_LOCAL = APP_MODE == "local"
# Kept for existing callers.
ENVIRONMENT = APP_MODE

# ---- Paths -----------------------------------------------------------

_explicit_data_dir = _text("COACHING_DATA_DIR")

if _explicit_data_dir:
    DATA_DIR = Path(_explicit_data_dir).expanduser()
elif APP_MODE == "development":
    DATA_DIR = None  # legacy source-tree layout: <repo>/data/coaching.db
else:
    DATA_DIR = _default_data_dir()


def data_subdir(name: str) -> Path | None:
    return DATA_DIR / name if DATA_DIR else None


_explicit_db = _text("COACHING_DB_PATH")
if _explicit_db:
    DATABASE_PATH = Path(_explicit_db).expanduser()
elif DATA_DIR:
    DATABASE_PATH = DATA_DIR / "data" / "coaching.db"
else:
    DATABASE_PATH = PROJECT_ROOT / "data" / "coaching.db"

_explicit_backup = _text("COACHING_BACKUP_DIR")
if _explicit_backup:
    BACKUP_DIR = _explicit_backup
elif IS_LOCAL and DATA_DIR:
    BACKUP_DIR = str(DATA_DIR / "backups")
else:
    BACKUP_DIR = None  # required in production (see main.py)


def ensure_data_dirs() -> None:
    """Create the data directory layout. Never touches existing files."""
    if DATA_DIR:
        for name in DATA_SUBDIRS:
            (DATA_DIR / name).mkdir(parents=True, exist_ok=True)
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if BACKUP_DIR:
        Path(BACKUP_DIR).mkdir(parents=True, exist_ok=True)


# ---- Network (used by scripts/run_local.py) ---------------------------

HOST = _text("COACHING_HOST") or "127.0.0.1"
try:
    PORT = int(_text("COACHING_PORT") or 8000)
except ValueError:
    raise RuntimeError("COACHING_PORT must be a whole number.") from None
if not 1 <= PORT <= 65535:
    raise RuntimeError("COACHING_PORT must be between 1 and 65535.")

# ---- Runtime behaviour by mode ----------------------------------------

SERVE_FRONTEND = _flag("COACHING_SERVE_FRONTEND", IS_LOCAL)
FRONTEND_DIST = Path(
    _text("COACHING_FRONTEND_DIST") or PROJECT_ROOT / "frontend" / "dist"
)
AUTO_MIGRATE = _flag("COACHING_AUTO_MIGRATE", IS_LOCAL)

# Session cookie. Secure is mandatory in production. In local mode the
# app is reached over plain HTTP (localhost or a LAN address), where a
# Secure cookie would never be sent back, so it defaults to off there;
# HttpOnly and SameSite=Lax stay on in every mode.
SESSION_COOKIE_NAME = "cti_session"
COOKIE_SECURE = IS_PRODUCTION or _flag("COACHING_COOKIE_SECURE", False)

# Session lifetime: sliding idle timeout with an absolute maximum.
SESSION_IDLE_HOURS = 12
SESSION_ABSOLUTE_DAYS = 7
# Only write last_seen/expiry back when it is older than this.
SESSION_TOUCH_SECONDS = 60

# Login throttling.
LOGIN_MAX_FAILURES = 5
LOGIN_LOCK_MINUTES = 15

# Passwords.
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 256

# CSRF: every non-GET request must carry this header (see security/csrf.py).
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "fetch"

# Request body limits, enforced while the body is received (before it is
# buffered or parsed): CSV uploads and everything else.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMPORT_REQUEST_BYTES = MAX_UPLOAD_BYTES + 256 * 1024
MAX_REQUEST_BYTES = 1024 * 1024

# Interactive API docs are only served in development.
API_DOCS_ENABLED = APP_MODE == "development"

# ---- OMR image uploads (Stage 2B) -----------------------------------
# Sheets are photographed or scanned; PDF input is not supported.
OMR_ALLOWED_EXTENSIONS = (".png", ".jpg", ".jpeg")
MAX_OMR_IMAGE_BYTES = 12 * 1024 * 1024
MAX_OMR_FILES = 100
# Whole request (all images together); enforced while receiving.
MAX_OMR_REQUEST_BYTES = 200 * 1024 * 1024
# Decoded size is checked from the image header before any decoding:
# a small file can still describe an enormous picture.
OMR_MIN_IMAGE_SIDE = 200
OMR_MAX_IMAGE_PIXELS = 50_000_000
# The recogniser runs as a child process; it is killed after this long
# (a fixed allowance plus a per-sheet allowance).
OMR_TIMEOUT_BASE_SECONDS = 60
OMR_TIMEOUT_PER_SHEET_SECONDS = 10
# How many OMR batches may run at once on this computer.
OMR_MAX_CONCURRENT_BATCHES = 2

