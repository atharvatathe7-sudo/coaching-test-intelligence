from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
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


class User(Base):
    """
    A person who signs in. Belongs to exactly one institute.

    Email is stored lower-cased (enforced by a CHECK) so the UNIQUE
    constraint is effectively case-insensitive.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    institute_id: Mapped[int] = mapped_column(
        ForeignKey("institutes.id"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    email: Mapped[str] = mapped_column(String(320), nullable=False)

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(String(20), nullable=False)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

    failed_login_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )

    locked_until: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("email"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("role IN ('admin', 'teacher')", name="role_value"),
        Index(None, "institute_id"),
    )


class UserSession(Base):
    """
    A server-side login session. Only a SHA-256 hash of the opaque
    session token is stored; the token itself lives in the user's
    HttpOnly cookie.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    last_seen_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )

    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index(None, "user_id"),
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

    __table_args__ = (
        UniqueConstraint(
            "institute_id",
            "name",
            name="uq_batch_institute_name",
        ),
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
        # Target of the composite foreign keys that keep answers/results
        # inside the student's own batch.
        UniqueConstraint("id", "batch_id"),
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

    __table_args__ = (
        UniqueConstraint(
            "batch_id",
            "name",
            "test_date",
            name="uq_test_batch_name_date",
        ),
        # Target of the composite foreign keys on answers/results.
        UniqueConstraint("id", "batch_id"),
        CheckConstraint("marks_correct > 0", name="marks_correct_positive"),
        # Later-test lookups (progress, action outcomes).
        Index(None, "batch_id", "test_date"),
    )


class Chapter(Base):
    """
    A syllabus chapter, owned by one institute. Topics belong to a chapter
    and therefore to the same institute.
    """

    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    institute_id: Mapped[int] = mapped_column(
        ForeignKey("institutes.id"),
        nullable=False,
    )

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
            "institute_id",
            "subject",
            "name",
            name="uq_chapter_institute_subject_name",
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
        # Target of the (topic_id, chapter_id) foreign keys.
        UniqueConstraint("id", "chapter_id"),
    )


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(
        ForeignKey("tests.id", ondelete="CASCADE"),
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

    # Must be a topic of chapter_id (composite foreign key below).
    topic_id: Mapped[int] = mapped_column(
        Integer,
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
        # Target of the (question_id, test_id) foreign keys.
        UniqueConstraint("id", "test_id"),
        ForeignKeyConstraint(
            ["topic_id", "chapter_id"],
            ["topics.id", "topics.chapter_id"],
        ),
        CheckConstraint(
            "correct_answer IN ('A', 'B', 'C', 'D')",
            name="correct_answer_option",
        ),
        CheckConstraint(
            "question_number > 0",
            name="question_number_positive",
        ),
        Index(None, "topic_id"),
        Index(None, "chapter_id"),
    )


class StudentAnswer(Base):
    """
    One student's response to one question.

    batch_id is stored so the database itself can guarantee that the
    test and the student belong to the same batch, and that the question
    belongs to the test (composite foreign keys below).
    """

    __tablename__ = "student_answers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(Integer, nullable=False)

    batch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    student_id: Mapped[int] = mapped_column(Integer, nullable=False)

    question_id: Mapped[int] = mapped_column(Integer, nullable=False)

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
        ForeignKeyConstraint(
            ["test_id", "batch_id"],
            ["tests.id", "tests.batch_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["student_id", "batch_id"],
            ["students.id", "students.batch_id"],
        ),
        ForeignKeyConstraint(
            ["question_id", "test_id"],
            ["questions.id", "questions.test_id"],
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "answer IS NULL OR answer IN ('A', 'B', 'C', 'D')",
            name="answer_option",
        ),
        # Per-question analytics lookups.
        Index(None, "test_id", "question_id"),
    )


class TestResult(Base):
    __tablename__ = "test_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    test_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Same-batch guarantee, as for student_answers.
    batch_id: Mapped[int] = mapped_column(Integer, nullable=False)

    student_id: Mapped[int] = mapped_column(Integer, nullable=False)

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
        ForeignKeyConstraint(
            ["test_id", "batch_id"],
            ["tests.id", "tests.batch_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["student_id", "batch_id"],
            ["students.id", "students.batch_id"],
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

    # Must be a question of test_id (composite foreign key below).
    question_id: Mapped[int | None] = mapped_column(
        Integer,
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

    # Who recorded the action. NULL only for actions recorded before
    # sign-in existed.
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
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

    __table_args__ = (
        ForeignKeyConstraint(
            ["question_id", "test_id"],
            ["questions.id", "questions.test_id"],
        ),
        # When both are given, the topic must belong to the chapter.
        ForeignKeyConstraint(
            ["topic_id", "chapter_id"],
            ["topics.id", "topics.chapter_id"],
        ),
        CheckConstraint(
            "action_type IN "
            "('review', 'reteach', 'revise', 'monitor', 'no_action')",
            name="action_type_value",
        ),
        CheckConstraint(
            "status IN ('planned', 'completed')",
            name="status_value",
        ),
        Index(None, "test_id"),
    )


class AuditLog(Base):
    """
    Record of an administrative change, written in the same transaction
    as the change itself.

    detail holds ids, counts and before/after values of non-personal
    fields only. It never contains student names, roll numbers, answers
    or passwords.
    """

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    institute_id: Mapped[int] = mapped_column(
        ForeignKey("institutes.id"),
        nullable=False,
    )

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"),
        nullable=True,
    )

    action: Mapped[str] = mapped_column(String(50), nullable=False)

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)

    # No foreign key: the entity may since have been deleted.
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        nullable=False,
    )

    __table_args__ = (
        Index(None, "institute_id", "created_at"),
        Index(None, "entity_type", "entity_id"),
    )
