"""
Add agent_registry table

新增表：
    - agent_registry (Agent注册信息)

用于持久化 Agent 元数据，支持运行时动态管理和监控。

Revision ID: 016
Revises: tc001
Create Date: 2026-07-13
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '016'
down_revision: Union[str, None] = 'tc001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'agent_registry',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('user.id', ondelete='CASCADE'), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),

        sa.Column('agent_name', sa.String(64), nullable=False, unique=True, comment='Agent唯一名称'),
        sa.Column('agent_type', sa.String(32), nullable=False, server_default='llm', comment='Agent类型'),
        sa.Column('display_name', sa.String(128), nullable=True, comment='显示名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='Agent描述'),
        sa.Column('module_path', sa.String(256), nullable=False, comment='Python模块路径'),
        sa.Column('class_name', sa.String(64), nullable=False, comment='类名'),
        sa.Column('model_name', sa.String(64), nullable=True, comment='模型名称'),
        sa.Column('model_provider', sa.String(32), nullable=True, comment='模型提供商'),
        sa.Column('prompt_path', sa.String(256), nullable=True, comment='Prompt模板路径'),
        sa.Column('system_prompt', sa.Text(), nullable=True, comment='系统Prompt'),
        sa.Column('tools', sa.Text(), nullable=True, comment='工具列表(JSON)'),
        sa.Column('capabilities', sa.Text(), nullable=True, comment='能力列表(JSON)'),
        sa.Column('status', sa.String(20), nullable=False, server_default='registered', comment='状态'),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default='1', comment='是否启用'),
        sa.Column('version', sa.String(32), nullable=False, server_default='1.0.0', comment='版本号'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='额外元数据(JSON)'),
    )

    # 索引
    op.create_index('idx_agent_registry_name', 'agent_registry', ['agent_name'])
    op.create_index('idx_agent_registry_type', 'agent_registry', ['agent_type'])
    op.create_index('idx_agent_registry_status', 'agent_registry', ['status'])
    op.create_index('idx_agent_registry_enabled', 'agent_registry', ['enabled'])


def downgrade() -> None:
    op.drop_index('idx_agent_registry_enabled', table_name='agent_registry')
    op.drop_index('idx_agent_registry_status', table_name='agent_registry')
    op.drop_index('idx_agent_registry_type', table_name='agent_registry')
    op.drop_index('idx_agent_registry_name', table_name='agent_registry')
    op.drop_table('agent_registry')
