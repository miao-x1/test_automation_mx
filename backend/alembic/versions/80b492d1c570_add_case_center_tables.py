"""add_case_center_tables

Revision ID: 80b492d1c570
Revises: 222428ec916b
Create Date: 2026-06-15 10:55:23.711111

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '80b492d1c570'
down_revision: Union[str, None] = '222428ec916b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('case_task',
        sa.Column('title', sa.String(length=200), nullable=False, comment='任务标题'),
        sa.Column('source_type', sa.String(length=30), nullable=False, comment='输入来源: pdf/doc/image/video/schema/swagger/url/text'),
        sa.Column('source_file', sa.String(length=500), nullable=True, comment='源文件路径'),
        sa.Column('source_url', sa.String(length=2000), nullable=True, comment='源URL'),
        sa.Column('raw_input', sa.Text(), nullable=True, comment='原始输入内容'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='任务状态'),
        sa.Column('requirement_context', sa.Text(), nullable=True, comment='解析后的RequirementContext(JSON)'),
        sa.Column('case_set', sa.Text(), nullable=True, comment='生成的CaseSet(JSON)'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('version', sa.Integer(), nullable=False, comment='版本号'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者用户ID'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['user_id'], ['user.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_task_created_by'), 'case_task', ['created_by'], unique=False)
    op.create_index(op.f('ix_case_task_status'), 'case_task', ['status'], unique=False)
    op.create_index(op.f('ix_case_task_user_id'), 'case_task', ['user_id'], unique=False)

    op.create_table('case_content',
        sa.Column('case_task_id', sa.Integer(), nullable=False, comment='关联用例任务ID'),
        sa.Column('title', sa.String(length=200), nullable=False, comment='用例标题'),
        sa.Column('case_type', sa.String(length=20), nullable=False, comment='用例类型: functional/error/boundary'),
        sa.Column('precondition', sa.Text(), nullable=True, comment='前置条件'),
        sa.Column('steps', sa.Text(), nullable=True, comment='测试步骤(JSON Array)'),
        sa.Column('expected', sa.Text(), nullable=True, comment='预期结果'),
        sa.Column('priority', sa.String(length=10), nullable=False, comment='优先级: high/medium/low'),
        sa.Column('tags', sa.String(length=500), nullable=True, comment='标签(JSON Array)'),
        sa.Column('version', sa.Integer(), nullable=False, comment='版本号'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, comment='是否删除'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['case_task_id'], ['case_task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_content_case_task_id'), 'case_content', ['case_task_id'], unique=False)

    op.create_table('case_export',
        sa.Column('case_task_id', sa.Integer(), nullable=False, comment='关联用例任务ID'),
        sa.Column('export_type', sa.String(length=20), nullable=False, comment='导出类型: excel/markdown/xmind/jira/testrail'),
        sa.Column('file_path', sa.String(length=500), nullable=True, comment='导出文件路径'),
        sa.Column('status', sa.String(length=20), nullable=False, comment='导出状态: pending/completed/failed'),
        sa.Column('config', sa.Text(), nullable=True, comment='导出配置(JSON)'),
        sa.Column('error_message', sa.Text(), nullable=True, comment='错误信息'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['case_task_id'], ['case_task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_export_case_task_id'), 'case_export', ['case_task_id'], unique=False)

    op.create_table('case_mindmap',
        sa.Column('case_task_id', sa.Integer(), nullable=False, comment='关联用例任务ID'),
        sa.Column('mindmap_data', sa.Text(), nullable=True, comment='思维导图数据(JSON树形结构)'),
        sa.Column('format', sa.String(length=20), nullable=False, comment='格式: json/markdown/xmind'),
        sa.Column('version', sa.Integer(), nullable=False, comment='版本号'),
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.ForeignKeyConstraint(['case_task_id'], ['case_task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_case_mindmap_case_task_id'), 'case_mindmap', ['case_task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_case_mindmap_case_task_id'), table_name='case_mindmap')
    op.drop_table('case_mindmap')
    op.drop_index(op.f('ix_case_export_case_task_id'), table_name='case_export')
    op.drop_table('case_export')
    op.drop_index(op.f('ix_case_content_case_task_id'), table_name='case_content')
    op.drop_table('case_content')
    op.drop_index(op.f('ix_case_task_user_id'), table_name='case_task')
    op.drop_index(op.f('ix_case_task_status'), table_name='case_task')
    op.drop_index(op.f('ix_case_task_created_by'), table_name='case_task')
    op.drop_table('case_task')
