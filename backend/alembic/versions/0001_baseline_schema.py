"""baseline schema

The pre-pilot schema plus the database integrity rules:
- composite foreign keys keep answers/results in the student's and the
  test's batch, keep an answer's question inside the answer's test, and keep
  a question's/action's topic inside its chapter;
- CHECK constraints on answer options, question numbers, marks and
  teacher-action values;
- indexes for per-question and later-test lookups.

Older demo databases created with create_all() are disposable: delete
data/coaching.db, run `alembic upgrade head` and re-seed.

Revision ID: 0001
Revises:
Create Date: 2026-10-02 09:30:39.112697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('chapters',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_chapters')),
    sa.UniqueConstraint('subject', 'name', name='uq_chapter_subject_name')
    )
    op.create_table('institutes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_institutes'))
    )
    op.create_table('batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institute_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['institute_id'], ['institutes.id'], name=op.f('fk_batches_institute_id_institutes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_batches')),
    sa.UniqueConstraint('institute_id', 'name', name='uq_batch_institute_name')
    )
    op.create_table('topics',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], name=op.f('fk_topics_chapter_id_chapters')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_topics')),
    sa.UniqueConstraint('chapter_id', 'name', name='uq_topic_chapter_name'),
    sa.UniqueConstraint('id', 'chapter_id', name=op.f('uq_topics_id_chapter_id'))
    )
    op.create_table('students',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('roll_number', sa.String(length=100), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name=op.f('fk_students_batch_id_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_students')),
    sa.UniqueConstraint('batch_id', 'roll_number', name='uq_student_batch_roll'),
    sa.UniqueConstraint('id', 'batch_id', name=op.f('uq_students_id_batch_id'))
    )
    op.create_table('tests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('test_date', sa.Date(), nullable=False),
    sa.Column('marks_correct', sa.Float(), nullable=False),
    sa.Column('marks_wrong', sa.Float(), nullable=False),
    sa.Column('marks_blank', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('marks_correct > 0', name=op.f('ck_tests_marks_correct_positive')),
    sa.ForeignKeyConstraint(['batch_id'], ['batches.id'], name=op.f('fk_tests_batch_id_batches')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tests')),
    sa.UniqueConstraint('batch_id', 'name', 'test_date', name='uq_test_batch_name_date'),
    sa.UniqueConstraint('id', 'batch_id', name=op.f('uq_tests_id_batch_id'))
    )
    with op.batch_alter_table('tests', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tests_batch_id_test_date'), ['batch_id', 'test_date'], unique=False)

    op.create_table('questions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('question_number', sa.Integer(), nullable=False),
    sa.Column('subject', sa.String(length=100), nullable=False),
    sa.Column('chapter_id', sa.Integer(), nullable=False),
    sa.Column('topic_id', sa.Integer(), nullable=False),
    sa.Column('correct_answer', sa.String(length=1), nullable=False),
    sa.Column('difficulty', sa.String(length=20), nullable=False),
    sa.CheckConstraint("correct_answer IN ('A', 'B', 'C', 'D')", name=op.f('ck_questions_correct_answer_option')),
    sa.CheckConstraint('question_number > 0', name=op.f('ck_questions_question_number_positive')),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], name=op.f('fk_questions_chapter_id_chapters')),
    sa.ForeignKeyConstraint(['test_id'], ['tests.id'], name=op.f('fk_questions_test_id_tests'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['topic_id', 'chapter_id'], ['topics.id', 'topics.chapter_id'], name=op.f('fk_questions_topic_id_chapter_id_topics')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_questions')),
    sa.UniqueConstraint('id', 'test_id', name=op.f('uq_questions_id_test_id')),
    sa.UniqueConstraint('test_id', 'question_number', name='uq_question_test_number')
    )
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_questions_chapter_id'), ['chapter_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_questions_topic_id'), ['topic_id'], unique=False)

    op.create_table('test_results',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('correct_count', sa.Integer(), nullable=False),
    sa.Column('wrong_count', sa.Integer(), nullable=False),
    sa.Column('blank_count', sa.Integer(), nullable=False),
    sa.Column('marks', sa.Float(), nullable=False),
    sa.Column('accuracy', sa.Float(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['student_id', 'batch_id'], ['students.id', 'students.batch_id'], name=op.f('fk_test_results_student_id_batch_id_students')),
    sa.ForeignKeyConstraint(['test_id', 'batch_id'], ['tests.id', 'tests.batch_id'], name=op.f('fk_test_results_test_id_batch_id_tests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_test_results')),
    sa.UniqueConstraint('test_id', 'student_id', name='uq_result_test_student')
    )
    op.create_table('student_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=False),
    sa.Column('answer', sa.String(length=1), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("answer IS NULL OR answer IN ('A', 'B', 'C', 'D')", name=op.f('ck_student_answers_answer_option')),
    sa.ForeignKeyConstraint(['question_id', 'test_id'], ['questions.id', 'questions.test_id'], name=op.f('fk_student_answers_question_id_test_id_questions'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id', 'batch_id'], ['students.id', 'students.batch_id'], name=op.f('fk_student_answers_student_id_batch_id_students')),
    sa.ForeignKeyConstraint(['test_id', 'batch_id'], ['tests.id', 'tests.batch_id'], name=op.f('fk_student_answers_test_id_batch_id_tests'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_student_answers')),
    sa.UniqueConstraint('test_id', 'student_id', 'question_id', name='uq_student_test_question')
    )
    with op.batch_alter_table('student_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_student_answers_test_id_question_id'), ['test_id', 'question_id'], unique=False)

    op.create_table('teacher_actions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('question_id', sa.Integer(), nullable=True),
    sa.Column('chapter_id', sa.Integer(), nullable=True),
    sa.Column('topic_id', sa.Integer(), nullable=True),
    sa.Column('finding_type', sa.String(length=50), nullable=True),
    sa.Column('finding_title', sa.String(length=255), nullable=True),
    sa.Column('finding_reason', sa.Text(), nullable=True),
    sa.Column('action_type', sa.String(length=20), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint("action_type IN ('review', 'reteach', 'revise', 'monitor', 'no_action')", name=op.f('ck_teacher_actions_action_type_value')),
    sa.CheckConstraint("status IN ('planned', 'completed')", name=op.f('ck_teacher_actions_status_value')),
    sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], name=op.f('fk_teacher_actions_chapter_id_chapters')),
    sa.ForeignKeyConstraint(['question_id', 'test_id'], ['questions.id', 'questions.test_id'], name=op.f('fk_teacher_actions_question_id_test_id_questions')),
    sa.ForeignKeyConstraint(['test_id'], ['tests.id'], name=op.f('fk_teacher_actions_test_id_tests')),
    sa.ForeignKeyConstraint(['topic_id', 'chapter_id'], ['topics.id', 'topics.chapter_id'], name=op.f('fk_teacher_actions_topic_id_chapter_id_topics')),
    sa.ForeignKeyConstraint(['topic_id'], ['topics.id'], name=op.f('fk_teacher_actions_topic_id_topics')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_teacher_actions'))
    )
    with op.batch_alter_table('teacher_actions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_teacher_actions_test_id'), ['test_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('teacher_actions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_teacher_actions_test_id'))

    op.drop_table('teacher_actions')
    with op.batch_alter_table('student_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_student_answers_test_id_question_id'))

    op.drop_table('student_answers')
    op.drop_table('test_results')
    with op.batch_alter_table('questions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_questions_topic_id'))
        batch_op.drop_index(batch_op.f('ix_questions_chapter_id'))

    op.drop_table('questions')
    with op.batch_alter_table('tests', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tests_batch_id_test_date'))

    op.drop_table('tests')
    op.drop_table('students')
    op.drop_table('topics')
    op.drop_table('batches')
    op.drop_table('institutes')
    op.drop_table('chapters')
