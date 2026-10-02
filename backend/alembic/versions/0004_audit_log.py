"""audit log

Administrative changes (imports, corrections, deletions, user
management) are recorded in the same transaction as the change. The
(entity_type, entity_id) index serves the "test re-evaluated after this
action" caveat on action outcomes.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-02 09:47:21.197434

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('institute_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=50), nullable=False),
    sa.Column('entity_type', sa.String(length=30), nullable=False),
    sa.Column('entity_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['institute_id'], ['institutes.id'], name=op.f('fk_audit_log_institute_id_institutes')),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], name=op.f('fk_audit_log_user_id_users')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_audit_log'))
    )
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_log_entity_type_entity_id'), ['entity_type', 'entity_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_audit_log_institute_id_created_at'), ['institute_id', 'created_at'], unique=False)



def downgrade() -> None:
    with op.batch_alter_table('audit_log', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_log_institute_id_created_at'))
        batch_op.drop_index(batch_op.f('ix_audit_log_entity_type_entity_id'))

    op.drop_table('audit_log')
