"""
测试资产中心 — 数据模型

设计原则:
  1. 不与既有 test_asset / test_case / api_endpoint / ui_element / script 等表冲突
  2. 通过 ref_type + ref_id 软关联到既有业务表, 不加外键约束
  3. 表名使用 asset_* 前缀, 与既有 test_* 前缀区分
  4. 继承 OwnedModel, 保持用户隔离与软删除一致性

三张表:
  - asset_registry: 资产索引主表 (统一抽象所有测试资产)
  - asset_version:   版本快照表 (每次发布生成不可变快照)
  - asset_relation:  资产关系表 (有向关系, 同步 Neo4j)
"""
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Column, String, Text, Integer, Float, Boolean, ForeignKey, Index, DateTime,
)
from sqlalchemy.orm import relationship

from app.models.base import OwnedModel


# ============================================================
# 枚举 (使用字符串常量, 避免与既有 AssetType / AssetStatus 冲突)
# ============================================================

class AssetRegistryType:
    """资产类型 — 对应 ref_type 的人类可读标签

    取值:
      - api_endpoint:  API 接口 (关联 api_endpoint 表)
      - ui_element:    UI 元素 (关联 ui_element 表)
      - test_case:     测试用例 (关联 test_case 表, TestCaseGeneratorAgent 生成)
      - test_asset:    测试资产 (关联 test_asset 表, Case First 用例)
      - script:        测试脚本 (关联 script 表)
      - test_data:     测试数据 (无既有表, 内容存 extra_metadata)
      - test_report:   测试报告 (关联 execution 表)
      - requirement:   需求 (关联 requirement_task 表)
      - test_plan / test_design / execution / defect / regression / archive
    """
    API_ENDPOINT = "api_endpoint"
    UI_ELEMENT = "ui_element"
    TEST_CASE = "test_case"
    TEST_ASSET = "test_asset"
    SCRIPT = "script"
    TEST_DATA = "test_data"
    TEST_REPORT = "test_report"
    REQUIREMENT = "requirement"
    TEST_PLAN = "test_plan"
    TEST_DESIGN = "test_design"
    EXECUTION = "execution"
    DEFECT = "defect"
    REGRESSION = "regression"
    ARCHIVE = "archive"

    ALL = (
        API_ENDPOINT, UI_ELEMENT, TEST_CASE, TEST_ASSET,
        SCRIPT, TEST_DATA, TEST_REPORT, REQUIREMENT,
        TEST_PLAN, TEST_DESIGN, EXECUTION, DEFECT, REGRESSION, ARCHIVE,
    )


class AssetRegistryStatus:
    """资产状态 — 状态机: draft → active → deprecated → archived

    流转规则:
      draft     → active (publish)
      draft     → archived
      active    → deprecated
      active    → archived
      deprecated → active (re-publish)
      deprecated → archived
      archived  → draft (recover, 仅恢复, 不直接发布)
    """
    DRAFT = "draft"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    ARCHIVED = "archived"

    ALL = (DRAFT, ACTIVE, DEPRECATED, ARCHIVED)


class AssetRegistrySource:
    """资产来源 — 标识资产如何产生

    取值:
      - manual:  手工录入
      - swagger: 从 Swagger / OpenAPI 文档导入
      - postman: 从 Postman Collection 导入
      - har:     从 HAR 文件导入
      - import:  其他来源导入
      - ai:      AI 自动生成
      - auto:    系统自动沉淀
    """
    MANUAL = "manual"
    SWAGGER = "swagger"
    POSTMAN = "postman"
    HAR = "har"
    IMPORT = "import"
    AI = "ai"
    AUTO = "auto"

    ALL = (MANUAL, SWAGGER, POSTMAN, HAR, IMPORT, AI, AUTO)


class AssetRelationType:
    """资产关系类型 — 有向关系, source → target

    取值:
      - DEPENDS_ON:     源依赖目标 (用例依赖接口 / 脚本依赖数据)
      - USED_BY:        目标被源使用 (反向引用, 用于影响面分析)
      - IMPLEMENTS:     源实现目标 (脚本实现用例)
      - COVERS:         源覆盖目标 (用例覆盖需求)
      - DERIVED_FROM:   源派生自目标 (测试数据派生)
      - VERIFIES:        源验证目标 (用例验证接口 / 用例验证页面)
      - CONTAINS:        源包含目标 (页面包含元素 / 用例包含步骤)
      - CONFLICTS_WITH:  源与目标冲突 (用例与用例覆盖冲突)
      - PRODUCES:        源产出目标 (用例→脚本→执行)
      - CAUSED:          源导致目标 (执行→缺陷)
      - REGRESSED:       源回归验证目标 (回归→缺陷)
      - REPORTS:         源汇总目标 (报告→链路)
    """
    DEPENDS_ON = "DEPENDS_ON"
    USED_BY = "USED_BY"
    IMPLEMENTS = "IMPLEMENTS"
    COVERS = "COVERS"
    DERIVED_FROM = "DERIVED_FROM"
    VERIFIES = "VERIFIES"
    CONTAINS = "CONTAINS"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    PRODUCES = "PRODUCES"
    CAUSED = "CAUSED"
    REGRESSED = "REGRESSED"
    REPORTS = "REPORTS"

    ALL = (
        DEPENDS_ON, USED_BY, IMPLEMENTS, COVERS,
        DERIVED_FROM, VERIFIES, CONTAINS, CONFLICTS_WITH,
        PRODUCES, CAUSED, REGRESSED, REPORTS,
    )


# ============================================================
# 模型
# ============================================================

class AssetRegistry(OwnedModel):
    """资产索引主表 — 所有测试资产的统一入口

    设计要点:
      1. asset_code 业务可读 (如 ASSET-2026-0001), 与主键 id 分离
      2. ref_type + ref_id 软关联到既有业务表, 不加 FK 约束
      3. status 走状态机, 由 AssetService 校验流转
      4. quality_score 由 AssetOptimizationAgent 计算, 0-100
      5. reuse_count 反规范化, 提升排序性能
      6. extra_metadata JSON 存放各资产类型的扩展字段
    """
    __tablename__ = "asset_registry"

    # ===== 业务标识 =====
    asset_code = Column(
        String(64), nullable=False, unique=True, index=True,
        comment="资产编码, 业务可读, 如 ASSET-2026-0001",
    )
    name = Column(
        String(200), nullable=False, index=True,
        comment="资产名称",
    )

    # ===== 资产类型与关联 =====
    asset_type = Column(
        String(30), nullable=False, index=True,
        comment="资产类型: 见 AssetRegistryType.ALL",
    )
    ref_type = Column(
        String(50), nullable=False, index=True,
        comment="关联表名: api_endpoint / ui_element / test_case 等",
    )
    ref_id = Column(
        Integer, nullable=False, index=True,
        comment="关联记录 ID (软外键, 不加 FK 约束)",
    )

    # ===== 描述信息 =====
    summary = Column(
        String(500), nullable=True,
        comment="一句话摘要",
    )
    description = Column(
        Text, nullable=True,
        comment="详细说明 (Markdown)",
    )
    module = Column(
        String(100), nullable=True, index=True,
        comment="所属业务模块: 用户中心 / 订单 / 商品",
    )
    tags = Column(
        String(500), nullable=True,
        comment="标签 (逗号分隔)",
    )

    # ===== 状态与版本 =====
    status = Column(
        String(20), nullable=False, default=AssetRegistryStatus.DRAFT, index=True,
        comment="状态: draft / active / deprecated / archived",
    )
    source = Column(
        String(20), nullable=False, default=AssetRegistrySource.MANUAL,
        comment="来源: manual / swagger / postman / har / import / ai",
    )
    version = Column(
        Integer, nullable=False, default=1,
        comment="当前版本号 (从 1 起, 单调递增)",
    )

    # ===== 评估指标 =====
    quality_score = Column(
        Float, nullable=False, default=0.0,
        comment="资产质量评分 0-100, 由 AssetOptimizationAgent 计算",
    )
    reuse_count = Column(
        Integer, nullable=False, default=0,
        comment="被复用次数 (反规范化, 提升查询性能)",
    )
    last_used_at = Column(
        DateTime, nullable=True,
        comment="最近被使用时间",
    )

    # ===== 扩展字段 =====
    extra_metadata = Column(
        Text, nullable=True,
        comment="扩展元数据 JSON (各资产类型自定义字段)",
    )

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, nullable=False, default=False, index=True,
        comment="软删除标记",
    )

    # ===== 关联 (ORM 层) =====
    versions = relationship(
        "AssetVersion",
        back_populates="asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relations_as_source = relationship(
        "AssetRelation",
        foreign_keys="AssetRelation.source_id",
        back_populates="source_asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    relations_as_target = relationship(
        "AssetRelation",
        foreign_keys="AssetRelation.target_id",
        back_populates="target_asset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # 列表页常用过滤: 用户 + 类型 + 状态
        Index("idx_asset_reg_user_type_status", "user_id", "asset_type", "status"),
        # 反查业务对象对应的资产: ref_type + ref_id
        Index("idx_asset_reg_ref_type_ref_id", "ref_type", "ref_id"),
        # 模块筛选: 用户 + 状态 + 模块
        Index("idx_asset_reg_user_status_module", "user_id", "status", "module"),
        # 软删除过滤
        Index("idx_asset_reg_user_is_deleted", "user_id", "is_deleted"),
        # 全局统计: 类型 + 状态
        Index("idx_asset_reg_type_status", "asset_type", "status"),
        # 高质量资产优先召回
        Index("idx_asset_reg_quality_score", "quality_score"),
        {"comment": "测试资产索引主表 — 所有测试资产的统一入口"},
    )

    def __repr__(self) -> str:
        return (
            f"<AssetRegistry(id={self.id}, code={self.asset_code}, "
            f"type={self.asset_type}, status={self.status})>"
        )


class AssetVersion(OwnedModel):
    """资产版本快照表 — 每次发布生成不可变快照

    设计要点:
      1. snapshot_json 存资产完整字段快照 (含详情表字段)
      2. is_current 标记当前版本, 便于快速定位
      3. change_type 区分创建 / 更新 / 回滚 / 状态变更
      4. diff_summary 存与上一版本的差异 (字段级)
      5. 回滚 = 用快照覆盖当前字段 + 产生新版本 (不删除历史)
    """
    __tablename__ = "asset_version"

    # ===== 关联 =====
    asset_id = Column(
        Integer,
        ForeignKey("asset_registry.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="关联 asset_registry.id",
    )
    asset = relationship("AssetRegistry", back_populates="versions")

    # ===== 版本信息 =====
    version = Column(
        Integer, nullable=False, index=True,
        comment="版本号 (从 1 起, 单调递增)",
    )
    snapshot_json = Column(
        Text, nullable=False,
        comment="资产完整快照 JSON (含详情表字段)",
    )
    change_log = Column(
        String(500), nullable=True,
        comment="变更说明",
    )
    change_type = Column(
        String(20), nullable=False, default="update",
        comment="变更类型: create / update / rollback / status_change",
    )
    diff_summary = Column(
        Text, nullable=True,
        comment="与上一版本的差异摘要 JSON (字段级)",
    )
    is_current = Column(
        Boolean, nullable=False, default=False, index=True,
        comment="是否为当前版本 (用于快速定位)",
    )

    # ===== 发布信息 =====
    published_by = Column(
        Integer, nullable=True,
        comment="发布人 ID",
    )

    __table_args__ = (
        # 同一资产版本号唯一
        Index("idx_asset_ver_asset_version", "asset_id", "version", unique=True),
        # 快速定位当前版本
        Index("idx_asset_ver_asset_is_current", "asset_id", "is_current"),
        # 用户时间线
        Index("idx_asset_ver_user_created", "user_id", "created_at"),
        {"comment": "资产版本快照表 — 每次发布生成不可变快照"},
    )

    def __repr__(self) -> str:
        return (
            f"<AssetVersion(id={self.id}, asset_id={self.asset_id}, "
            f"version={self.version}, is_current={self.is_current})>"
        )


class AssetRelation(OwnedModel):
    """资产关系表 — 资产之间的有向关系

    设计要点:
      1. source_id → target_id, 有向关系
      2. relation_type 见 AssetRelationType.ALL
      3. weight 影响推荐排序, 默认 1.0
      4. metadata JSON 存关系扩展字段 (如 coverage_pct)
      5. neo4j_synced 跟踪同步状态, 失败由补偿任务重试
      6. 同一 source + type + target 唯一, 防止重复关系
    """
    __tablename__ = "asset_relation"

    # ===== 关联 =====
    source_id = Column(
        Integer,
        ForeignKey("asset_registry.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="源资产 ID",
    )
    target_id = Column(
        Integer,
        ForeignKey("asset_registry.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="目标资产 ID",
    )

    # ===== 关系信息 =====
    relation_type = Column(
        String(30), nullable=False, index=True,
        comment="关系类型: 见 AssetRelationType.ALL",
    )
    weight = Column(
        Float, nullable=False, default=1.0,
        comment="关系权重 (影响推荐排序)",
    )
    metadata_json = Column(
        Text, nullable=True,
        comment="关系扩展元数据 JSON",
    )

    # ===== Neo4j 同步状态 =====
    neo4j_synced = Column(
        Boolean, nullable=False, default=False, index=True,
        comment="是否已同步到 Neo4j",
    )
    neo4j_synced_at = Column(
        DateTime, nullable=True,
        comment="最近成功同步到 Neo4j 的时间",
    )

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, nullable=False, default=False,
        comment="软删除标记",
    )

    # ===== 关联 (ORM 层) =====
    source_asset = relationship(
        "AssetRegistry",
        foreign_keys=[source_id],
        back_populates="relations_as_source",
    )
    target_asset = relationship(
        "AssetRegistry",
        foreign_keys=[target_id],
        back_populates="relations_as_target",
    )

    __table_args__ = (
        # 同一 source + type + target 唯一, 防止重复关系
        Index(
            "idx_asset_rel_src_type_tgt",
            "source_id", "relation_type", "target_id",
            unique=True,
        ),
        # 反向查询: target + type
        Index("idx_asset_rel_tgt_type", "target_id", "relation_type"),
        # 用户 + 类型
        Index("idx_asset_rel_user_type", "user_id", "relation_type"),
        # 未同步批处理扫描
        Index("idx_asset_rel_neo4j_synced", "neo4j_synced"),
        {"comment": "资产关系表 — 资产之间的有向关系, 同步 Neo4j"},
    )

    def __repr__(self) -> str:
        return (
            f"<AssetRelation(id={self.id}, {self.source_id} "
            f"-[{self.relation_type}]-> {self.target_id})>"
        )
