"""institute-owned chapters/topics and action attribution

- chapters.institute_id (NOT NULL); uniqueness becomes
  (institute_id, subject, name). Topics are owned through their chapter.
- teacher_actions.created_by_user_id (nullable for actions recorded
  before sign-in existed).

Existing chapters are assigned to the institute whose tests/actions use
them. The migration refuses to guess: it stops if a chapter is used by
more than one institute, or if an unused chapter cannot be attributed
(more than one institute exists). Pre-pilot demo databases are
disposable; recreate them instead.

Revision ID: 0003
Revises: 0002
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Institutes using each chapter, via questions and teacher actions.
CHAPTER_USERS = """
    SELECT DISTINCT used.chapter_id, b.institute_id
    FROM (
        SELECT chapter_id, test_id FROM questions
        UNION
        SELECT chapter_id, test_id FROM teacher_actions
        WHERE chapter_id IS NOT NULL
    ) AS used
    JOIN tests t ON t.id = used.test_id
    JOIN batches b ON b.id = t.batch_id
"""


def upgrade() -> None:
    bind = op.get_bind()

    with op.batch_alter_table('chapters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('institute_id', sa.Integer(), nullable=True))

    owners: dict[int, set[int]] = {}
    for chapter_id, institute_id in bind.execute(sa.text(CHAPTER_USERS)):
        owners.setdefault(chapter_id, set()).add(institute_id)

    shared = sorted(c for c, i in owners.items() if len(i) > 1)
    if shared:
        raise RuntimeError(
            f"Chapters {shared} are used by more than one institute and "
            "cannot be assigned automatically."
        )

    for chapter_id, institutes in owners.items():
        bind.execute(
            sa.text("UPDATE chapters SET institute_id = :i WHERE id = :c"),
            {"i": next(iter(institutes)), "c": chapter_id},
        )

    unassigned = bind.execute(
        sa.text("SELECT COUNT(*) FROM chapters WHERE institute_id IS NULL")
    ).scalar()

    if unassigned:
        institutes = [
            row[0] for row in bind.execute(sa.text("SELECT id FROM institutes"))
        ]
        if len(institutes) != 1:
            raise RuntimeError(
                f"{unassigned} unused chapter(s) cannot be assigned to an "
                "institute automatically."
            )
        bind.execute(
            sa.text("UPDATE chapters SET institute_id = :i WHERE institute_id IS NULL"),
            {"i": institutes[0]},
        )

    with op.batch_alter_table('chapters', schema=None) as batch_op:
        batch_op.alter_column('institute_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint('uq_chapter_subject_name', type_='unique')
        batch_op.create_unique_constraint(
            'uq_chapter_institute_subject_name',
            ['institute_id', 'subject', 'name'],
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_chapters_institute_id_institutes'),
            'institutes', ['institute_id'], ['id'],
        )

    with op.batch_alter_table('teacher_actions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('created_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            batch_op.f('fk_teacher_actions_created_by_user_id_users'),
            'users', ['created_by_user_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('teacher_actions', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('fk_teacher_actions_created_by_user_id_users'),
            type_='foreignkey',
        )
        batch_op.drop_column('created_by_user_id')

    with op.batch_alter_table('chapters', schema=None) as batch_op:
        batch_op.drop_constraint(
            batch_op.f('fk_chapters_institute_id_institutes'),
            type_='foreignkey',
        )
        batch_op.drop_constraint('uq_chapter_institute_subject_name', type_='unique')
        batch_op.create_unique_constraint('uq_chapter_subject_name', ['subject', 'name'])
        batch_op.drop_column('institute_id')
