# Coaching Test Intelligence

Turn every coaching test into a diagnostic report for your teachers.

A prototype that adds an analytics layer on top of an institute's tests:
**Detect → Investigate → Act → Measure**.

Current capabilities: test evaluation, question / chapter / topic / student /
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
    services/          evaluation, analytics, action_report, progress
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

## Demo workflow

1. Start the backend and the frontend.
2. Open the dashboard and pick **Physics Test 02** (or Test 01).
3. Review **Teacher Attention** priorities and open a question to investigate
   the individual student responses.
4. Record a teacher action (review / reteach / revise / monitor / no action)
   on a finding.
5. Check **Progress vs Previous Test** for the change from Test 01 to Test 02.
