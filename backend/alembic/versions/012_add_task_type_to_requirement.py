"""add task_type and type_config to requirement_task

Revision ID: 012
Revises: 011
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = '012'
down_revision = '011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('requirement_task', sa.Column('task_type', sa.String(20), nullable=False, server_default='web', comment='AI推断的测试类型: web/api/performance/android/hybrid'))
    op.add_column('requirement_task', sa.Column('type_config', sa.Text(), nullable=True, comment='AI推断的测试范围(JSON): {web:true, api:false, performance:false, android:false}'))
    op.create_index('idx_requirement_task_type', 'requirement_task', ['task_type'])


def downgrade() -> None:
    op.drop_index('idx_requirement_task_type', table_name='requirement_task')
    op.drop_column('requirement_task', 'type_config')
    op.drop_column('requirement_task', 'task_type')
