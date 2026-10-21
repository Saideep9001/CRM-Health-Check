"""link each problem to the measure that raised it

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-21 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('finding', schema=None) as batch_op:
        batch_op.add_column(sa.Column('measure', sa.String(length=200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('finding', schema=None) as batch_op:
        batch_op.drop_column('measure')
