"""add_execution_trigger_source_and_waiting_cancelled

Revision ID: 222428ec916b
Revises: 8b82646f8b71
Create Date: 2026-06-14 20:32:30.937121

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '222428ec916b'
down_revision: Union[str, None] = '8b82646f8b71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 新增 trigger_source 列
    op.add_column('execution_record', sa.Column(
        'trigger_source', sa.String(length=30),
        nullable=True,
        comment='触发来源: manual/schedule/script_upload/retry'
    ))
    # 更新 status 列注释（兼容 waiting/cancelled 新状态值）
    op.alter_column('execution_record', 'status',
               existing_type=mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=20),
               comment='执行状态: waiting/pending/running/success/failed/cancelled',
               existing_comment='执行状态: pending/running/success/failed',
               existing_nullable=False)


def downgrade() -> None:
    op.alter_column('execution_record', 'status',
               existing_type=mysql.VARCHAR(collation='utf8mb4_unicode_ci', length=20),
               comment='执行状态: pending/running/success/failed',
               existing_comment='执行状态: waiting/pending/running/success/failed/cancelled',
               existing_nullable=False)
    op.drop_column('execution_record', 'trigger_source')
