"""omr review batches

A batch of scanned answer sheets awaiting teacher review, its sheets, and
what the recogniser read for every answer. These tables hold no final
answers: StudentAnswer / TestResult are only written when a batch is
committed. Recognition results are kept unchanged next to the teacher's
final answer.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-03 09:08:54.723029

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('omr_batches',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institute_id', sa.Integer(), nullable=False),
    sa.Column('test_id', sa.Integer(), nullable=False),
    sa.Column('created_by_user_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('template_id', sa.String(length=50), nullable=False),
    sa.Column('template_version', sa.Integer(), nullable=False),
    sa.Column('total_sheets', sa.Integer(), nullable=False),
    sa.Column('accepted_sheets', sa.Integer(), nullable=False),
    sa.Column('review_required_count', sa.Integer(), nullable=False),
    sa.Column('error_count', sa.Integer(), nullable=False),
    sa.Column('committed_at', sa.DateTime(), nullable=True),
    sa.Column('committed_by_user_id', sa.Integer(), nullable=True),
    sa.Column('discarded_at', sa.DateTime(), nullable=True),
    sa.Column('discarded_by_user_id', sa.Integer(), nullable=True),
    sa.Column('images_removed_at', sa.DateTime(), nullable=True),
    sa.Column('failure_code', sa.String(length=30), nullable=True),
    sa.CheckConstraint("status IN ('PROCESSING', 'REVIEW_REQUIRED', 'READY_TO_COMMIT', 'COMMITTED', 'DISCARDED', 'FAILED')", name=op.f('ck_omr_batches_omr_batch_status')),
    sa.ForeignKeyConstraint(['committed_by_user_id'], ['users.id'], name=op.f('fk_omr_batches_committed_by_user_id_users')),
    sa.ForeignKeyConstraint(['created_by_user_id'], ['users.id'], name=op.f('fk_omr_batches_created_by_user_id_users')),
    sa.ForeignKeyConstraint(['discarded_by_user_id'], ['users.id'], name=op.f('fk_omr_batches_discarded_by_user_id_users')),
    sa.ForeignKeyConstraint(['institute_id'], ['institutes.id'], name=op.f('fk_omr_batches_institute_id_institutes')),
    sa.ForeignKeyConstraint(['test_id'], ['tests.id'], name=op.f('fk_omr_batches_test_id_tests')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_omr_batches'))
    )
    with op.batch_alter_table('omr_batches', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_omr_batches_institute_id_test_id'), ['institute_id', 'test_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_omr_batches_status'), ['status'], unique=False)

    op.create_table('omr_sheets',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('batch_id', sa.Integer(), nullable=False),
    sa.Column('sheet_index', sa.Integer(), nullable=False),
    sa.Column('original_filename', sa.String(length=200), nullable=False),
    sa.Column('roll_raw', sa.String(length=100), nullable=True),
    sa.Column('roll_number', sa.String(length=100), nullable=True),
    sa.Column('roll_source', sa.String(length=10), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('unreadable', sa.Boolean(), nullable=False),
    sa.Column('image_ext', sa.String(length=5), nullable=True),
    sa.Column('has_checked_image', sa.Boolean(), nullable=False),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
    sa.CheckConstraint("roll_source IN ('omr', 'teacher')", name=op.f('ck_omr_sheets_omr_roll_source')),
    sa.CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REVIEW_REQUIRED', 'INVALID', 'REVIEWED', 'COMMITTED')", name=op.f('ck_omr_sheets_omr_sheet_status')),
    sa.ForeignKeyConstraint(['batch_id'], ['omr_batches.id'], name=op.f('fk_omr_sheets_batch_id_omr_batches'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], name=op.f('fk_omr_sheets_reviewed_by_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_omr_sheets')),
    sa.UniqueConstraint('batch_id', 'sheet_index', name='uq_omr_sheet_index')
    )
    with op.batch_alter_table('omr_sheets', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_omr_sheets_batch_id'), ['batch_id'], unique=False)

    op.create_table('omr_answers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sheet_id', sa.Integer(), nullable=False),
    sa.Column('question_number', sa.Integer(), nullable=False),
    sa.Column('raw_value', sa.String(length=20), nullable=True),
    sa.Column('recognized_answer', sa.String(length=1), nullable=True),
    sa.Column('recognition_status', sa.String(length=20), nullable=False),
    sa.Column('review_reason', sa.String(length=30), nullable=True),
    sa.Column('resolved', sa.Boolean(), nullable=False),
    sa.Column('final_answer', sa.String(length=1), nullable=True),
    sa.Column('reviewed', sa.Boolean(), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(), nullable=True),
    sa.Column('reviewed_by_user_id', sa.Integer(), nullable=True),
    sa.Column('revision', sa.Integer(), nullable=False),
    sa.CheckConstraint("final_answer IS NULL OR final_answer IN ('A', 'B', 'C', 'D')", name=op.f('ck_omr_answers_omr_final_option')),
    sa.CheckConstraint("recognition_status IN ('recognized', 'blank', 'multi_mark', 'invalid', 'review_required')", name=op.f('ck_omr_answers_omr_recognition_status')),
    sa.CheckConstraint("recognized_answer IS NULL OR recognized_answer IN ('A', 'B', 'C', 'D')", name=op.f('ck_omr_answers_omr_recognized_option')),
    sa.CheckConstraint("review_reason IS NULL OR review_reason IN ('MULTI_MARK', 'INVALID_ANSWER', 'MISSING_ANSWER_FIELD')", name=op.f('ck_omr_answers_omr_review_reason')),
    sa.CheckConstraint('resolved = 1 OR final_answer IS NULL', name=op.f('ck_omr_answers_omr_final_needs_resolved')),
    sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], name=op.f('fk_omr_answers_reviewed_by_user_id_users')),
    sa.ForeignKeyConstraint(['sheet_id'], ['omr_sheets.id'], name=op.f('fk_omr_answers_sheet_id_omr_sheets'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_omr_answers')),
    sa.UniqueConstraint('sheet_id', 'question_number', name='uq_omr_answer_question')
    )
    with op.batch_alter_table('omr_answers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_omr_answers_sheet_id'), ['sheet_id'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('omr_answers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_omr_answers_sheet_id'))

    op.drop_table('omr_answers')
    with op.batch_alter_table('omr_sheets', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_omr_sheets_batch_id'))

    op.drop_table('omr_sheets')
    with op.batch_alter_table('omr_batches', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_omr_batches_status'))
        batch_op.drop_index(batch_op.f('ix_omr_batches_institute_id_test_id'))

    op.drop_table('omr_batches')
