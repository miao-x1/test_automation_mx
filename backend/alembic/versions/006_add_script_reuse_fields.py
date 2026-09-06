"""add script_source, reuse_count, rag_result, reuse_similarity

Revision ID: 006
Revises: 005
Create Date: 2026-06-07
"""
from alembic import op
import sqlalchemy as sa

from app.db.alembic_ops import add_column_if_missing

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing('script', sa.Column('script_source', sa.String(20), nullable=False, server_default='generated', comment='脚本来源: generated/reused'))
    add_column_if_missing('script', sa.Column('reuse_count', sa.Integer, nullable=False, server_default='0', comment='被其他需求复用的次数'))
    add_column_if_missing('requirement_task', sa.Column('rag_result', sa.Text, nullable=True, comment='RAG召回结果(JSON)'))
    add_column_if_missing('requirement_task', sa.Column('script_source', sa.String(20), nullable=True, comment='脚本来源: generated/reused'))
    add_column_if_missing('requirement_task', sa.Column('reuse_similarity', sa.String(20), nullable=True, comment='复用时的相似度分数'))


def downgrade() -> None:
    op.drop_column('script', 'reuse_count')
    op.drop_column('script', 'script_source')
    op.drop_column('requirement_task', 'reuse_similarity')
    op.drop_column('requirement_task', 'script_source')
    op.drop_column('requirement_task', 'rag_result')
