"""
Create api_test_data_template and generated_api_data tables

新增表 (接口自动化测试数据智能生成 Phase 1):
  - api_test_data_template: 测试数据模板 (可复用, 关联接口)
  - generated_api_data:      按模板生成的具体数据实例 (可追溯到模板)

与 ApiDataGeneratorAgent 的关系:
  - Agent 生成数据时, 优先查模板复用
  - 每次生成的数据落 generated_api_data, 便于追溯和统计分析

Revision ID: 020
Revises: 019
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = '020'
down_revision: Union[str, None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. api_test_data_template — 测试数据模板表
    # ============================================================
    op.create_table(
        'api_test_data_template',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('endpoint_id', sa.Integer(), nullable=False, comment='关联 api_endpoint.id (软关联, 不加 FK)'),
        sa.Column('name', sa.String(length=200), nullable=False, comment='模板名称'),
        sa.Column('description', sa.Text(), nullable=True, comment='模板说明'),
        sa.Column('data_type', sa.String(length=20), nullable=False, server_default='normal', comment='数据类型: normal/abnormal/boundary/dependent'),
        sa.Column('fields_schema', mysql.MEDIUMTEXT(), nullable=True, comment='字段定义 JSON (从接口 Schema 提取)'),
        sa.Column('generation_rules', mysql.MEDIUMTEXT(), nullable=True, comment='生成规则 JSON'),
        sa.Column('dependencies_json', sa.Text(), nullable=True, comment='依赖接口 JSON (dependent 类型用)'),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft', comment='模板状态'),
        sa.Column('tags', sa.String(length=500), nullable=True, comment='标签 (逗号分隔)'),
        sa.Column('usage_count', sa.Integer(), nullable=False, server_default='0', comment='被使用次数'),
        sa.Column('last_used_at', sa.String(length=30), nullable=True, comment='最后使用时间'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='软删除标记'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
        comment='API 测试数据模板表'
    )

    # 索引
    op.create_index(
        'idx_template_endpoint_type',
        'api_test_data_template',
        ['endpoint_id', 'data_type', 'status'],
        unique=False
    )
    op.create_index(
        'idx_template_status',
        'api_test_data_template',
        ['status', 'is_deleted'],
        unique=False
    )
    op.create_index(
        'idx_template_user',
        'api_test_data_template',
        ['user_id', 'is_deleted'],
        unique=False
    )

    # ============================================================
    # 2. generated_api_data — 生成的测试数据实例表
    # ============================================================
    op.create_table(
        'generated_api_data',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('endpoint_id', sa.Integer(), nullable=False, comment='关联 api_endpoint.id (软关联)'),
        sa.Column('template_id', sa.Integer(), nullable=True, comment='关联 api_test_data_template.id (无模板则空)'),
        sa.Column('case_id', sa.Integer(), nullable=True, comment='关联 api_case.id (若被用例引用)'),
        sa.Column('data_type', sa.String(length=20), nullable=False, server_default='normal', comment='数据类型'),
        sa.Column('generated_data', mysql.MEDIUMTEXT(), nullable=False, comment='生成的数据 JSON'),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='rule', comment='生成来源: rule/faker/llm/db/runtime/template'),
        sa.Column('fields_meta', sa.Text(), nullable=True, comment='字段生成详情 JSON'),
        sa.Column('elapsed_ms', sa.Integer(), nullable=False, server_default='0', comment='生成耗时 (毫秒)'),
        sa.Column('is_valid', sa.Boolean(), nullable=False, server_default='1', comment='数据是否通过校验'),
        sa.Column('validation_errors', sa.Text(), nullable=True, comment='校验错误信息'),
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='软删除标记'),
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now(), onupdate=sa.func.now(), comment='更新时间'),
        sa.PrimaryKeyConstraint('id'),
        comment='生成的 API 测试数据实例表'
    )

    # 索引
    op.create_index(
        'idx_data_endpoint_type',
        'generated_api_data',
        ['endpoint_id', 'data_type', 'is_deleted'],
        unique=False
    )
    op.create_index(
        'idx_data_case',
        'generated_api_data',
        ['case_id', 'is_deleted'],
        unique=False
    )
    op.create_index(
        'idx_data_template',
        'generated_api_data',
        ['template_id', 'is_deleted'],
        unique=False
    )
    op.create_index(
        'idx_data_user',
        'generated_api_data',
        ['user_id', 'is_deleted'],
        unique=False
    )
    op.create_index(
        'idx_data_created',
        'generated_api_data',
        ['created_at'],
        unique=False
    )


def downgrade() -> None:
    op.drop_index('idx_data_created', table_name='generated_api_data')
    op.drop_index('idx_data_user', table_name='generated_api_data')
    op.drop_index('idx_data_template', table_name='generated_api_data')
    op.drop_index('idx_data_case', table_name='generated_api_data')
    op.drop_index('idx_data_endpoint_type', table_name='generated_api_data')
    op.drop_table('generated_api_data')

    op.drop_index('idx_template_user', table_name='api_test_data_template')
    op.drop_index('idx_template_status', table_name='api_test_data_template')
    op.drop_index('idx_template_endpoint_type', table_name='api_test_data_template')
    op.drop_table('api_test_data_template')
