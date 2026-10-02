# Coaching Test Intelligence

Turn every coaching test into a diagnostic report for your teachers.

A prototype that adds an analytics layer on top of an institute's tests:
**Detect → Investigate → Act → Measure**.

Current capabilities: CSV data import, test evaluation, action outcomes, question / chapter / topic / student /
batch analytics, a Teacher Action Report, Question Investigation,
test-to-test progress, and Teacher Action Tracking.

It is built for a controlled pilot with one real institute: sign-in with
server-side sessions, admin/teacher roles, institute isolation, database
integrity enforced by SQLite, migrations, correction workflows with an
audit log, and verified backups. It is not yet a multi-institute SaaS
(see "Known limitations" in `docs/OPERATIONS.md`). There is no OMR.
See `CLAUDE.md` for product rules and scope, and `docs/OPERATIONS.md`
for deployment, backups and the pilot checklist.

## Project structure

```
backend/
  alembic/             Database migrations (alembic upgrade head)
  app/
    main.py            FastAPI app, middleware, startup checks, /api/health
    config.py          Settings from environment variables
    api.py             Main API routes (signed-in users)
    auth_api.py        Login, logout, current user, password change
    users_api.py       Admin user management
    corrections_api.py Admin corrections + audit log
    import_api.py      CSV imports and answer-key correction (admin)
    security/          Sessions, passwords, CSRF, body limits, ownership checks
    database/          Engine (SQLite pragmas), models, schema check
    services/          evaluation, analytics, action_report, progress,
                       action_outcomes, importer, audit
    ops/               Backups, restore verification, retention
  requirements.txt     Runtime dependencies (pinned)
  requirements-dev.txt Runtime + test dependencies
frontend/              React + Vite dashboard (src/App.jsx, api.js, AdminPage.jsx)
scripts/               seed_demo.py, create_test_02.py, manage.py, backup.py
deploy/                Caddy, systemd units, environment template, upgrade.sh
docs/OPERATIONS.md     Deployment, backups, restore, pilot checklist
tests/                 pytest suite
data/                  Local SQLite database (generated, not in Git)
```

## Backend setup

Requires Python 3.11+. From the project root:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r backend/requirements-dev.txt
```

### Demo database

`data/coaching.db` is generated locally and ignored by Git. The schema is
created only by migrations (the app and the seed script never create
it). From the project root:

```bash
alembic upgrade head               # create / upgrade the schema
python scripts/seed_demo.py        # institute, users, batch, 20 students, Physics Test 01
python scripts/create_test_02.py   # Physics Test 02 (dated a week after Test 01)
```

Demo sign-in (demo databases only; the seed script refuses to run in
production): `admin@demo.local` and `teacher@demo.local`, password
`demo-password`.

The demo data is deterministic (fixed random seed). Expected values:

| | Test 01 | Test 02 |
|---|---|---|
| Average marks | 45.8 | 51.0 |
| Average accuracy | 53.9% | 62.5% |

Comparison: marks +5.2, accuracy +8.6 pp, 13 improved, 6 declined, 1 unchanged.

To reset, delete `data/coaching.db` (and any `-wal`/`-shm` files) and run
the three commands again. Databases from before Milestone 4 are not
migrated; recreate them.

### Run the backend

```bash
python -m uvicorn backend.app.main:app --reload --port 8000   # development only
```

The app refuses to start if the database is not at the latest migration.
Health check: `GET /api/health` (runs a query and checks the schema
revision; 503 if the database is unusable). API docs (development only):
http://127.0.0.1:8000/docs

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `COACHING_DB_PATH` | `data/coaching.db` | SQLite file to use. The test suite sets this to a temporary file. |
| `COACHING_ENV` | `development` | `production` enables Secure cookies, hides API docs, and requires a backup directory. |
| `COACHING_BACKUP_DIR` | unset | Where backups go. Required in production; when set, a safety backup is taken before destructive changes. |
| `COACHING_COOKIE_SECURE` | off in development | Send the session cookie only over HTTPS (always on in production). |

No application secret is needed. See `deploy/coaching.env.example`.

## Frontend setup

Requires Node.js 20+.

```bash
cd frontend
npm install
npm run dev        # http://127.0.0.1:5173, proxies /api to the backend on port 8000
npm run build      # production build
npm run lint
```

## Run the tests

```bash
python -m pytest
```

The tests build a temporary database with `alembic upgrade head` and the
demo scripts, so they do not need (and never touch) `data/coaching.db`.
They cover integrity constraints, migrations, authentication, CSRF,
roles, institute isolation, corrections, backups and the earlier
milestones' behaviour.

## Sign-in, roles and institutes

- Sign-in uses server-side sessions: an opaque random token in an
  HttpOnly, SameSite=Lax cookie (Secure in production); only its hash is
  stored. Sessions slide for 12 hours of inactivity, up to 7 days.
  Passwords (10+ characters) are hashed with Argon2id. Five failed
  attempts lock an account for 15 minutes.
- Every non-GET request must send `X-Requested-With: fetch` (CSRF
  protection); the frontend's `api.js` does this.
- Roles: **admin** (imports, corrections, users, evaluation, deletion)
  and **teacher** (analytics, investigation, actions; edits only their
  own actions). All teachers see all batches of their institute.
- Every record belongs to one institute (through its batch, or for
  chapters/topics directly). Other institutes' data answers 404.
- There is no self-signup. The operator creates institutes and their
  first admin on the server; admins then add teachers in **Admin → Users**:

```bash
python scripts/manage.py create-institute --name "ABC Academy" \
    --admin-name "Priya Sharma" --admin-email priya@abc.example
```

## Corrections and audit log

Admins correct mistakes in the app (**Admin**), without database edits.
Every correction is one transaction, writes an audit entry, and keeps
teacher actions:

- **Test details** (`PATCH /api/tests/{id}`): name, subject, date, marks.
  Changing marks re-evaluates the test; the batch cannot change.
- **Answer key** (`POST /api/imports/answer-key`, test-setup columns,
  every question listed): validate shows the exact changes
  (`Q4: A → C`), applying updates the questions in place and
  re-evaluates. Outcomes of earlier actions get the caveat
  `test_reevaluated_after_action`.
- **Answers**: re-upload with `replace=true` (re-evaluates).
- **Roster** (`PATCH`/`DELETE /api/students/{id}`): fix a name or roll
  number; students with answers cannot be deleted.
- **Delete a test** (`DELETE /api/tests/{id}`): refused if teacher
  actions exist unless `confirm_delete_actions=true`.

The audit log (`GET /api/audit`, Admin page) stores ids, counts and
before/after values of non-personal fields only, never student names,
roll numbers, answers or passwords.

## Importing real data (CSV)

Admins open the dashboard and click **Import data**, or call the API directly.
Import in this order; each file is validated first and nothing is saved
until you confirm. Use UTF-8 CSV with a header row.

| Stage | Required columns | Also supplied |
|---|---|---|
| 1. Roster (`roster.csv`) | `roll_number,name` | batch |
| 2. Test setup (`test_setup.csv`) | `question_number,correct_answer,chapter,topic` | batch, test name, subject, test date (`YYYY-MM-DD`), marks for correct / wrong / blank (defaults 4 / -1 / 0) |
| 3. Answers (`answers.csv`) | `roll_number,question_number,answer` | test |

```
roll_number,name            question_number,correct_answer,chapter,topic     roll_number,question_number,answer
R1,Asha                     1,A,Mechanics,Kinematics                        R1,1,A
R2,Bala                     2,C,Mechanics,Newton's Laws                     R1,2,
```

- Answers are `A`–`D`; a blank answer means unanswered. Long format only
  (one row per student per question).
- Students are matched by roll number within the batch, tests by
  (batch, name, date), questions by number, and chapters/topics by name
  (case and spacing ignored). IDs are never taken from the files.
- **Validation** reports every problem with file, row, field and value.
  Errors block the import (nothing is written); warnings do not.
  Warnings include new chapters/topics (which must be confirmed), skipped
  existing students, and students with missing answer rows (recorded as
  blank).
- **Transactions:** each import commits in a single transaction, so a
  failure leaves no partial data.
- **Evaluation** runs automatically after a successful answers import.
  `POST /api/tests/{id}/evaluate` is still available.
- **Re-import rules:** an existing roll number with the same name is
  skipped, with a different name it is an error (names are never
  overwritten). A test with the same batch/name/date is rejected and test
  setups cannot be replaced. Answers already present are rejected unless
  `replace=true`, which atomically replaces only the answers and results
  (questions and teacher actions are kept).

Imports are admin-only and limited to the admin's institute. API
(multipart form with a `file` field, max 10 MB; responses are
`{status: valid|invalid|imported, errors, warnings, summary}`):
`POST /api/imports/roster`, `POST /api/imports/test-setup`,
`POST /api/imports/answers`. `dry_run` defaults to `true`; send
`dry_run=false` to commit. Test setup also takes
`confirm_new_chapters_topics=true` when new chapters/topics are created.

## Action outcomes (observed next test)

`GET /api/tests/{test_id}/actions/outcomes` returns, for each teacher
action on a test, what was observed in the next comparable test. It
reports an **observed change only**; it never claims the action caused it.

- **Target:** the action's topic, else its question's topic, else its
  chapter. A question action is measured through its topic ("Topic of
  Question 4: Kinematics"); question numbers are never matched across tests.
- **Next comparable test:** same batch, same subject (case/spacing
  ignored), a strictly later `test_date` than the *source test*, ordered by
  `(test_date, id)`. Same-date tests do not count, and the action's
  timestamp is not used. Later tests with no imported answers, or without
  the target, are skipped (listed in `skipped_tests`).
- **Measure:** the existing topic/chapter correct percentage
  (`correct / responses`), so marking schemes do not matter. Needs at
  least 10 responses in both tests; the change is in percentage points.
- **Status:** `measured`, `no_subsequent_test`, `topic_absent`,
  `chapter_absent`, `insufficient_data` or `no_target`. Absence is never
  reported as 0%.
- **Caveats:** `action_still_planned`, `action_recorded_after_next_test`,
  `marking_scheme_differs`, `test_reevaluated_after_action`.

Outcomes are computed on read (nothing is stored) and shown under each
action on the Teacher Attention cards.

## Demo workflow

1. Create the demo database (above), start the backend and the frontend,
   and sign in as `teacher@demo.local` or `admin@demo.local`.
2. Open the dashboard and pick **Physics Test 02** (or Test 01).
3. Review **Teacher Attention** priorities and open a question to investigate
   the individual student responses.
4. Record a teacher action (review / reteach / revise / monitor / no action)
   on a finding.
5. Check **Progress vs Previous Test** for the change from Test 01 to Test 02.
6. On Test 01, the recorded action shows the observed result in Test 02
   (Test 02 is dated one week after Test 01).
7. As admin, **Admin → Test corrections** shows the answer-key correction,
   metadata edits and the audit log.

## Production

See `docs/OPERATIONS.md`: Caddy (HTTPS) in front of one uvicorn worker on
127.0.0.1, systemd units, nightly backups with weekly restore tests,
migrations, restore procedure and the pilot checklist.
