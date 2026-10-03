# Coaching Test Intelligence

Turn every coaching test into a diagnostic report for your teachers.

A prototype that adds an analytics layer on top of an institute's tests:
**Detect → Investigate → Act → Measure**.

Current capabilities: CSV data import, test evaluation, action outcomes, question / chapter / topic / student /
batch analytics, a Teacher Action Report, Question Investigation,
test-to-test progress, Teacher Action Tracking, and Excel export of a test.

It is built for a controlled pilot with one real institute: sign-in with
server-side sessions, admin/teacher roles, institute isolation, database
integrity enforced by SQLite, migrations, correction workflows with an
audit log, and verified backups. It is not yet a multi-institute SaaS
(see "Known limitations" in `docs/OPERATIONS.md`). Answers can also be
read from photographed OMR sheets, with a teacher review step (below).
See `CLAUDE.md` for product rules and scope, and `docs/OPERATIONS.md`
for deployment, backups and the pilot checklist.

## Project structure

```
backend/
  alembic/             Database migrations (alembic upgrade head)
  app/
    main.py            FastAPI app, middleware, startup checks, /api/health
    config.py          Mode, data directory, paths and settings (single source)
    frontend_serving.py Serves the built React app in local mode
    omr_api.py         OMR image import endpoint (admin)
    omr/               OMR: template, checker (runs OMRChecker), normalization,
                       validation, service (bridge to the answer import)
    api.py             Main API routes (signed-in users)
    auth_api.py        Login, logout, current user, password change
    users_api.py       Admin user management
    corrections_api.py Admin corrections + audit log
    import_api.py      CSV imports and answer-key correction (admin)
    security/          Sessions, passwords, CSRF, body limits, ownership checks
    database/          Engine (SQLite pragmas), models, schema check,
                       startup.py (safe local-mode migration)
    services/          evaluation, analytics, action_report, progress,
                       action_outcomes, importer, audit, excel_export
    ops/               Backups, restore verification, retention
  requirements.txt     Runtime dependencies (pinned)
  requirements-dev.txt Runtime + test dependencies
frontend/              React + Vite dashboard (src/App.jsx, api.js, AdminPage.jsx)
scripts/               verify_omrchecker.py, run_local.py, seed_demo.py, create_test_02.py, manage.py, backup.py
third_party/omrchecker Vendored OMRChecker (MIT), pinned to commit 5cf44a5
deploy/                Caddy, systemd units, environment template, upgrade.sh
docs/OPERATIONS.md     Deployment, backups, restore, pilot checklist
tests/                 pytest suite
data/                  Development-mode SQLite database (generated, not in Git)
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
| `COACHING_APP_MODE` | `development` | `development`, `local` or `production` (`COACHING_ENV` is the older name). `production` enables Secure cookies, hides API docs, and requires a backup directory. `local` is described below. An unknown value stops startup. |
| `COACHING_DATA_DIR` | unset (local: platform default) | Data directory for local mode (`data/ backups/ uploads/ logs/ exports/ config/`). |
| `COACHING_HOST` / `COACHING_PORT` | `127.0.0.1` / `8000` | Address used by `scripts/run_local.py`. |
| `COACHING_SERVE_FRONTEND` | on in local mode | Whether FastAPI serves `frontend/dist`. `COACHING_FRONTEND_DIST` changes the folder. |
| `COACHING_AUTO_MIGRATE` | on in local mode | Whether startup applies migrations (see below). Never on in development or production. |
| `COACHING_BACKUP_DIR` | unset | Where backups go. Required in production; when set, a safety backup is taken before destructive changes. |
| `COACHING_COOKIE_SECURE` | off in development and local | Send the session cookie only over HTTPS (always on in production). |

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

## Local Prototype Setup

The product is designed to run on **one institute-owned computer**, with
the browser on that same computer, no internet, no cloud and no web
server in front of it. There are two ways to run it; do not mix them up:

| | Development mode | Local prototype mode |
|---|---|---|
| For | changing the code | using the app |
| Mode | `development` (default) | `local` |
| Frontend | Vite dev server (`npm run dev`, port 5173) | built once (`npm run build`), served by FastAPI |
| Database | `data/coaching.db` in the source tree | `<data dir>/data/coaching.db` |
| Migrations | you run `alembic upgrade head` | applied at startup (backed up first) |
| API docs | on | off |

**Prerequisites:** Python 3.11+ and Node.js 20.19+ or 22.12+ (Node is needed only to
build the frontend once).

```bash
# 1. Install dependencies
pip install -r backend/requirements.txt
cd frontend && npm ci && npm run build && cd ..      # 2. Build the frontend

# 3. (Optional) choose where data lives; see "Where local data lives".
#    Skip this to use the default.
#    Windows (cmd):  set COACHING_DATA_DIR=D:\CoachingIntel
#    Linux/macOS:    export COACHING_DATA_DIR=/srv/coaching-intel

# 4. Create the data directory and database (runs the migrations)
python scripts/run_local.py --migrate-only

# 5. Create the first institute and its admin (prompts for a password)
python scripts/manage.py create-institute --name "My Institute" \
    --admin-name "Your Name" --admin-email you@example.com

# 6. Start the app, then open http://127.0.0.1:8000/ in a browser
python scripts/run_local.py
```

Sign in with the admin you created. To stop, press `Ctrl+C` in the
window. To restart, run step 6 again: existing data is kept. After
updating the code, run steps 1-2 again and then step 6; if the new
version needs a database migration, startup takes a backup first (in
`<data dir>/backups/`) and then migrates.

`scripts/seed_demo.py` and `scripts/create_test_02.py` load the demo
institute and tests (sign-in details in `CLAUDE.md`) into an empty
database, as in development.

**Safe startup.** In local mode startup never resets, deletes or
recreates a database. A new, empty database is created by running the
migrations. A database from an older version is first copied to
`backups/` (checked with `PRAGMA integrity_check`) and only then
migrated; if the backup fails, nothing is changed. A database with tables
but no migration history, or from a *newer* version of the app, is
refused and left untouched, with a message saying why.

**Where local data lives.** Under the data directory (`COACHING_DATA_DIR`,
default `%LOCALAPPDATA%\CoachingIntel` on Windows and
`~/.local/share/CoachingIntel` elsewhere): `data/` (the SQLite database),
`backups/`, `uploads/`, `logs/`, `exports/`, `config/`. `uploads/`, `logs/`
and `exports/` are created for later stages and are empty today. Copy the
whole folder (with the app stopped) to move or back up the installation.

**Network access.** The default address is `127.0.0.1`, reachable only
from this computer. To let other computers on the network connect, set
`COACHING_HOST=0.0.0.0` (and optionally `COACHING_PORT`) explicitly and
allow the port through the computer's firewall. That traffic is plain,
unencrypted HTTP, so use it only on a network you trust. Settings can also
be kept in a file (`docs/local.env.example`) passed with `--env-file`.

**Session cookies in local mode.** The browser reaches the app over plain
HTTP, where a `Secure` cookie would never be sent back and sign-in would
silently fail, so in local mode the cookie is not marked `Secure`
(`COACHING_COOKIE_SECURE=1` turns it on, e.g. behind an HTTPS proxy). It
stays `HttpOnly` and `SameSite=Lax`, tokens are stored hashed on the
server, and nothing is put in browser storage. Production mode always
sets `Secure`.

**Offline.** The app makes no outbound network calls: no CDN, remote
font, analytics or API at runtime.

**Not tested / not included.** This section has been run on Linux only.
Windows paths and behaviour are prepared for (platform-aware defaults,
no Linux-only paths in the runtime) but **have not been tested on
Windows**. There is no installer, Windows service, bundled Python, tray
app or first-run setup screen yet.

## OMR answer sheets (images)

Besides CSV answers, a test's answers can be read from **PNG or JPEG
images** of filled-in answer sheets: on the Import page, stage 4 (or
`POST /api/tests/{test_id}/omr/import`, admin only).

```
images -> OMR recognition -> our normalization -> validation
       -> the existing answer import and evaluation (unchanged)
```

OMR only *reads* the sheets. It never calculates marks: scores come from
the application's existing evaluation, exactly as for a CSV import.

**Pending batches and review (Stage 3).** Uploading images creates a
stored **pending batch**; no answer or result exists until it is
committed. Clear answers are accepted automatically. Anything doubtful
becomes a review item for an admin, with a crop of the sheet (or the whole
sheet) next to what the engine detected:

- a multi-marked answer (two or more bubbles) - choose A, B, C, D or blank;
- an invalid or missing answer - same;
- a roll number that is missing, malformed, not on the roster or used by
  two sheets - type the right roll number;
- an unreadable sheet (e.g. markers not found) - it blocks the commit; fix
  or rescan it and upload again, or discard the batch.

The teacher's decision is stored separately (`final_answer`); what the
engine detected is never overwritten and a multi-mark is never turned into
a blank by the system. Batch states: `PROCESSING`, `REVIEW_REQUIRED`,
`READY_TO_COMMIT`, `COMMITTED`, `DISCARDED`, `FAILED`; illegal moves are
refused. Two reviewers cannot silently overwrite each other (a stale
decision answers 409 "changed by someone else").

**Commit.** "Commit batch" is possible only when every item is settled and
re-checks the whole batch against the test as it is now. It then runs the
existing answer import and evaluation, the audit entries and the batch's
COMMITTED state in **one transaction**: it all happens or none of it does.
If answers already exist for the test, commit is refused unless "Replace
existing answers" is ticked; replacing uses the same safety backup as a
CSV import. **Discard** removes a pending batch and its images and leaves
every existing answer, result and report untouched; discarding twice is
harmless.

**Images and privacy.** Pending-batch images are stored only on this
computer under `<data dir>/omr/` (override: `COACHING_OMR_DIR`). They are
shown only through signed-in, institute-checked endpoints
(`GET /api/omr/sheets/{id}/image`); no file path is ever sent to the
browser, and the images are removed when the batch is committed,
discarded or fails. Audit entries record who created/reviewed/committed/
discarded a batch and counts, never names, roll numbers, answers or
images.

**Who can use it.** Every OMR endpoint and the Import page are
**admin only** (as for CSV imports); teachers get 403 and no Import
button. Review is by any admin of the institute.

**What is checked.** Each sheet's roll number must match a student in the
test's batch exactly (no fuzzy matching); two sheets with the same roll
are blocked until fixed; answers are only taken for the selected test's
questions (other fields on the sheet are reported, never imported); every
upload must be a real PNG/JPEG within the size limits.

**Recognition states.** Each answer is `recognized` (one option),
`blank`, `multi_mark` (two or more options), `invalid` or
`review_required` (no value). A blank and a multi-mark are never mixed
up, even though evaluation scores both as no answer.

**Limits.** At most 100 images per batch, 12 MB each, 200 MB in total
(see `backend/app/config.py`). Processing is synchronous (no job queue); a batch left
"processing" for over 30 minutes is shown as failed (interrupted).

**Template.** The sheet layout is a controlled template under
`backend/app/omr/templates/` (a layout file for the engine plus a
manifest saying which fields are the roll number and the questions). Two
**prototype** templates are built in, each a 6-digit numeric roll number
and 60 four-option questions: `prototype-60q` (flat, aligned images) and
`prototype-marked-60q`, which has four corner markers so ordinary
photographs (tilted, with perspective) can be read; print it with
`python scripts/make_prototype_sheet.py`. The
roll numbers in a roster must be exactly those digits to match. A real
institute's sheet needs its own template; there is no template editor.

**Engine and licence.** Recognition uses
[OMRChecker](https://github.com/Udayraj123/OMRChecker) (MIT), included
unmodified at the single upstream commit `5cf44a5` in
`third_party/omrchecker/` and run as a separate headless process. See
`THIRD_PARTY_NOTICES.md`. Check the pin with
`python scripts/verify_omrchecker.py`. Its image-only dependencies are in
`backend/requirements-omr.txt` (PyMuPDF and PDF input are deliberately not
included). If they are not installed, the OMR endpoint answers 503 and the
rest of the application is unaffected.

## Excel export

On a test's page, **Export Excel** downloads one `.xlsx` workbook for that
test (`GET /api/tests/{test_id}/export.xlsx`, signed-in users, own
institute only; admins and teachers alike). It is built in memory for the
request and never stored. The file is named `<test name>_<test date>.xlsx`.

Sheets: Test Summary, Student Results, Question Analysis, Chapter
Analysis, Topic Analysis, Answer Matrix, Teacher Actions (with the
observed next-test outcome and caveats) and Test Comparison (against the
previous test of the same batch and subject, as on the dashboard).

Every figure comes from the same calculations the dashboard uses; the
export adds no scoring or ranking of its own. Notes for readers:

- *Accuracy* is correct / attempted. *Correct %* is correct / all
  responses (unattempted included). Percentages are real Excel
  percentages; changes between tests are in percentage points.
- Text is never treated as a formula: a value that starts with `=`, `+`,
  `-`, `@` (or a tab or carriage return) is written with a leading
  apostrophe so Excel keeps it as text. This also applies to student names
  and notes.
- A test with no questions or no imported answers still exports; the
  affected sheets say why they are empty. Students with no answers rows
  are not part of the analysis (as on the dashboard).
- Sorting: students by roll number, questions by number, chapters and
  topics by name.

## Production

See `docs/OPERATIONS.md`: Caddy (HTTPS) in front of one uvicorn worker on
127.0.0.1, systemd units, nightly backups with weekly restore tests,
migrations, restore procedure and the pilot checklist.
