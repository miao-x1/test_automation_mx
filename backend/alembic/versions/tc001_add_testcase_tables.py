"""
Add testcase tables and agent_message table

新增表：
    - test_requirement (测试需求)
    - test_case_point (测试点)
    - test_case (测试用例)
    - test_case_review (用例审核)
    - mind_map (思维导图)
    - agent_message (Agent消息日志)

Revision ID: tc001
Revises: r2r001
Create Date: 2026-07-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'tc001'
down_revision: Union[str, None] = 'r2r001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # === test_requirement: 测试需求 ===
    op.create_table('test_requirement',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('task_id', sa.String(length=64), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_type', sa.String(length=20), nullable=False, server_default='text'),
        sa.Column('raw_input', sa.Text(), nullable=True),
        sa.Column('parsed_result', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_test_req_task', 'test_requirement', ['task_id'])
    op.create_index('idx_test_req_status', 'test_requirement', ['status'])

    # === test_case_point: 测试点 ===
    op.create_table('test_case_point',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('requirement_id', sa.Integer(), sa.ForeignKey('test_requirement.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=5), nullable=False, server_default='P1'),
        sa.Column('type', sa.String(length=30), nullable=False, server_default='functional'),
        sa.Column('scenario', sa.String(length=500), nullable=True),
        sa.Column('expected_behavior', sa.Text(), nullable=True),
        sa.Column('case_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tcp_req', 'test_case_point', ['requirement_id'])
    op.create_index('idx_tcp_priority', 'test_case_point', ['priority'])

    # === test_case: 测试用例 ===
    op.create_table('test_case',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_by', sa.String(length=64), nullable=True),
        sa.Column('task_id', sa.String(length=64), nullable=True),
        sa.Column('point_id', sa.Integer(), sa.ForeignKey('test_case_point.id', ondelete='CASCADE'), nullable=False),
        sa.Column('case_name', sa.String(length=200), nullable=False),
        sa.Column('precondition', sa.Text(), nullable=True),
        sa.Column('steps', sa.Text(), nullable=True),
        sa.Column('expected_result', sa.Text(), nullable=True),
        sa.Column('priority', sa.String(length=5), nullable=False, server_default='P1'),
        sa.Column('type', sa.String(length=30), nullable=False, server_default='functional'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft'),
        sa.Column('rag_references', sa.Text(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default=sa.text('0')),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tc_task', 'test_case', ['task_id'])
    op.create_index('idx_tc_point', 'test_case', ['point_id'])
    op.create_index('idx_tc_status', 'test_case', ['status'])

    # === test_case_review: 用例审核 ===
    op.create_table('test_case_review',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('case_id', sa.Integer(), sa.ForeignKey('test_case.id', ondelete='CASCADE'), nullable=False),
        sa.Column('score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('review_result', sa.String(length=20), nullable=False, server_default='need_revision'),
        sa.Column('suggestion', sa.Text(), nullable=True),
        sa.Column('issues', sa.Text(), nullable=True),
        sa.Column('review_comment', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_tcr_case', 'test_case_review', ['case_id'])

    # === mind_map: 思维导图 ===
    op.create_table('mind_map',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('format', sa.String(length=20), nullable=False, server_default='json'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_mm_task', 'mind_map', ['task_id'])

    # === agent_message: Agent消息日志 ===
    op.create_table('agent_message',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('task_id', sa.String(length=64), nullable=False),
        sa.Column('session_key', sa.String(length=128), nullable=False, server_default='default'),
        sa.Column('message_type', sa.String(length=64), nullable=False),
        sa.Column('sender', sa.String(length=64), nullable=False),
        sa.Column('receiver', sa.String(length=64), nullable=True),
        sa.Column('action', sa.String(length=64), nullable=True),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('result', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('duration', sa.Float(), nullable=True, server_default='0'),
        sa.Column('tokens_used', sa.Integer(), nullable=True, server_default='0'),
        sa.Column('step', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_agent_msg_task', 'agent_message', ['task_id'])
    op.create_index('idx_agent_msg_session', 'agent_message', ['session_key'])
    op.create_index('idx_agent_msg_type', 'agent_message', ['message_type'])
    op.create_index('idx_agent_msg_status', 'agent_message', ['status'])
    op.create_index('idx_agent_msg_task_step', 'agent_message', ['task_id', 'step'])


def downgrade() -> None:
    op.drop_table('agent_message')
    op.drop_table('mind_map')
    op.drop_table('test_case_review')
    op.drop_table('test_case')
    op.drop_table('test_case_point')
    op.drop_table('test_requirement')
