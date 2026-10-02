"""
Test configuration.

Every test run uses its own throwaway SQLite database, seeded with the
demo data. The developer's data/coaching.db is never touched.

COACHING_DB_PATH must be set before any backend module is imported,
because the database engine is created at import time.
"""

import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

_TEST_DB_DIR = tempfile.mkdtemp(prefix="coaching-test-db-")
os.environ["COACHING_DB_PATH"] = str(Path(_TEST_DB_DIR) / "test.db")

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.database import models  # noqa: E402,F401
from backend.app.database.connection import SessionLocal  # noqa: E402
from backend.app.database.models import TeacherAction, Test  # noqa: E402
from backend.app.main import app  # noqa: E402

import create_test_02  # noqa: E402
import seed_demo  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def demo_database():
    """Seed Physics Test 01 and Test 02 into the temporary database."""
    seed_demo.create_demo_data()
    create_test_02.create_test_02()


@pytest.fixture(scope="session")
def client(demo_database):
    return TestClient(app)


@pytest.fixture()
def db(demo_database):
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="session")
def test_ids(demo_database):
    session = SessionLocal()
    try:
        ids = {
            test.name: test.id
            for test in session.query(Test).all()
        }
    finally:
        session.close()

    return ids["Physics Test 01"], ids["Physics Test 02"]


@pytest.fixture(autouse=True)
def clean_actions(demo_database):
    """Teacher actions created by one test must not leak into another."""
    yield
    session = SessionLocal()
    try:
        session.query(TeacherAction).delete()
        session.commit()
    finally:
        session.close()
