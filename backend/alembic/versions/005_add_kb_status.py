"""add kb_status to ui_element, script, requirement_task

Revision ID: 005
Revises: 004
Create Date: 2026-06-07
统一为 ui_element、script、requirement_task 三张表新增 
kb_status 字段，用于标识知识库审核状态（draft/approved/rejected）
，默认 approved，并增加索引以支持按状态高效过滤查询。
"""
from alembic import op
import sqlalchemy as sa

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('ui_element', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    op.add_column('script', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    op.add_column('requirement_task', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    op.create_index('ix_ui_element_kb_status', 'ui_element', ['kb_status'])
    op.create_index('ix_script_kb_status', 'script', ['kb_status'])
    op.create_index('ix_requirement_task_kb_status', 'requirement_task', ['kb_status'])


def downgrade() -> None:
    op.drop_index('ix_ui_element_kb_status', 'ui_element')
    op.drop_index('ix_script_kb_status', 'script')
    op.drop_index('ix_requirement_task_kb_status', 'requirement_task')
    op.drop_column('ui_element', 'kb_status')
    op.drop_column('script', 'kb_status')
    op.drop_column('requirement_task', 'kb_status')
