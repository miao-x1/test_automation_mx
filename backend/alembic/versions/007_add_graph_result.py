"""add graph_result to requirement_task

Revision ID: 007
Revises: 006
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import add_column_if_missing

revision = '007'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        'requirement_task',
        sa.Column('graph_result', sa.Text, nullable=True, comment='Graph推理结果(JSON): 页面路径、元素、业务流'),
    )


def downgrade() -> None:
    op.drop_column('requirement_task', 'graph_result')
