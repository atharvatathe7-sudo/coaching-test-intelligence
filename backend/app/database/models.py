from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .connection import Base


class Institute(Base):
    __tablename__ = "institutes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Batch(Base):
    __tablename__ = "batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    institute_id: Mapped[int] = mapped_column(
        ForeignKey("institutes.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id"),
        nullable=False,
    )

    roll_number: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "roll_number",
            name="uq_student_batch_roll",
        ),
    )


class Test(Base):
    __tablename__ = "tests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    batch_id: Mapped[int] = mapped_column(
        ForeignKey("batches.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    subject: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    test_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    marks_correct: Mapped[float] = mapped_column(
        Float,
        default=4,
        nullable=False,
    )

    marks_wrong: Mapped[float] = mapped_column(
        Float,
        default=-1,
        nullable=False,
    )

    marks_blank: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )


class Chapter(Base):
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    subject: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "subject",
            "name",
            name="uq_chapter_subject_name",
        ),
    )


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "chapter_id",
            "name",
            name="uq_topic_chapter_name",
        ),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id"),
        nullable=False,
    )

    question_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    subject: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    chapter_id: Mapped[int] = mapped_column(
        ForeignKey("chapters.id"),
        nullable=False,
    )

    topic_id: Mapped[int] = mapped_column(
        ForeignKey("topics.id"),
        nullable=False,
    )

    correct_answer: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
    )

    difficulty: Mapped[str] = mapped_column(
        String(20),
        default="medium",
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "test_id",
            "question_number",
            name="uq_question_test_number",
        ),
    )


class StudentAnswer(Base):
    __tablename__ = "student_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id"),
        nullable=False,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"),
        nullable=False,
    )

    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id"),
        nullable=False,
    )

    # NULL/None means the question was not attempted.
    answer: Mapped[str | None] = mapped_column(
        String(1),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "test_id",
            "student_id",
            "question_id",
            name="uq_student_test_question",
        ),
    )


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id"),
        nullable=False,
    )

    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id"),
        nullable=False,
    )

    correct_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    wrong_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    blank_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    marks: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    accuracy: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "test_id",
            "student_id",
            name="uq_result_test_student",
        ),
    )


class TeacherAction(Base):
    """
    A teacher's recorded response to a finding in the Teacher Action Report.

    The finding_* columns keep a snapshot of the finding as it was shown to
    the teacher, so the record stays understandable even if analytics change.
    The test_id link allows later comparison with subsequent tests; the
    record itself makes no claim about cause or effect.
    """

    __tablename__ = "teacher_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id"),
        nullable=False,
    )

    question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id"),
        nullable=True,
    )

    chapter_id: Mapped[int | None] = mapped_column(
        ForeignKey("chapters.id"),
        nullable=True,
    )

    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topics.id"),
        nullable=True,
    )

    # Snapshot of the originating finding.
    finding_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
    )

    finding_title: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    finding_reason: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    action_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="planned",
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )
