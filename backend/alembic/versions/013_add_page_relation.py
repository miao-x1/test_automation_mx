"""add page_relation table

Revision ID: 013
Revises: 012
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa

revision = '013'
down_revision = '012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'page_relation',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='主键ID'),
        sa.Column('task_id', sa.Integer(), sa.ForeignKey('task.id', ondelete='CASCADE'), nullable=False, comment='关联任务ID'),
        sa.Column('source_page', sa.String(500), nullable=False, comment='源页面标识'),
        sa.Column('source_page_title', sa.String(200), nullable=True, comment='源页面标题'),
        sa.Column('target_page', sa.String(500), nullable=False, comment='目标页面标识'),
        sa.Column('target_page_title', sa.String(200), nullable=True, comment='目标页面标题'),
        sa.Column('relation_type', sa.String(50), nullable=False, server_default='navigation', comment='关系类型'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5', comment='关联置信度'),
        sa.Column('trigger', sa.String(500), nullable=True, comment='触发条件'),
        sa.Column('trigger_locator', sa.String(500), nullable=True, comment='触发元素定位器'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0', comment='排序序号'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='额外元数据'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
    )
    op.create_index('idx_page_relation_task', 'page_relation', ['task_id'])
    op.create_index('idx_page_relation_source', 'page_relation', ['source_page'])
    op.create_index('idx_page_relation_target', 'page_relation', ['target_page'])


def downgrade() -> None:
    op.drop_index('idx_page_relation_target', table_name='page_relation')
    op.drop_index('idx_page_relation_source', table_name='page_relation')
    op.drop_index('idx_page_relation_task', table_name='page_relation')
    op.drop_table('page_relation')
