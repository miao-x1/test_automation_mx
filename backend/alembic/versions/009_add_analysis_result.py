"""add analysis_result to execution_record

Revision ID: 009
Revises: 008
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = '009'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('execution_record', sa.Column('analysis_result', sa.Text, nullable=True, comment='LLM失败分析结果(JSON): success, fail_step, root_cause, suggestion'))


def downgrade() -> None:
    op.drop_column('execution_record', 'analysis_result')
