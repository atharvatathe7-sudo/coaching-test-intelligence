#!/usr/bin/env bash
# Apply a new release's database migrations safely.
#
# Run as the `coaching` user from /opt/coaching AFTER stopping the API:
#   sudo systemctl stop coaching-api
#   sudo -u coaching deploy/upgrade.sh
#   sudo systemctl start coaching-api && curl -fsS https://<domain>/api/health
#
# Order: pre-migration backup -> verify that backup -> alembic upgrade.
# If the upgrade fails, restore the pre-migration backup (see
# docs/OPERATIONS.md, "Restore").
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="${COACHING_ENV_FILE:-/etc/coaching/coaching.env}"
PY="${COACHING_PYTHON:-.venv/bin/python}"
ALEMBIC="${COACHING_ALEMBIC:-.venv/bin/alembic}"

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

backup_path="$($PY scripts/backup.py create --kind pre-migration)"
echo "Pre-migration backup: $backup_path"

$PY scripts/backup.py verify "$backup_path" > /dev/null
echo "Backup verified."

"$ALEMBIC" upgrade head
echo "Migrations applied. Start the service and check /api/health."
