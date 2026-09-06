"""add requirement extended fields

Revision ID: 011_requirement_extended
Revises: 010_graph_result_mediumtext
Create Date: 2026-06-10
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import add_column_if_missing

revision = '011'
down_revision = '010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing('requirement_task', sa.Column('additional_info', sa.Text(), nullable=True, comment='用户附加信息'))
    add_column_if_missing('requirement_task', sa.Column('image_paths', sa.Text(), nullable=True, comment='上传的图片路径列表(JSON)'))
    add_column_if_missing('requirement_task', sa.Column('script_format', sa.String(20), nullable=True, comment='脚本格式: playwright/yaml'))
    add_column_if_missing('requirement_task', sa.Column('generated_yaml', sa.Text(), nullable=True, comment='AI生成的YAML格式脚本'))
    add_column_if_missing('requirement_task', sa.Column('page_overview', sa.Text(), nullable=True, comment='AI生成的页面概述'))
    add_column_if_missing('requirement_task', sa.Column('page_elements', sa.Text(), nullable=True, comment='AI识别的页面元素(JSON)'))
    add_column_if_missing('requirement_task', sa.Column('test_scenarios', sa.Text(), nullable=True, comment='AI生成的测试场景(JSON)'))
    add_column_if_missing('requirement_task', sa.Column('expected_results', sa.Text(), nullable=True, comment='AI生成的预期结果(JSON)'))


def downgrade() -> None:
    op.drop_column('requirement_task', 'expected_results')
    op.drop_column('requirement_task', 'test_scenarios')
    op.drop_column('requirement_task', 'page_elements')
    op.drop_column('requirement_task', 'page_overview')
    op.drop_column('requirement_task', 'generated_yaml')
    op.drop_column('requirement_task', 'script_format')
    op.drop_column('requirement_task', 'image_paths')
    op.drop_column('requirement_task', 'additional_info')
