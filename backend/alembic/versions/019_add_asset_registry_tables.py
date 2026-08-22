"""
Create asset_registry, asset_version, asset_relation tables

新增表 (测试资产中心 Phase 1):
  - asset_registry (资产索引主表 — 所有测试资产的统一入口)
  - asset_version   (资产版本快照表 — 每次发布生成不可变快照)
  - asset_relation  (资产关系表 — 有向关系, 同步 Neo4j)

设计原则:
  1. 不与既有 test_asset / test_case / api_endpoint / ui_element / script 冲突
  2. 通过 ref_type + ref_id 软关联到既有业务表, 不加 FK 约束
  3. asset_version / asset_relation 通过 FK 关联到 asset_registry (CASCADE)

Revision ID: 019
Revises: 018
Create Date: 2026-07-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '019'
down_revision: Union[str, None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================================
    # 1. asset_registry — 资产索引主表
    # ============================================================
    op.create_table(
        'asset_registry',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # 业务标识
        sa.Column('asset_code', sa.String(length=64), nullable=False, comment='资产编码, 业务可读, 如 ASSET-2026-0001'),
        sa.Column('name', sa.String(length=200), nullable=False, comment='资产名称'),
        # 资产类型与关联
        sa.Column('asset_type', sa.String(length=30), nullable=False, comment='资产类型: api_endpoint/ui_element/test_case/test_asset/script/test_data/test_report/requirement'),
        sa.Column('ref_type', sa.String(length=50), nullable=False, comment='关联表名: api_endpoint / ui_element 等'),
        sa.Column('ref_id', sa.Integer(), nullable=False, comment='关联记录 ID (软外键, 不加 FK 约束)'),
        # 描述信息
        sa.Column('summary', sa.String(length=500), nullable=True, comment='一句话摘要'),
        sa.Column('description', sa.Text(), nullable=True, comment='详细说明 (Markdown)'),
        sa.Column('module', sa.String(length=100), nullable=True, comment='所属业务模块'),
        sa.Column('tags', sa.String(length=500), nullable=True, comment='标签 (逗号分隔)'),
        # 状态与版本
        sa.Column('status', sa.String(length=20), nullable=False, server_default='draft', comment='状态: draft/active/deprecated/archived'),
        sa.Column('source', sa.String(length=20), nullable=False, server_default='manual', comment='来源: manual/swagger/postman/har/import/ai'),
        sa.Column('version', sa.Integer(), nullable=False, server_default='1', comment='当前版本号 (从 1 起, 单调递增)'),
        # 评估指标
        sa.Column('quality_score', sa.Float(), nullable=False, server_default='0', comment='资产质量评分 0-100'),
        sa.Column('reuse_count', sa.Integer(), nullable=False, server_default='0', comment='被复用次数 (反规范化)'),
        sa.Column('last_used_at', sa.DateTime(), nullable=True, comment='最近被使用时间'),
        # 扩展字段
        sa.Column('extra_metadata', sa.Text(), nullable=True, comment='扩展元数据 JSON (各资产类型自定义字段)'),
        # 软删除
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='软删除标记'),
        # OwnedModel 字段
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新者'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        # 约束
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_code', name='uq_asset_registry_asset_code'),
        comment='测试资产索引主表 — 所有测试资产的统一入口',
    )

    # 单列索引
    op.create_index('ix_asset_registry_id', 'asset_registry', ['id'])
    op.create_index('ix_asset_registry_asset_code', 'asset_registry', ['asset_code'])
    op.create_index('ix_asset_registry_name', 'asset_registry', ['name'])
    op.create_index('ix_asset_registry_asset_type', 'asset_registry', ['asset_type'])
    op.create_index('ix_asset_registry_ref_type', 'asset_registry', ['ref_type'])
    op.create_index('ix_asset_registry_ref_id', 'asset_registry', ['ref_id'])
    op.create_index('ix_asset_registry_module', 'asset_registry', ['module'])
    op.create_index('ix_asset_registry_status', 'asset_registry', ['status'])
    op.create_index('ix_asset_registry_is_deleted', 'asset_registry', ['is_deleted'])
    op.create_index('ix_asset_registry_user_id', 'asset_registry', ['user_id'])
    # 复合索引
    op.create_index('idx_asset_reg_user_type_status', 'asset_registry', ['user_id', 'asset_type', 'status'])
    op.create_index('idx_asset_reg_ref_type_ref_id', 'asset_registry', ['ref_type', 'ref_id'])
    op.create_index('idx_asset_reg_user_status_module', 'asset_registry', ['user_id', 'status', 'module'])
    op.create_index('idx_asset_reg_user_is_deleted', 'asset_registry', ['user_id', 'is_deleted'])
    op.create_index('idx_asset_reg_type_status', 'asset_registry', ['asset_type', 'status'])
    op.create_index('idx_asset_reg_quality_score', 'asset_registry', ['quality_score'])

    # ============================================================
    # 2. asset_version — 资产版本快照表
    # ============================================================
    op.create_table(
        'asset_version',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # 关联
        sa.Column('asset_id', sa.Integer(), nullable=False, comment='关联 asset_registry.id'),
        # 版本信息
        sa.Column('version', sa.Integer(), nullable=False, comment='版本号 (从 1 起, 单调递增)'),
        sa.Column('snapshot_json', sa.Text(), nullable=False, comment='资产完整快照 JSON (含详情表字段)'),
        sa.Column('change_log', sa.String(length=500), nullable=True, comment='变更说明'),
        sa.Column('change_type', sa.String(length=20), nullable=False, server_default='update', comment='变更类型: create/update/rollback/status_change'),
        sa.Column('diff_summary', sa.Text(), nullable=True, comment='与上一版本的差异摘要 JSON (字段级)'),
        sa.Column('is_current', sa.Boolean(), nullable=False, server_default='0', comment='是否为当前版本'),
        # 发布信息
        sa.Column('published_by', sa.Integer(), nullable=True, comment='发布人 ID'),
        # OwnedModel 字段
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新者'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        # 约束
        sa.ForeignKeyConstraint(['asset_id'], ['asset_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='资产版本快照表 — 每次发布生成不可变快照',
    )

    # 单列索引
    op.create_index('ix_asset_version_id', 'asset_version', ['id'])
    op.create_index('ix_asset_version_asset_id', 'asset_version', ['asset_id'])
    op.create_index('ix_asset_version_version', 'asset_version', ['version'])
    op.create_index('ix_asset_version_is_current', 'asset_version', ['is_current'])
    op.create_index('ix_asset_version_user_id', 'asset_version', ['user_id'])
    # 复合索引
    op.create_index('idx_asset_ver_asset_version', 'asset_version', ['asset_id', 'version'], unique=True)
    op.create_index('idx_asset_ver_asset_is_current', 'asset_version', ['asset_id', 'is_current'])
    op.create_index('idx_asset_ver_user_created', 'asset_version', ['user_id', 'created_at'])

    # ============================================================
    # 3. asset_relation — 资产关系表
    # ============================================================
    op.create_table(
        'asset_relation',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        # 关联
        sa.Column('source_id', sa.Integer(), nullable=False, comment='源资产 ID'),
        sa.Column('target_id', sa.Integer(), nullable=False, comment='目标资产 ID'),
        # 关系信息
        sa.Column('relation_type', sa.String(length=30), nullable=False, comment='关系类型: DEPENDS_ON/USED_BY/IMPLEMENTS/COVERS/DERIVED_FROM/VERIFIES/CONTAINS/CONFLICTS_WITH'),
        sa.Column('weight', sa.Float(), nullable=False, server_default='1', comment='关系权重 (影响推荐排序)'),
        sa.Column('metadata_json', sa.Text(), nullable=True, comment='关系扩展元数据 JSON'),
        # Neo4j 同步状态
        sa.Column('neo4j_synced', sa.Boolean(), nullable=False, server_default='0', comment='是否已同步到 Neo4j'),
        sa.Column('neo4j_synced_at', sa.DateTime(), nullable=True, comment='最近成功同步到 Neo4j 的时间'),
        # 软删除
        sa.Column('is_deleted', sa.Boolean(), nullable=False, server_default='0', comment='软删除标记'),
        # OwnedModel 字段
        sa.Column('user_id', sa.Integer(), nullable=True, comment='所属用户 ID'),
        sa.Column('created_by', sa.Integer(), nullable=True, comment='创建者'),
        sa.Column('updated_by', sa.Integer(), nullable=True, comment='更新者'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        # 约束
        sa.ForeignKeyConstraint(['source_id'], ['asset_registry.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['target_id'], ['asset_registry.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        comment='资产关系表 — 资产之间的有向关系, 同步 Neo4j',
    )

    # 单列索引
    op.create_index('ix_asset_relation_id', 'asset_relation', ['id'])
    op.create_index('ix_asset_relation_source_id', 'asset_relation', ['source_id'])
    op.create_index('ix_asset_relation_target_id', 'asset_relation', ['target_id'])
    op.create_index('ix_asset_relation_relation_type', 'asset_relation', ['relation_type'])
    op.create_index('ix_asset_relation_neo4j_synced', 'asset_relation', ['neo4j_synced'])
    op.create_index('ix_asset_relation_user_id', 'asset_relation', ['user_id'])
    # 复合索引
    op.create_index('idx_asset_rel_src_type_tgt', 'asset_relation', ['source_id', 'relation_type', 'target_id'], unique=True)
    op.create_index('idx_asset_rel_tgt_type', 'asset_relation', ['target_id', 'relation_type'])
    op.create_index('idx_asset_rel_user_type', 'asset_relation', ['user_id', 'relation_type'])


def downgrade() -> None:
    # ===== asset_relation (依赖 asset_registry, 先删) =====
    op.drop_index('idx_asset_rel_user_type', table_name='asset_relation')
    op.drop_index('idx_asset_rel_tgt_type', table_name='asset_relation')
    op.drop_index('idx_asset_rel_src_type_tgt', table_name='asset_relation')
    op.drop_index('ix_asset_relation_user_id', table_name='asset_relation')
    op.drop_index('ix_asset_relation_neo4j_synced', table_name='asset_relation')
    op.drop_index('ix_asset_relation_relation_type', table_name='asset_relation')
    op.drop_index('ix_asset_relation_target_id', table_name='asset_relation')
    op.drop_index('ix_asset_relation_source_id', table_name='asset_relation')
    op.drop_index('ix_asset_relation_id', table_name='asset_relation')
    op.drop_table('asset_relation')

    # ===== asset_version (依赖 asset_registry, 先删) =====
    op.drop_index('idx_asset_ver_user_created', table_name='asset_version')
    op.drop_index('idx_asset_ver_asset_is_current', table_name='asset_version')
    op.drop_index('idx_asset_ver_asset_version', table_name='asset_version')
    op.drop_index('ix_asset_version_user_id', table_name='asset_version')
    op.drop_index('ix_asset_version_is_current', table_name='asset_version')
    op.drop_index('ix_asset_version_version', table_name='asset_version')
    op.drop_index('ix_asset_version_asset_id', table_name='asset_version')
    op.drop_index('ix_asset_version_id', table_name='asset_version')
    op.drop_table('asset_version')

    # ===== asset_registry (最后删) =====
    op.drop_index('idx_asset_reg_quality_score', table_name='asset_registry')
    op.drop_index('idx_asset_reg_type_status', table_name='asset_registry')
    op.drop_index('idx_asset_reg_user_is_deleted', table_name='asset_registry')
    op.drop_index('idx_asset_reg_user_status_module', table_name='asset_registry')
    op.drop_index('idx_asset_reg_ref_type_ref_id', table_name='asset_registry')
    op.drop_index('idx_asset_reg_user_type_status', table_name='asset_registry')
    op.drop_index('ix_asset_registry_user_id', table_name='asset_registry')
    op.drop_index('ix_asset_registry_is_deleted', table_name='asset_registry')
    op.drop_index('ix_asset_registry_status', table_name='asset_registry')
    op.drop_index('ix_asset_registry_module', table_name='asset_registry')
    op.drop_index('ix_asset_registry_ref_id', table_name='asset_registry')
    op.drop_index('ix_asset_registry_ref_type', table_name='asset_registry')
    op.drop_index('ix_asset_registry_asset_type', table_name='asset_registry')
    op.drop_index('ix_asset_registry_name', table_name='asset_registry')
    op.drop_index('ix_asset_registry_asset_code', table_name='asset_registry')
    op.drop_index('ix_asset_registry_id', table_name='asset_registry')
    op.drop_table('asset_registry')
