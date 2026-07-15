"""添加ui_element和page_element表

Revision ID: 002
Revises: 001
Create Date: 2026-06-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """升级：创建ui_element和page_element表"""

    # 创建ui_element表（Vision分析结果）
    op.create_table(
        'ui_element',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        sa.Column('element_name', sa.String(length=255), nullable=False, comment='元素名称'),
        sa.Column('element_type', sa.String(length=50), nullable=False, comment='元素类型'),
        sa.Column('element_text', sa.String(length=512), nullable=True, comment='元素文本内容'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='UI元素表（Vision分析结果）'
    )
    op.create_index('ix_ui_element_task_id', 'ui_element', ['task_id'])
    op.create_index('ix_ui_element_element_type', 'ui_element', ['element_type'])
    op.create_index('idx_ui_element_task_type', 'ui_element', ['task_id', 'element_type'])

    # 创建page_element表（Playwright抓取的DOM元素）
    op.create_table(
        'page_element',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('task_id', sa.Integer(), nullable=False, comment='任务ID'),
        sa.Column('page_url', sa.String(length=1024), nullable=False, comment='页面URL'),
        sa.Column('tag_name', sa.String(length=50), nullable=False, comment='标签名'),
        sa.Column('element_text', sa.String(length=512), nullable=True, comment='元素文本内容'),
        sa.Column('element_id', sa.String(length=255), nullable=True, comment='元素ID属性'),
        sa.Column('element_class', sa.String(length=512), nullable=True, comment='元素class属性'),
        sa.Column('element_name', sa.String(length=255), nullable=True, comment='元素name属性'),
        sa.Column('placeholder', sa.String(length=255), nullable=True, comment='placeholder属性'),
        sa.Column('href', sa.String(length=1024), nullable=True, comment='href属性'),
        sa.Column('aria_label', sa.String(length=255), nullable=True, comment='aria-label属性'),
        sa.Column('role', sa.String(length=50), nullable=True, comment='role属性'),
        sa.Column('xpath', sa.String(length=1024), nullable=True, comment='XPath定位'),
        sa.Column('css_selector', sa.String(length=1024), nullable=True, comment='CSS选择器定位'),
        sa.ForeignKeyConstraint(['task_id'], ['task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='页面元素表（Playwright抓取的DOM元素）'
    )
    op.create_index('ix_page_element_task_id', 'page_element', ['task_id'])
    op.create_index('ix_page_element_tag_name', 'page_element', ['tag_name'])
    op.create_index('idx_page_element_task_tag', 'page_element', ['task_id', 'tag_name'])


def downgrade() -> None:
    """降级：删除page_element和ui_element表"""
    op.drop_table('page_element')
    op.drop_table('ui_element')
