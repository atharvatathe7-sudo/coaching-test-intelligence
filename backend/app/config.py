"""
Application settings, read from environment variables.

COACHING_ENV          "production" or "development" (default)
COACHING_DB_PATH      SQLite file (see database/connection.py)
COACHING_COOKIE_SECURE  "1" to send the session cookie only over HTTPS
                      in development; always on in production
COACHING_BACKUP_DIR   directory for automatic pre-operation backups
"""

import os


def _flag(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


ENVIRONMENT = os.environ.get("COACHING_ENV", "development").strip().lower()
IS_PRODUCTION = ENVIRONMENT == "production"

# Session cookie. Secure is mandatory in production.
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

# Backups. Required in production (startup refuses to run without it).
BACKUP_DIR = os.environ.get("COACHING_BACKUP_DIR", "").strip() or None

# Request body limits, enforced while the body is received (before it is
# buffered or parsed): CSV uploads and everything else.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMPORT_REQUEST_BYTES = MAX_UPLOAD_BYTES + 256 * 1024
MAX_REQUEST_BYTES = 1024 * 1024

# Interactive API docs are disabled in production.
API_DOCS_ENABLED = not IS_PRODUCTION
