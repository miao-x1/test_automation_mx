"""r2r: Add knowledge tables for RAG-enhanced case generation

Revision ID: r2r001
Revises: 80b492d1c570
Create Date: 2026-06-15
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = 'r2r001'
down_revision: Union[str, None] = '80b492d1c570'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('knowledge_source',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('source_type', sa.String(length=32), nullable=False),
        sa.Column('file_path', sa.String(length=500), nullable=True),
        sa.Column('source_url', sa.String(length=2000), nullable=True),
        sa.Column('raw_text', sa.Text(), nullable=True),
        sa.Column('requirement_context', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('chunk_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_knowledge_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('indexed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['parent_knowledge_id'], ['knowledge_source.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_knowledge_project_status', 'knowledge_source', ['project_id', 'status'])

    op.create_table('knowledge_chunk',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('knowledge_source_id', sa.Integer(), nullable=False),
        sa.Column('milvus_id', sa.BigInteger(), nullable=False),
        sa.Column('chunk_type', sa.String(length=32), nullable=True),
        sa.Column('text', sa.Text(), nullable=True),
        sa.Column('locator', sa.String(length=200), nullable=True),
        sa.Column('page', sa.String(length=64), nullable=True),
        sa.Column('metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['knowledge_source_id'], ['knowledge_source.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_chunk_type', 'knowledge_chunk', ['chunk_type'])

    op.create_table('case_generation',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('case_task_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('parent_generation_id', sa.Integer(), nullable=True),
        sa.Column('requirement_context', sa.JSON(), nullable=True),
        sa.Column('retrieved_context', sa.JSON(), nullable=True),
        sa.Column('retrieved_chunk_ids', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('case_set', sa.JSON(), nullable=True),
        sa.Column('case_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('config', sa.JSON(), nullable=True),
        sa.Column('llm_usage', sa.JSON(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['case_task_id'], ['case_task.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['parent_generation_id'], ['case_generation.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_gen_task_version', 'case_generation', ['case_task_id', 'version'])
    op.create_index('ix_gen_project_status', 'case_generation', ['project_id', 'status'])

    op.create_table('retrieval_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('project_id', sa.String(length=64), nullable=False),
        sa.Column('task_id', sa.String(length=64), nullable=True),
        sa.Column('case_generation_id', sa.Integer(), nullable=True),
        sa.Column('query_text', sa.Text(), nullable=True),
        sa.Column('query_vector_id', sa.BigInteger(), nullable=True),
        sa.Column('top_k', sa.Integer(), nullable=False, server_default='10'),
        sa.Column('score_threshold', sa.Float(), nullable=False, server_default='0.6'),
        sa.Column('filters', sa.JSON(), nullable=True),
        sa.Column('results', sa.JSON(), nullable=True),
        sa.Column('total_results', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_score', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('latency_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['case_generation_id'], ['case_generation.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_retrieval_task', 'retrieval_log', ['task_id'])
    op.create_index('ix_retrieval_project_time', 'retrieval_log', ['project_id', 'created_at'])


def downgrade() -> None:
    op.drop_table('retrieval_log')
    op.drop_table('case_generation')
    op.drop_table('knowledge_chunk')
    op.drop_table('knowledge_source')
