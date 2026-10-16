"""portfolio (several saved orgs), scheduled scans and notifications

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-16 10:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004'
down_revision: Union[str, None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('salesforce_connection', schema=None) as batch_op:
        batch_op.add_column(sa.Column('active', sa.Boolean(), nullable=False, server_default=sa.true()))

    op.create_table(
        'scan_schedule',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('org_id', sa.String(length=32), nullable=False),
        sa.Column('frequency', sa.String(length=16), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('area_ids', sa.JSON(), nullable=True),
        sa.Column('next_run_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_run_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_assessment_id', sa.String(length=36), nullable=True),
        sa.Column('alert_email', sa.String(length=255), nullable=True),
        sa.Column('score_drop', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('alert_new_critical', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table('scan_schedule', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_scan_schedule_org_id'), ['org_id'], unique=True)
        batch_op.create_index(batch_op.f('ix_scan_schedule_next_run_at'), ['next_run_at'], unique=False)

    op.create_table(
        'notification',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('org_id', sa.String(length=32), nullable=True),
        sa.Column('kind', sa.String(length=16), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('link', sa.String(length=512), nullable=True),
        sa.Column('read', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_notification_created_at'), ['created_at'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('notification', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_notification_created_at'))
    op.drop_table('notification')
    with op.batch_alter_table('scan_schedule', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_scan_schedule_next_run_at'))
        batch_op.drop_index(batch_op.f('ix_scan_schedule_org_id'))
    op.drop_table('scan_schedule')
    with op.batch_alter_table('salesforce_connection', schema=None) as batch_op:
        batch_op.drop_column('active')
