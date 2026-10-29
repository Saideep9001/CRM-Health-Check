"""companies (workspaces): people, orgs and results are kept apart per company

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-29 12:00:00

"""
from datetime import datetime, timezone
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    company = op.create_table(
        'company',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('platform_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column('hidden_org_ids', sa.JSON(), nullable=True))
        batch_op.create_index('ix_app_user_company_id', ['company_id'])
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.add_column(sa.Column('company_id', sa.String(length=36), nullable=True))
        batch_op.create_index('ix_audit_event_company_id', ['company_id'])

    # Everything that exists today is the first company; the first admin runs the platform.
    op.bulk_insert(company, [{'id': 'default', 'name': 'Aquarient', 'created_at': datetime.now(timezone.utc)}])
    op.execute("UPDATE app_user SET company_id = 'default'")
    op.execute("UPDATE audit_event SET company_id = 'default'")
    op.execute(
        "UPDATE app_user SET platform_admin = TRUE WHERE id = ("
        " SELECT id FROM (SELECT id FROM app_user WHERE role = 'admin' ORDER BY created_at LIMIT 1) first_admin)"
    )


def downgrade() -> None:
    with op.batch_alter_table('audit_event', schema=None) as batch_op:
        batch_op.drop_index('ix_audit_event_company_id')
        batch_op.drop_column('company_id')
    with op.batch_alter_table('app_user', schema=None) as batch_op:
        batch_op.drop_index('ix_app_user_company_id')
        batch_op.drop_column('hidden_org_ids')
        batch_op.drop_column('platform_admin')
        batch_op.drop_column('company_id')
    op.drop_table('company')
