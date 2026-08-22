"""
Create api_endpoint and api_endpoint_version tables

新增表:
  - api_endpoint         (API 接口管理主表)
  - api_endpoint_version (接口版本快照表)

支持 API 接口管理的完整生命周期: 创建 → 编辑 → 发布(版本快照) → 废弃 → 归档

Revision ID: 018
Revises: 017
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '018'
down_revision: Union[str, None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ===== api_endpoint 主表 =====
    op.create_table(
        'api_endpoint',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False, comment='接口名称'),
        sa.Column('method', sa.String(length=10), nullable=False, comment='HTTP 方法'),
        sa.Column('path', sa.String(length=500), nullable=False, comment='接口路径'),
        sa.Column('summary', sa.String(length=500), nullable=True, comment='摘要'),
        sa.Column('description', sa.Text(), nullable=True, comment='详细说明'),
        sa.Column('tags', sa.String(length=500), nullable=True, comment='标签(逗号分隔)'),
        sa.Column('module', sa.String(length=100), nullable=True, comment='所属模块'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft', comment='状态'),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='manual', comment='来源'),
        sa.Column('headers_json', sa.Text(), nullable=True, comment='请求头 JSON'),
        sa.Column('params_json', sa.Text(), nullable=True, comment='Query/Path 参数 JSON'),
        sa.Column('body_json', sa.Text(), nullable=True, comment='请求体 JSON'),
        sa.Column('response_json', sa.Text(), nullable=True, comment='响应 JSON'),
        sa.Column('auth_type', sa.String(length=20), nullable=False, server_default='none', comment='认证类型'),
        sa.Column('auth_details_json', sa.Text(), nullable=True, comment='认证详情 JSON'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1', comment='当前版本号'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='软删除标记'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新者'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='API 接口管理主表',
    )
    op.create_index('ix_api_endpoint_id', 'api_endpoint', ['id'])
    op.create_index('ix_api_endpoint_user_status', 'api_endpoint', ['user_id', 'status'])
    op.create_index('ix_api_endpoint_method_path', 'api_endpoint', ['method', 'path'])
    op.create_index('ix_api_endpoint_module', 'api_endpoint', ['module'])
    op.create_index('ix_api_endpoint_is_deleted', 'api_endpoint', ['is_deleted'])

    # ===== api_endpoint_version 版本快照表 =====
    op.create_table(
        'api_endpoint_version',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('endpoint_id', sa.Integer(), nullable=False, comment='关联接口 ID'),
        sa.Column('version', sa.Integer(), nullable=False, comment='版本号'),
        sa.Column('snapshot_json', sa.Text(), nullable=False, comment='接口完整快照 JSON'),
        sa.Column('change_log', sa.String(length=500), nullable=True, comment='变更说明'),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='0', comment='是否当前版本'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新者'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.ForeignKeyConstraint(['endpoint_id'], ['api_endpoint.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='API 接口版本快照表',
    )
    op.create_index('ix_api_endpoint_version_id', 'api_endpoint_version', ['id'])
    op.create_index('ix_api_endpoint_version_endpoint_id', 'api_endpoint_version', ['endpoint_id'])
    op.create_index('ix_api_endpoint_version_ep_ver', 'api_endpoint_version', ['endpoint_id', 'version'])


def downgrade() -> None:
    op.drop_index('ix_api_endpoint_version_ep_ver', table_name='api_endpoint_version')
    op.drop_index('ix_api_endpoint_version_endpoint_id', table_name='api_endpoint_version')
    op.drop_index('ix_api_endpoint_version_id', table_name='api_endpoint_version')
    op.drop_table('api_endpoint_version')

    op.drop_index('ix_api_endpoint_is_deleted', table_name='api_endpoint')
    op.drop_index('ix_api_endpoint_module', table_name='api_endpoint')
    op.drop_index('ix_api_endpoint_method_path', table_name='api_endpoint')
    op.drop_index('ix_api_endpoint_user_status', table_name='api_endpoint')
    op.drop_index('ix_api_endpoint_id', table_name='api_endpoint')
    op.drop_table('api_endpoint')
