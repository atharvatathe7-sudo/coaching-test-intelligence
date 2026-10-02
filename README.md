# Coaching Test Intelligence

Turn every coaching test into a diagnostic report for your teachers.

A prototype that adds an analytics layer on top of an institute's tests:
**Detect → Investigate → Act → Measure**.

Current capabilities: CSV data import, test evaluation, question / chapter / topic / student /
batch analytics, a Teacher Action Report, Question Investigation,
test-to-test progress, and Teacher Action Tracking.

This is a working prototype, not a production system: there is no
authentication or multi-institute isolation yet, and no data import.
See `CLAUDE.md` for product rules and scope.

## Project structure

```
backend/
  app/
    main.py            FastAPI app
    api.py             API routes (prefix /api)
    database/          SQLAlchemy engine and models (SQLite)
    schemas/           Request models
    services/          evaluation, analytics, action_report, progress,
                       import_csv (parsing/report), importer (validate + commit)
    import_api.py      CSV import routes (prefix /api/imports)
  requirements.txt     Runtime dependencies (pinned)
  requirements-dev.txt Runtime + test dependencies
frontend/              React + Vite dashboard (src/App.jsx)
scripts/               Demo data scripts
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

`data/coaching.db` is generated locally and ignored by Git. Create it with
the two demo scripts (run from the project root):

```bash
python scripts/seed_demo.py        # institute, batch, 20 students, Physics Test 01
python scripts/create_test_02.py   # Physics Test 02 derived from Test 01
```

The demo data is deterministic (fixed random seed). Expected values:

| | Test 01 | Test 02 |
|---|---|---|
| Average marks | 45.8 | 51.0 |
| Average accuracy | 53.9% | 62.5% |

Comparison: marks +5.2, accuracy +8.6 pp, 13 improved, 6 declined, 1 unchanged.

To reset, delete `data/coaching.db` and run the scripts again.

### Run the backend

```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

API docs: http://127.0.0.1:8000/docs

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `COACHING_DB_PATH` | `data/coaching.db` | SQLite file to use. The test suite sets this to a temporary file. |

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

The tests build their own temporary database from the demo scripts, so they
do not need (and never touch) `data/coaching.db`.

## Importing real data (CSV)

Open the dashboard and click **Import data**, or call the API directly.
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

API (multipart form with a `file` field; responses are
`{status: valid|invalid|imported, errors, warnings, summary}`):
`POST /api/imports/roster`, `POST /api/imports/test-setup`,
`POST /api/imports/answers`. `dry_run` defaults to `true`; send
`dry_run=false` to commit. Test setup also takes
`confirm_new_chapters_topics=true` when new chapters/topics are created.

Existing local databases created before this version do not get the new
unique constraints (batch name per institute; test name + date per batch);
delete `data/coaching.db` and re-seed to get them.

## Demo workflow

1. Start the backend and the frontend.
2. Open the dashboard and pick **Physics Test 02** (or Test 01).
3. Review **Teacher Attention** priorities and open a question to investigate
   the individual student responses.
4. Record a teacher action (review / reteach / revise / monitor / no action)
   on a finding.
5. Check **Progress vs Previous Test** for the change from Test 01 to Test 02.
