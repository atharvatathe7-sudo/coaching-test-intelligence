"""
Database integrity, migrations and health (Milestone 4A).

These tests write invalid rows directly with the ORM to prove the
database itself rejects them, independent of the importer's validation.
"""

from datetime import date

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from backend.app import main
from backend.app.database import models
from backend.app.database.connection import Base, engine, make_engine
from backend.app.database.schema_check import (
    expected_revision,
    require_current_schema,
    schema_status,
)

from conftest import alembic_config

DbTest = models.Test


@pytest.fixture()
def fresh_db(db):
    """Roll back whatever a test leaves in the session."""
    yield db
    db.rollback()


def _demo(db):
    tests = {t.name: t for t in db.query(DbTest)}
    t1, t2 = tests["Physics Test 01"], tests["Physics Test 02"]
    q1 = db.query(models.Question).filter_by(test_id=t1.id).first()
    q2 = db.query(models.Question).filter_by(test_id=t2.id).first()
    student = db.query(models.Student).filter_by(batch_id=t1.batch_id).first()
    return t1, t2, q1, q2, student


def _other_batch_student(db):
    batch = models.Batch(institute_id=1, name="Integrity Other Batch")
    db.add(batch)
    db.flush()
    student = models.Student(batch_id=batch.id, roll_number="X1", name="X")
    db.add(student)
    db.flush()
    return batch, student


def _rejects(db, *rows):
    db.add_all(rows)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


# ------------------------------------------------------------------
# Engine settings
# ------------------------------------------------------------------

def test_sqlite_pragmas_enabled(db):
    connection = db.connection()
    assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
    assert connection.exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
    assert connection.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
    # NORMAL == 1
    assert connection.exec_driver_sql("PRAGMA synchronous").scalar() == 1


def test_sql_parameters_hidden_in_errors(fresh_db):
    fresh_db.add(
        models.Student(batch_id=99999, roll_number="SECRET-ROLL", name="Secret Name")
    )
    with pytest.raises(IntegrityError) as exc:
        fresh_db.flush()
    assert "Secret Name" not in str(exc.value)
    assert "SECRET-ROLL" not in str(exc.value)
    assert "parameters hidden" in str(exc.value)


# ------------------------------------------------------------------
# Foreign keys and cross-entity consistency
# ------------------------------------------------------------------

def test_invalid_foreign_key_rejected(fresh_db):
    _rejects(fresh_db, models.Student(batch_id=99999, roll_number="Z", name="Z"))


def test_cross_batch_student_answer_rejected(fresh_db):
    t1, _, q1, _, _ = _demo(fresh_db)
    other_batch, outsider = _other_batch_student(fresh_db)

    # Student from another batch answering a test of batch A, whichever
    # batch_id is claimed.
    for claimed_batch in (t1.batch_id, other_batch.id):
        fresh_db.add(
            models.StudentAnswer(
                test_id=t1.id, batch_id=claimed_batch,
                student_id=outsider.id, question_id=q1.id, answer="A",
            )
        )
        with pytest.raises(IntegrityError):
            fresh_db.flush()
        fresh_db.rollback()
        other_batch, outsider = _other_batch_student(fresh_db)


def test_answer_with_question_from_another_test_rejected(fresh_db):
    t1, _, _, q2, student = _demo(fresh_db)
    _rejects(
        fresh_db,
        models.StudentAnswer(
            test_id=t1.id, batch_id=t1.batch_id,
            student_id=student.id, question_id=q2.id, answer="A",
        ),
    )


def test_cross_batch_test_result_rejected(fresh_db):
    t1, *_ = _demo(fresh_db)
    _, outsider = _other_batch_student(fresh_db)
    _rejects(
        fresh_db,
        models.TestResult(
            test_id=t1.id, batch_id=t1.batch_id, student_id=outsider.id,
            correct_count=0, wrong_count=0, blank_count=0,
            marks=0, accuracy=0,
        ),
    )


def test_question_topic_must_belong_to_its_chapter(fresh_db):
    t1, _, q1, _, _ = _demo(fresh_db)
    other_chapter = (
        fresh_db.query(models.Chapter)
        .filter(models.Chapter.id != q1.chapter_id)
        .first()
    )
    _rejects(
        fresh_db,
        models.Question(
            test_id=t1.id, question_number=999, subject="Physics",
            chapter_id=other_chapter.id, topic_id=q1.topic_id,
            correct_answer="A", difficulty="medium",
        ),
    )


def test_action_question_must_belong_to_action_test(fresh_db):
    t1, _, _, q2, _ = _demo(fresh_db)
    _rejects(
        fresh_db,
        models.TeacherAction(
            test_id=t1.id, question_id=q2.id, action_type="review",
            status="planned",
        ),
    )


def test_action_topic_must_belong_to_action_chapter(fresh_db):
    t1, _, q1, _, _ = _demo(fresh_db)
    other_chapter = (
        fresh_db.query(models.Chapter)
        .filter(models.Chapter.id != q1.chapter_id)
        .first()
    )
    _rejects(
        fresh_db,
        models.TeacherAction(
            test_id=t1.id, chapter_id=other_chapter.id, topic_id=q1.topic_id,
            action_type="review", status="planned",
        ),
    )


# ------------------------------------------------------------------
# CHECK constraints
# ------------------------------------------------------------------

@pytest.mark.parametrize("key", ["E", "a", "AB", ""])
def test_invalid_answer_key_rejected(fresh_db, key):
    t1, _, q1, _, _ = _demo(fresh_db)
    _rejects(
        fresh_db,
        models.Question(
            test_id=t1.id, question_number=500, subject="Physics",
            chapter_id=q1.chapter_id, topic_id=q1.topic_id,
            correct_answer=key, difficulty="medium",
        ),
    )


def test_invalid_student_answer_rejected(fresh_db):
    t1, _, q1, _, student = _demo(fresh_db)
    answer = (
        fresh_db.query(models.StudentAnswer)
        .filter_by(test_id=t1.id, student_id=student.id, question_id=q1.id)
        .one()
    )
    answer.answer = "Z"
    with pytest.raises(IntegrityError):
        fresh_db.flush()


def test_question_number_must_be_positive(fresh_db):
    t1, _, q1, _, _ = _demo(fresh_db)
    _rejects(
        fresh_db,
        models.Question(
            test_id=t1.id, question_number=0, subject="Physics",
            chapter_id=q1.chapter_id, topic_id=q1.topic_id,
            correct_answer="A", difficulty="medium",
        ),
    )


@pytest.mark.parametrize("marks", [0, -4])
def test_marks_correct_must_be_positive(fresh_db, marks):
    t1, *_ = _demo(fresh_db)
    _rejects(
        fresh_db,
        DbTest(
            batch_id=t1.batch_id, name="Bad marks", subject="Physics",
            test_date=date(2026, 1, 1), marks_correct=marks,
            marks_wrong=-1, marks_blank=0,
        ),
    )


@pytest.mark.parametrize(
    "field, value", [("action_type", "delete"), ("status", "done")]
)
def test_teacher_action_values_checked(fresh_db, field, value):
    t1, *_ = _demo(fresh_db)
    values = {"action_type": "review", "status": "planned", field: value}
    _rejects(fresh_db, models.TeacherAction(test_id=t1.id, **values))


# ------------------------------------------------------------------
# Migrations
# ------------------------------------------------------------------

def test_database_is_at_head_revision(db):
    revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
    assert revision == expected_revision()


def test_models_match_migrations():
    """Autogenerate finds nothing to add: models and migrations agree."""
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"compare_type": True}
        )
        diff = compare_metadata(context, Base.metadata)

    assert diff == []


def test_upgrade_downgrade_round_trip(tmp_path):
    """A fresh file migrates to head, all the way down, and back up."""
    path = tmp_path / "roundtrip.db"
    other = make_engine(f"sqlite:///{path}")
    config = alembic_config()

    with other.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        tables = set(inspect(connection).get_table_names())
        command.downgrade(config, "base")
        assert set(inspect(connection).get_table_names()) <= {"alembic_version"}
        command.upgrade(config, "head")
        assert set(inspect(connection).get_table_names()) == tables

    assert schema_status(other) == "ok"
    other.dispose()


# ------------------------------------------------------------------
# Health and startup
# ------------------------------------------------------------------

def test_health_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_schema_status_detects_problems(tmp_path):
    empty = make_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    assert schema_status(empty) == "not_migrated"

    with empty.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(32))"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version VALUES ('not-a-revision')"
        )
    assert schema_status(empty) == "outdated"
    empty.dispose()

    # A directory cannot be opened as a database.
    broken = create_engine(f"sqlite:///{tmp_path}")
    assert schema_status(broken) == "unavailable"


def test_health_reports_unusable_database(monkeypatch, tmp_path, client):
    unmigrated = make_engine(f"sqlite:///{tmp_path / 'blank.db'}")
    monkeypatch.setattr(main, "engine", unmigrated)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "not_migrated"}
    assert "sqlite" not in response.text.lower()


def test_startup_refuses_unmigrated_database(monkeypatch, tmp_path):
    unmigrated = make_engine(f"sqlite:///{tmp_path / 'blank.db'}")

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        require_current_schema(unmigrated)

    monkeypatch.setattr(main, "engine", unmigrated)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        with TestClient(main.app):
            pass


def test_startup_accepts_migrated_database():
    with TestClient(main.app) as started:
        assert started.get("/api/health").status_code == 200
