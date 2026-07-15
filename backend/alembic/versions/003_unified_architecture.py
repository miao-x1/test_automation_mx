"""统一架构升级：重构ui_element表，新增task字段

Revision ID: 003
Revises: 002
Create Date: 2026-06-06 10:00:00.000000

变更内容：
1. 重构ui_element表：新增source/locator/xpath/css_selector等字段，支持vision/dom/merge三种来源
2. task表新增input_mode和page_url字段
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级"""

    # 1. task表新增字段
    op.add_column('task', sa.Column('input_mode', sa.String(length=10), nullable=False, server_default='image', comment='输入模式: image/url'))
    op.add_column('task', sa.Column('page_url', sa.String(length=1024), nullable=True, comment='页面URL（URL模式时填写）'))
    op.create_index('idx_task_input_mode', 'task', ['input_mode'])

    # 2. 重建ui_element表（需要删除旧表再创建，因为字段结构变化较大）
    # 先删除旧表
    op.drop_index('idx_ui_element_task_type', table_name='ui_element')
    op.drop_index('ix_ui_element_task_id', table_name='ui_element')
    op.drop_index('ix_ui_element_element_type', table_name='ui_element')
    op.drop_table('ui_element')

    # 创建新的统一ui_element表
    op.create_table(
        'ui_element',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        # 元素基本信息
        sa.Column('name', sa.String(length=255), nullable=False, comment='元素名称（语义描述）'),
        sa.Column('type', sa.String(length=50), nullable=False, comment='元素类型'),
        sa.Column('text', sa.String(length=512), nullable=True, comment='元素文本内容'),
        # 来源标识
        sa.Column('source', sa.String(length=20), nullable=False, comment='元素来源: vision/dom/merge'),
        # 定位信息
        sa.Column('locator', sa.String(length=512), nullable=True, comment='最佳定位器'),
        sa.Column('xpath', sa.String(length=1024), nullable=True, comment='XPath定位'),
        sa.Column('css_selector', sa.String(length=1024), nullable=True, comment='CSS选择器定位'),
        # DOM属性
        sa.Column('element_id', sa.String(length=255), nullable=True, comment='元素id属性'),
        sa.Column('element_class', sa.String(length=512), nullable=True, comment='元素class属性'),
        sa.Column('element_name', sa.String(length=255), nullable=True, comment='元素name属性'),
        sa.Column('placeholder', sa.String(length=255), nullable=True, comment='placeholder属性'),
        sa.Column('href', sa.String(length=1024), nullable=True, comment='href属性'),
        sa.Column('aria_label', sa.String(length=255), nullable=True, comment='aria-label属性'),
        sa.Column('role', sa.String(length=50), nullable=True, comment='role属性'),
        # 页面URL
        sa.Column('page_url', sa.String(length=1024), nullable=True, comment='页面URL'),
        # 置信度
        sa.Column('confidence', sa.Float(), nullable=True, comment='识别置信度(0-1)'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='统一UI元素表'
    )
    op.create_index('ix_ui_element_task_id', 'ui_element', ['task_id'])
    op.create_index('ix_ui_element_type', 'ui_element', ['type'])
    op.create_index('ix_ui_element_source', 'ui_element', ['source'])
    op.create_index('idx_ui_element_task_type', 'ui_element', ['task_id', 'type'])
    op.create_index('idx_ui_element_task_source', 'ui_element', ['task_id', 'source'])


def downgrade() -> None:
    """降级"""
    # 删除新ui_element表
    op.drop_index('idx_ui_element_task_source', table_name='ui_element')
    op.drop_index('idx_ui_element_task_type', table_name='ui_element')
    op.drop_index('ix_ui_element_source', table_name='ui_element')
    op.drop_index('ix_ui_element_type', table_name='ui_element')
    op.drop_index('ix_ui_element_task_id', table_name='ui_element')
    op.drop_table('ui_element')

    # 恢复旧ui_element表
    op.create_table(
        'ui_element',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=False),
        sa.Column('element_name', sa.String(length=255), nullable=False),
        sa.Column('element_type', sa.String(length=50), nullable=False),
        sa.Column('element_text', sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_ui_element_task_id', 'ui_element', ['task_id'])
    op.create_index('ix_ui_element_element_type', 'ui_element', ['element_type'])
    op.create_index('idx_ui_element_task_type', 'ui_element', ['task_id', 'element_type'])

    # 删除task新增字段
    op.drop_index('idx_task_input_mode', table_name='task')
    op.drop_column('task', 'page_url')
    op.drop_column('task', 'input_mode')
