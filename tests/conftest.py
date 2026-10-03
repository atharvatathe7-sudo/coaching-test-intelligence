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
# OMR review images go to the same throwaway folder, never a real user one.
os.environ["COACHING_OMR_DIR"] = str(Path(_TEST_DB_DIR) / "omr")

sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.app.database import models  # noqa: E402,F401
from backend.app.database.connection import SessionLocal  # noqa: E402
from backend.app.database.models import TeacherAction, Test  # noqa: E402
from backend.app.main import app  # noqa: E402

import create_test_02  # noqa: E402
import seed_demo  # noqa: E402


def alembic_config() -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.attributes["configure_logger"] = False
    return config


@pytest.fixture(scope="session", autouse=True)
def demo_database():
    """
    Build the temporary database the way production does
    (alembic upgrade head), then seed Physics Test 01 and Test 02.
    """
    command.upgrade(alembic_config(), "head")
    seed_demo.create_demo_data()
    create_test_02.create_test_02()


# Every non-GET request must carry the CSRF header (security/csrf.py).
CSRF_HEADERS = {"X-Requested-With": "fetch"}


def make_client(email=None, password=seed_demo.DEMO_PASSWORD) -> TestClient:
    """A TestClient, signed in as `email` when given."""
    test_client = TestClient(app, headers=CSRF_HEADERS)

    if email is not None:
        response = test_client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert response.status_code == 200, response.text

    return test_client


@pytest.fixture(scope="session")
def client(demo_database):
    """Signed in as the demo institute's admin."""
    return make_client("admin@demo.local")


@pytest.fixture()
def teacher_client(demo_database):
    """Signed in as the demo institute's teacher."""
    return make_client("teacher@demo.local")


@pytest.fixture()
def anon_client(demo_database):
    """Not signed in (but sends the CSRF header)."""
    return make_client()


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
