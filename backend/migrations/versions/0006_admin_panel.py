"""admin panel: forced password change, access requests, activity log

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-21 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('must_change_password', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table(
        'access_request',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('kind', sa.String(length=8), nullable=False),
        sa.Column('requested_role', sa.String(length=16), nullable=True),
        sa.Column('org_note', sa.String(length=200), nullable=True),
        sa.Column('message', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=12), nullable=False),
        sa.Column('decided_by', sa.String(length=120), nullable=True),
        sa.Column('decision_note', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
    )
    with op.batch_alter_table('access_request', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_access_request_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_access_request_status'), ['status'], unique=False)

    op.create_table(
        'audit_event',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor', sa.String(length=255), nullable=False),
        sa.Column('action', sa.String(length=40), nullable=False),
        sa.Column('target', sa.String(length=255), nullable=True),
        sa.Column('detail', sa.String(length=500), nullable=True),
    )
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_audit_event_at'), ['at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_event_at'))
    op.drop_table('audit_event')
    with op.batch_alter_table('access_request', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_access_request_status'))
        batch_op.drop_index(batch_op.f('ix_access_request_user_id'))
    op.drop_table('access_request')
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.drop_column('must_change_password')
