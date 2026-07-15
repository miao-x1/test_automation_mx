"""add script_source, reuse_count, rag_result, reuse_similarity

Revision ID: 006
Revises: 005
Create Date: 2026-06-07
为 script 与 requirement_task 表新增脚本来源与复用能力相关字段，
包括 script_source（生成/复用标识）、reuse_count（脚本复用次数）、
rag_result（RAG召回结果）以及 reuse_similarity（复用相似度），
用于支持基于检索增强生成（RAG）的脚本复用与相似度驱动的生成优化机制。
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # script表新增字段
    op.add_column('script', sa.Column('script_source', sa.String(20), nullable=False, server_default='generated', comment='脚本来源: generated/reused'))
    op.add_column('script', sa.Column('reuse_count', sa.Integer, nullable=False, server_default='0', comment='被其他需求复用的次数'))

    # requirement_task表新增字段
    op.add_column('requirement_task', sa.Column('rag_result', sa.Text, nullable=True, comment='RAG召回结果(JSON)'))
    op.add_column('requirement_task', sa.Column('script_source', sa.String(20), nullable=True, comment='脚本来源: generated/reused'))
    op.add_column('requirement_task', sa.Column('reuse_similarity', sa.String(20), nullable=True, comment='复用时的相似度分数'))


def downgrade() -> None:
    op.drop_column('script', 'reuse_count')
    op.drop_column('script', 'script_source')
    op.drop_column('requirement_task', 'reuse_similarity')
    op.drop_column('requirement_task', 'script_source')
    op.drop_column('requirement_task', 'rag_result')
