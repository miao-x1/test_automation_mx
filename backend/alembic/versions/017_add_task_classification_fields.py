"""
Add classification fields to task table

新增字段：
    - framework  (测试框架: playwright/appium/pytest/jmeter)
    - platform   (测试平台: browser/mobile/server)
    - confidence (AI识别置信度 0-1)

Revision ID: 017
Revises: 016
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '017'
down_revision: Union[str, None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('task', sa.Column('framework', sa.String(64), nullable=True, comment='测试框架: playwright/appium/pytest/jmeter'))
    op.add_column('task', sa.Column('platform', sa.String(64), nullable=True, comment='测试平台: browser/mobile/server'))
    op.add_column('task', sa.Column('confidence', sa.Float(), nullable=True, comment='AI识别置信度(0-1)'))
    op.create_index('ix_task_framework', 'task', ['framework'])
    op.create_index('ix_task_platform', 'task', ['platform'])


def downgrade() -> None:
    op.drop_index('ix_task_platform', table_name='task')
    op.drop_index('ix_task_framework', table_name='task')
    op.drop_column('task', 'confidence')
    op.drop_column('task', 'platform')
    op.drop_column('task', 'framework')
