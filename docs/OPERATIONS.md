# Operations guide (pilot)

How to run Coaching Test Intelligence for one real institute: install,
bootstrap, health, backups, restore, upgrades, and the pilot checklist.

## Architecture

```
Internet
  ↓ HTTPS (Caddy, automatic certificates, 11 MB request limit)
Caddy ── /          → frontend/dist (static files)
      └─ /api/*     → uvicorn on 127.0.0.1:8000 (one worker, systemd)
                        ↓
                      SQLite (WAL) at /var/lib/coaching/coaching.db
                        ↓ nightly online backup + weekly restore test
                      /var/backups/coaching  (+ encrypted off-machine copy)
```

Frontend and API share one origin: the session cookie works and CORS is
not enabled. Use **one** uvicorn worker (SQLite has a single writer).

## Install (once)

As root, on a small Linux server (Python 3.11+, Node 20+, Caddy 2):

```bash
useradd --system --home /opt/coaching --shell /usr/sbin/nologin coaching
install -d -o coaching -g coaching -m 0700 /var/lib/coaching /var/backups/coaching
install -d -m 0750 -o root -g coaching /etc/coaching

# Code (release checkout) in /opt/coaching, owned by root, readable by coaching.
cd /opt/coaching
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)          # produces frontend/dist

cp deploy/coaching.env.example /etc/coaching/coaching.env
chown root:coaching /etc/coaching/coaching.env && chmod 0640 /etc/coaching/coaching.env

# Schema (never created implicitly)
sudo -u coaching bash -c 'set -a; . /etc/coaching/coaching.env; .venv/bin/alembic upgrade head'
```

Do **not** run `scripts/seed_demo.py` in production (it refuses when
`COACHING_ENV=production`).

## Bootstrap the institute and its first admin

There is no self-signup and no institute creation over the web.

```bash
cd /opt/coaching
sudo -u coaching bash -c 'set -a; . /etc/coaching/coaching.env; set +a;
  .venv/bin/python scripts/manage.py create-institute --name "ABC Academy" \
    --admin-name "Priya Sharma" --admin-email priya@abc.example'
```

The password is prompted for (10+ characters) and never placed on the
command line. The admin then signs in and adds teachers under
**Admin → Users** (create, disable, reset password). Operator fallbacks:
`manage.py reset-password`, `manage.py set-active --inactive`,
`manage.py list-users`. Disabling a user or resetting a password signs
them out everywhere.

## Start

```bash
cp deploy/systemd/*.service deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now coaching-api coaching-backup.timer coaching-restore-test.timer

cp deploy/Caddyfile /etc/caddy/Caddyfile     # set COACHING_DOMAIN for Caddy
systemctl reload caddy
```

The API refuses to start (and logs why) if migrations are not applied,
or, in production, if `COACHING_BACKUP_DIR` is missing or not writable.

## Health check

`GET /api/health` runs a query and compares the schema revision with the
code:

- `200 {"status": "ok", "database": "ok", "schema_revision": "...", "expected_revision": "..."}`
- `503 {"status": "error", "database": "unavailable" | "not_migrated" | "outdated"}`

Point an uptime monitor at `https://<domain>/api/health`. It exposes no
data.

## Backups

- **What:** the SQLite database only (CSV uploads are not stored; the
  environment file holds no secrets).
- **How:** SQLite's online backup API (`scripts/backup.py create`), safe
  while the app runs. A raw file copy is *not* safe in WAL mode.
- **When:**
  - nightly at 02:30 (`coaching-backup.timer`), followed by pruning;
  - before every migration (`deploy/upgrade.sh`);
  - automatically before destructive admin changes (delete test, replace
    answers, answer-key correction). If that safety backup fails, the
    change is refused.
- **Retention:** nightly backups: newest per day for 14 days plus newest
  per week for 8 weeks. Pre-migration / pre-operation backups: 14 days.
  The newest backup is always kept.
- **Files:** `coaching-<UTC time>-<kind>.db` (mode 0600, directory 0700)
  and a `.json` manifest with the schema revision, key-table row counts
  and a SHA-256.
- **Off-machine copy (required for the pilot):** copy the backup
  directory to a second location daily, encrypted (for example `restic`
  or an object-storage bucket with server-side encryption). Backups
  contain student data: restrict access as for the live database.
  Deleted data remains in backups until they expire under the retention
  above.

## Restore

A backup counts only once it has been restored successfully.

**Automatic restore test (weekly, `coaching-restore-test.timer`):**
`scripts/backup.py test-restore` restores the newest backup into a
temporary directory and checks `PRAGMA integrity_check`,
`PRAGMA foreign_key_check`, the Alembic revision, the health check, the
key-table row counts against the manifest, and the checksum. A failure
leaves the unit failed: check `systemctl --failed` weekly (or wire
`OnFailure=` to your alerting).

**Manual verification of any backup:**

```bash
.venv/bin/python scripts/backup.py verify /var/backups/coaching/coaching-…db
```

**Restoring the live database:**

1. `systemctl stop coaching-api`
2. Choose the backup: `scripts/backup.py list`
3. `sudo -u coaching bash -c 'set -a; . /etc/coaching/coaching.env; .venv/bin/python scripts/backup.py restore /var/backups/coaching/<file>.db --yes'`
   - the backup is verified first and refused if any check fails;
   - the current database and its `-wal`/`-shm` files are moved aside
     (`coaching.db.pre-restore-<time>`), not deleted;
   - the restored file is checked again.
4. If the backup is from an older release, run `deploy/upgrade.sh`.
5. `systemctl start coaching-api` and check `/api/health`; sign in and
   open a recent test.
6. Record the restore (when, which backup, why).

## Upgrades and migrations

```bash
systemctl stop coaching-api
cd /opt/coaching && <update code>
.venv/bin/pip install -r backend/requirements.txt
(cd frontend && npm ci && npm run build)
sudo -u coaching deploy/upgrade.sh        # backup → verify → alembic upgrade head
systemctl start coaching-api && curl -fsS https://<domain>/api/health
```

Writing a migration: change the models, then
`alembic revision --autogenerate -m "..."` against a database at head,
review it (SQLite batch mode is enabled), and test on a copy of
production data. The test suite fails if models and migrations differ
(`tests/test_integrity.py::test_models_match_migrations`). Migrations
refuse to guess when existing data is ambiguous; restore the
pre-migration backup if one fails.

## Logging

- uvicorn and Caddy log method, path, status and timing; request bodies
  are never logged.
- The database engine hides SQL parameters
  (`hide_parameters=True`), so database errors in the logs show the
  statement but no student names, roll numbers or answers.
- Passwords and session tokens are never logged.
- `journalctl -u coaching-api` for application errors.

## Security notes

- Sessions: server-side, opaque 256-bit tokens in an HttpOnly,
  SameSite=Lax, Secure cookie; only a SHA-256 is stored. 12 h idle,
  7 days absolute; logout, password change and disabling revoke them.
- CSRF: every non-GET request must carry `X-Requested-With: fetch`.
- Every query is limited to the signed-in user's institute; other
  institutes' records answer 404.
- Interactive API docs and the OpenAPI schema are off in production.
- Uploads: 10 MB per CSV, enforced by Caddy and again by the app while
  the body streams in.

## Pilot checklist

Before real student data:

- [ ] HTTPS works on the institute's domain; `http://` redirects.
- [ ] `/etc/coaching/coaching.env` is 0640 root:coaching, `COACHING_ENV=production`.
- [ ] `alembic upgrade head` done; `/api/health` returns 200.
- [ ] Institute and first admin created with `manage.py`; demo data NOT seeded.
- [ ] Teachers created by the admin; each has signed in once.
- [ ] Nightly backup ran; `scripts/backup.py test-restore` passes.
- [ ] Off-machine encrypted copy configured and checked.
- [ ] A full restore rehearsed on a spare machine (steps above).
- [ ] Uptime monitor on `/api/health`; someone checks `systemctl --failed` weekly.
- [ ] Admin knows the correction workflows (answer key, answers, roster, delete test).
- [ ] Agreed with the institute: who may see which data, and how long data
      and backups are kept.

## Known limitations

- One institute per deployment is the tested pilot shape. The data model
  isolates institutes, but multi-institute operation (PostgreSQL,
  per-institute backups/retention, operator tooling) is later work.
- SQLite with one writer: fine for one institute; concurrent heavy imports
  queue behind each other.
- No email (password resets are done by an admin), no MFA, no SSO.
- All teachers see all batches of their institute.
- Analytics recompute on every request; very large tests (hundreds of
  students × hundreds of questions) are slower (see the Milestone 4 report).
- Login throttling is per account; there is no per-IP rate limiting in the
  app (add it at Caddy if needed).
