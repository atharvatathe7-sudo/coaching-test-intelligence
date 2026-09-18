# Coaching Test Intelligence

A Phase 1 prototype for turning coaching-institute test data into
diagnostic information for teachers.

## Phase 1

The system will eventually provide:

1. Automatic test evaluation
2. Question-level analysis
3. Chapter/topic weakness detection
4. Individual student diagnosis
5. Batch intelligence
6. Teacher action reports
7. Test-to-test progress tracking

## Current milestone

Milestone 1:

- Database schema
- FastAPI application
- SQLite database
- Demo dataset

## Technology

- Python
- FastAPI
- SQLAlchemy
- SQLite

## Run backend

From the project root:

```bash
cd backend

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
