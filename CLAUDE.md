# Coaching Test Intelligence

## Product

This is a commercial coaching-institute Test Intelligence & Teacher Decision System.

Core positioning:

"Turn every coaching test into a diagnostic report for your teachers."

The product adds an intelligence and analytics layer on top of an institute's existing testing process.

Core workflow:

Test
→ Data
→ Evaluation
→ Analysis
→ Problems identified
→ Teacher action
→ Progress measurement

The system is NOT intended to be merely:
- an OMR scanner
- a marks calculator
- a student dashboard
- an LMS
- an AI tutor

---

## Current Product Scope

### Phase 1

1. Automatic Test Evaluation
2. Question-Level Analysis
3. Chapter and Topic Weakness Detection
4. Individual Student Diagnostic Reports
5. Batch / Teacher Dashboard
6. Teacher Action Report
7. Test-to-Test Progress Tracking
8. Question Investigation

### Not currently in scope

Do not implement these unless explicitly requested:

- gamification
- leaderboards
- student social features
- AI tutor
- automated teaching content
- full LMS
- full ERP
- unnecessary CRM functionality

---

## Core Product Loop

Detect
→ Investigate
→ Act
→ Measure

The application should help a teacher answer:

1. What happened in this test?
2. Which questions caused difficulty?
3. Which chapters/topics are weak?
4. Which students need attention?
5. What should the teacher review or reteach?
6. What changed in the next test?

---

## Current Architecture

### Backend

- Python
- FastAPI
- SQLAlchemy
- SQLite

Location:

`backend/app/`

Important files:

- `backend/app/main.py`
- `backend/app/api.py`
- `backend/app/database/connection.py`
- `backend/app/database/models.py`
- `backend/app/schemas/api.py`

Security and operations (Milestone 4):

- `backend/app/security/` — server-side sessions, Argon2id passwords,
  CSRF header check, request-size limits, and `access.py`: the single
  place that checks an object belongs to the user's institute.
- `backend/alembic/` — migrations. The schema is only ever created or
  changed with `alembic upgrade head`; never with `create_all`.
- `backend/app/ops/backup.py`, `scripts/backup.py` — backups and
  restore verification. `docs/OPERATIONS.md` — deployment and pilot checklist.
- Every route except `/`, `/api/health` and `POST /api/auth/login`
  requires a signed-in user; admin-only routes use `require_admin`.
  New routes must keep this (the route-guard tests enforce it).
- Corrections and imports write `audit_log` entries in the same
  transaction; audit details never contain student names, roll numbers,
  answers or passwords.

Business logic:

- `backend/app/services/evaluation.py`
- `backend/app/services/analytics.py`
- `backend/app/services/action_report.py`
- `backend/app/services/progress.py`

### Frontend

- React
- Vite

Main application:

`frontend/src/App.jsx`

Styles:

`frontend/src/App.css`

---

## Database Model

Institute
→ Batch
→ Student

Test
→ Question
→ Chapter
→ Topic

StudentAnswer
→ TestResult

The current database contains demo data for Physics Test 01 and Physics Test 02.

---

## Existing Functionality

The following functionality has already been implemented:

### Evaluation

- Student answers are compared with official answer keys.
- Correct, wrong and blank answers are calculated.
- Marks are calculated using the test's marking scheme.
- Accuracy is calculated.
- Results are stored in `test_results`.

### Question Analytics

The system calculates:

- correct percentage
- wrong percentage
- blank percentage
- difficult questions
- high-wrong questions
- blank-heavy questions

### Chapter / Topic Analytics

Questions can be mapped to:

- chapters
- topics

The system calculates batch performance at chapter and topic level.

### Student Analytics

The system calculates:

- marks
- accuracy
- correct answers
- wrong answers
- blank answers

### Batch Analytics

The system calculates:

- average marks
- highest marks
- lowest marks
- average accuracy
- total correct
- total wrong
- total blank
- negative marks
- performance distribution

### Teacher Action Report

The system converts data-supported findings into teacher attention priorities.

Important rule:

The system must NOT invent the cause of poor performance.

For example:

Good:
"65% of students answered Question 4 incorrectly."

Bad:
"Students misunderstood the concept."

The latter is a causal claim that the current data does not establish.

### Question Investigation

The dashboard has a Question Investigation feature.

A teacher can inspect a question and see individual student responses including:

- roll number
- student name
- selected answer
- Correct / Wrong / Blank result

This functionality must be preserved.

### Test-to-Test Progress

The backend now contains comparison functionality between tests.

Current comparison includes:

- average marks
- average accuracy
- marks change
- accuracy change
- improved students
- declined students
- unchanged students
- student-level changes
- chapter progress
- topic progress
- biggest improvements
- biggest declines

Teacher action outcomes (`services/action_outcomes.py`) report the observed change in a topic/chapter between a source test and the next comparable test (same batch and subject, strictly later date, with answers and the target). They must use observed-change wording only and never claim causation. Demo Test 02 is dated 7 days after Test 01.

Performance comparisons should use percentages where appropriate so different test sizes remain comparable.

The dashboard also contains a Progress vs Previous Test section.

---

## Demo Data

Existing demo tests include:

- Physics Test 01
- Physics Test 02

Known Test 01 values:

- 20 students
- 30 questions
- Average marks: 45.8
- Average accuracy: 53.9%

Known Test 02 values:

- Average marks: 51.0
- Average accuracy: 62.5%

Comparison:

- Average marks change: +5.2
- Accuracy change: +8.6 percentage points
- Improved students: 13
- Declined students: 6
- Unchanged students: 1

These values can be used to validate the implementation.

---

## Demo sign-in

Demo databases (`alembic upgrade head`, then `scripts/seed_demo.py`,
`scripts/create_test_02.py`) have `admin@demo.local` and
`teacher@demo.local`, password `demo-password`.

---

## Development Rules

Before modifying code:

1. Inspect the existing implementation.
2. Understand dependencies between affected files.
3. Make the smallest coherent change.
4. Preserve existing functionality.
5. Avoid unnecessary rewrites.
6. Avoid unnecessary dependencies.
7. Do not redesign the database without a clear requirement.

After modifying code:

1. Run backend tests.
2. Run relevant backend checks.
3. Run the frontend production build.
4. Test the affected UI where possible.
5. Check for regressions.
6. Report exactly which files changed.
7. Report remaining limitations.

Never claim a feature is working without actually testing it.

---

## Product Design Principles

The application is for teachers and coaching institutes.

Prioritize:

- clarity
- speed
- actionable information
- evidence-backed analysis
- simple workflows
- readable reports
- useful comparisons

Avoid:

- unnecessary visual complexity
- excessive animations
- meaningless charts
- gamification
- feature bloat

A teacher should be able to understand the important findings quickly.

---

## Data Interpretation Rules

Use neutral, data-supported language.

Good:

- "Correctness increased by 8 percentage points."
- "Question 4 had 25% correct responses."
- "13 students improved between the two tests."
- "Temperature performance declined by 4 percentage points."

Do not claim:

- why students failed unless the data supports it
- that a teaching intervention caused improvement unless intervention data exists
- that a question is conceptually bad merely because performance was low
- that a student is weak based on a single measurement

The system reports evidence and supports teacher decisions; it does not replace teacher judgment.

---

## Current Roadmap

Near-term order:

1. Stabilize current dashboard
2. Verify Test-to-Test Progress
3. Improve Teacher Action workflow
4. Add teacher action tracking
5. Build test import workflow
6. Integrate OMR processing
7. Strengthen multi-institute architecture
8. Prepare for commercial deployment

Do not implement roadmap items automatically.

Only implement the feature explicitly requested.

---

## Important

This repository is a real product under development.

Do not perform broad rewrites.

Do not delete working functionality to simplify implementation.

Do not change dependencies merely to silence an error without understanding the cause.

When something fails, diagnose the actual failure first.

When uncertain about product behavior, inspect the existing code and explain the ambiguity before making a large architectural decision.
