"""add kb_status to ui_element, script, requirement_task

Revision ID: 005
Revises: 004
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import add_column_if_missing, create_index_if_missing, table_exists

revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists('requirement_task'):
        op.create_table(
            'requirement_task',
            sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
            sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
            sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
            sa.Column('requirement', sa.Text(), nullable=False, comment='用户输入的自然语言需求'),
            sa.Column('status', sa.String(length=30), nullable=False, comment='任务状态'),
            sa.Column('intent', sa.String(length=100), nullable=True, comment='AI解析的意图标识'),
            sa.Column('generated_case', sa.Text(), nullable=True, comment='AI生成的测试用例(JSON)'),
            sa.Column('generated_script', sa.Text(), nullable=True, comment='AI生成的Playwright脚本'),
            sa.Column('task_id', sa.Integer(), nullable=True, comment='关联的任务ID'),
            sa.Column('execution_id', sa.Integer(), nullable=True, comment='关联的执行记录ID'),
            sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_requirement_task_status', 'requirement_task', ['status'])

    add_column_if_missing('ui_element', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    add_column_if_missing('script', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    add_column_if_missing('requirement_task', sa.Column('kb_status', sa.String(20), nullable=False, server_default='approved', comment='知识库审核状态: draft/approved/rejected'))
    create_index_if_missing('ix_ui_element_kb_status', 'ui_element', ['kb_status'])
    create_index_if_missing('ix_script_kb_status', 'script', ['kb_status'])
    create_index_if_missing('ix_requirement_task_kb_status', 'requirement_task', ['kb_status'])


def downgrade() -> None:
    op.drop_index('ix_ui_element_kb_status', 'ui_element')
    op.drop_index('ix_script_kb_status', 'script')
    op.drop_index('ix_requirement_task_kb_status', 'requirement_task')
    op.drop_column('ui_element', 'kb_status')
    op.drop_column('script', 'kb_status')
    op.drop_column('requirement_task', 'kb_status')
