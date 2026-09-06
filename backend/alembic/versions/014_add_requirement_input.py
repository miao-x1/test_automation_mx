"""add requirement_input table

Revision ID: 014
Revises: 013
Create Date: 2026-06-14
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import ensure_user_table

revision = '014'
down_revision = '013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    ensure_user_table()
    op.create_table(
        'requirement_input',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True, comment='主键ID'),
        sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=True, comment='所属用户ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者用户ID'),
        sa.Column('requirement_id', sa.Integer(), sa.ForeignKey('requirement_task.id', ondelete='CASCADE'), nullable=True, comment='关联的需求任务ID'),
        sa.Column('mode', sa.String(20), nullable=False, server_default='text', comment='输入模式: text/image/url/script/mixed'),
        sa.Column('text', sa.Text(), nullable=True, comment='文本需求内容'),
        sa.Column('images', sa.Text(), nullable=True, comment='上传的图片路径列表(JSON数组)'),
        sa.Column('urls', sa.Text(), nullable=True, comment='输入的URL列表(JSON数组)'),
        sa.Column('script_path', sa.String(500), nullable=True, comment='上传的脚本文件路径'),
        sa.Column('script_content', sa.Text(), nullable=True, comment='直接粘贴的脚本内容'),
        sa.Column('script_language', sa.String(30), nullable=True, comment='脚本语言: python/javascript/yaml等'),
        sa.Column('page_ids', sa.Text(), nullable=True, comment='关联的数据库页面ID列表(JSON数组)'),
        sa.Column('recommended_mode', sa.String(20), nullable=True, comment='AI推荐的处理模式: vision/dom/reuse'),
        sa.Column('recommended_reason', sa.String(500), nullable=True, comment='AI推荐模式的理由'),
        sa.Column('parsed_result', sa.Text(), nullable=True, comment='各Parser解析结果(JSON)'),
        sa.Column('fused_result', sa.Text(), nullable=True, comment='FusionAgent融合结果(JSON)'),
        sa.Column('unified_requirement', sa.Text(), nullable=True, comment='融合后的统一需求文本'),
    )
    op.create_index('idx_req_input_requirement', 'requirement_input', ['requirement_id'])
    op.create_index('idx_req_input_mode', 'requirement_input', ['mode'])


def downgrade() -> None:
    op.drop_index('idx_req_input_mode', table_name='requirement_input')
    op.drop_index('idx_req_input_requirement', table_name='requirement_input')
    op.drop_table('requirement_input')
