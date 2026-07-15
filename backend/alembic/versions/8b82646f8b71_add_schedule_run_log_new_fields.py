"""add_schedule_run_log_new_fields

Revision ID: 8b82646f8b71
Revises: 015
Create Date: 2026-06-14 19:06:57.785252

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '8b82646f8b71'
down_revision: Union[str, None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增字段
    op.add_column('schedule_run_log', sa.Column('execution_id', sa.Integer(), nullable=True, comment='关联的执行记录ID'))
    op.add_column('schedule_run_log', sa.Column('trigger_type', sa.String(length=20), nullable=False, server_default='schedule', comment='触发方式: schedule/manual/retry'))
    op.add_column('schedule_run_log', sa.Column('operator', sa.String(length=100), nullable=True, comment='操作人（手动触发时记录）'))
    op.add_column('schedule_run_log', sa.Column('logs', sa.Text(), nullable=True, comment='执行日志'))

    # 外键
    op.create_foreign_key('fk_schedule_run_log_execution_id', 'schedule_run_log', 'execution_record', ['execution_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    op.drop_constraint('fk_schedule_run_log_execution_id', 'schedule_run_log', type_='foreignkey')
    op.drop_column('schedule_run_log', 'logs')
    op.drop_column('schedule_run_log', 'operator')
    op.drop_column('schedule_run_log', 'trigger_type')
    op.drop_column('schedule_run_log', 'execution_id')
