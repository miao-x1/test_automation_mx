"""add feedback table

Revision ID: 008
Revises: 007
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

revision = '008'
down_revision = '007'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'feedback',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('requirement_id', sa.Integer(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('script_id', sa.Integer(), nullable=True),
        sa.Column('score', sa.Integer(), nullable=False),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('accepted', sa.Boolean(), nullable=True),
        sa.Column('failure_analysis', sa.Text(), nullable=True),
        sa.Column('regenerated', sa.Boolean(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['requirement_id'], ['requirement_task.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_feedback_requirement', 'feedback', ['requirement_id'])
    op.create_index('idx_feedback_score', 'feedback', ['score'])


def downgrade() -> None:
    op.drop_index('idx_feedback_score', table_name='feedback')
    op.drop_index('idx_feedback_requirement', table_name='feedback')
    op.drop_table('feedback')
