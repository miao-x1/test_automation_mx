"""
测试资产中心 Pydantic Schemas

定义资产索引 / 版本 / 关系的请求/响应数据结构,与 SQLAlchemy Model 解耦。
- 所有 JSON 字段(extra_metadata / metadata_json / snapshot_json)在 schema 层用 dict 表达,
  序列化由 repository 层处理。
- 枚举值集合与 app/models/asset_registry.py 中的常量类保持一致。
"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.asset_registry import (
    AssetRegistryType,
    AssetRegistryStatus,
    AssetRegistrySource,
    AssetRelationType,
)


# ============================================================
# 基础字段类型
# ============================================================

class AssetRef(BaseModel):
    """资产软关联引用 — 指向既有业务表记录

    ref_type + ref_id 不加 FK 约束,由 service 层校验存在性。
    ref_id 允许 0 (纯索引资产, 如 test_data 无既有业务表)。
    """
    ref_type: str = Field(
        ...,
        description="关联表名: api_endpoint / ui_element / test_case / "
                    "test_asset / script / test_data / test_report / requirement",
    )
    ref_id: int = Field(default=0, ge=0, description="关联记录 ID, 0 表示纯索引资产")


class AssetRefItem(AssetRef):
    """带资产概要的引用信息(响应使用)"""
    asset_id: Optional[int] = Field(default=None, description="资产索引 ID")
    asset_code: Optional[str] = Field(default=None, description="资产编码")
    name: Optional[str] = Field(default=None, description="资产名称")


# ============================================================
# 资产创建 / 更新
# ============================================================

class AssetCreate(BaseModel):
    """创建资产索引请求

    两种用法:
      1. 关联既有业务表: 必填 ref_type + ref_id
      2. 纯索引资产(test_data 等无既有表): ref_type='test_data', ref_id=0,
         内容存 extra_metadata
    """
    asset_code: Optional[str] = Field(
        default=None, max_length=64,
        description="资产编码, 不传则系统生成 (ASSET-YYYY-NNNN)",
    )
    name: str = Field(..., min_length=1, max_length=200, description="资产名称")
    asset_type: str = Field(
        ...,
        description="资产类型: api_endpoint / ui_element / test_case / "
                    "test_asset / script / test_data / test_report / requirement",
    )
    ref_type: str = Field(
        ...,
        description="关联表名 (与 asset_type 通常一致, test_data 等可独立)",
    )
    ref_id: int = Field(default=0, ge=0, description="关联记录 ID, 0 表示纯索引资产")
    summary: Optional[str] = Field(default=None, max_length=500, description="一句话摘要")
    description: Optional[str] = Field(default=None, description="详细说明 (Markdown)")
    module: Optional[str] = Field(default=None, max_length=100, description="所属业务模块")
    tags: Optional[List[str]] = Field(default=None, description="标签列表")
    source: str = Field(default="manual", description="来源: manual/swagger/postman/har/import/ai")
    extra_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="扩展元数据 (各资产类型自定义字段, 如 method/path/content_json)",
    )

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, v: str) -> str:
        if v not in AssetRegistryType.ALL:
            raise ValueError(
                f"asset_type 必须是 {list(AssetRegistryType.ALL)} 之一"
            )
        return v

    @field_validator("ref_type")
    @classmethod
    def validate_ref_type(cls, v: str) -> str:
        # ref_type 限定为已知业务表名集合
        allowed = {
            "api_endpoint", "ui_element", "test_case", "test_asset",
            "script", "test_data", "test_report", "requirement",
            "test_plan", "test_design", "execution", "defect",
            "regression", "archive",
        }
        if v not in allowed:
            raise ValueError(
                f"ref_type 必须是 {sorted(allowed)} 之一"
            )
        return v

    @field_validator("source")
    @classmethod
    def validate_source(cls, v: str) -> str:
        if v not in AssetRegistrySource.ALL:
            raise ValueError(
                f"source 必须是 {list(AssetRegistrySource.ALL)} 之一"
            )
        return v

    @model_validator(mode="after")
    def validate_ref(self) -> "AssetCreate":
        """ref_id>0 时, ref_type 必须与 asset_type 匹配 (test_data 除外)"""
        if self.ref_id > 0 and self.asset_type != AssetRegistryType.TEST_DATA:
            if self.ref_type != self.asset_type:
                raise ValueError(
                    f"ref_type({self.ref_type}) 必须与 asset_type({self.asset_type}) 一致, "
                    f"或 asset_type=test_data (纯索引资产)"
                )
        return self


class AssetUpdate(BaseModel):
    """更新资产请求(所有字段可选)"""
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=500)
    description: Optional[str] = Field(default=None)
    module: Optional[str] = Field(default=None, max_length=100)
    tags: Optional[List[str]] = Field(default=None)
    quality_score: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="质量评分 0-100 (由 AssetOptimizationAgent 计算)",
    )
    extra_metadata: Optional[Dict[str, Any]] = Field(default=None)


class AssetQueryParams(BaseModel):
    """资产列表查询参数"""
    keyword: Optional[str] = Field(
        default=None, description="关键词, 匹配 name/asset_code/summary",
    )
    asset_type: Optional[str] = Field(default=None, description="资产类型过滤")
    status: Optional[str] = Field(default=None, description="状态过滤")
    module: Optional[str] = Field(default=None, description="模块过滤")
    source: Optional[str] = Field(default=None, description="来源过滤")
    tags: Optional[List[str]] = Field(default=None, description="标签过滤(任一匹配)")
    ref_type: Optional[str] = Field(default=None, description="关联表名过滤")
    min_quality: Optional[float] = Field(
        default=None, ge=0, le=100, description="最低质量评分",
    )
    page: int = Field(default=1, ge=1, description="页码, 从 1 开始")
    page_size: int = Field(default=20, ge=1, le=100, description="每页条数")

    @field_validator("asset_type")
    @classmethod
    def validate_asset_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in AssetRegistryType.ALL:
            raise ValueError(
                f"asset_type 必须是 {list(AssetRegistryType.ALL)} 之一"
            )
        return v

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if v not in AssetRegistryStatus.ALL:
            raise ValueError(
                f"status 必须是 {list(AssetRegistryStatus.ALL)} 之一"
            )
        return v


class PublishRequest(BaseModel):
    """发布资产(生成版本快照)"""
    change_log: str = Field(default="", max_length=500, description="变更说明")
    change_type: str = Field(
        default="update",
        description="变更类型: create / update / rollback / status_change",
    )

    @field_validator("change_type")
    @classmethod
    def validate_change_type(cls, v: str) -> str:
        allowed = {"create", "update", "rollback", "status_change"}
        if v not in allowed:
            raise ValueError(f"change_type 必须是 {sorted(allowed)} 之一")
        return v


class StateTransitionRequest(BaseModel):
    """状态机流转请求"""
    target_status: str = Field(
        ...,
        description="目标状态: draft / active / deprecated / archived",
    )
    reason: Optional[str] = Field(
        default=None, max_length=500,
        description="流转原因 (记录到版本快照)",
    )

    @field_validator("target_status")
    @classmethod
    def validate_target_status(cls, v: str) -> str:
        if v not in AssetRegistryStatus.ALL:
            raise ValueError(
                f"target_status 必须是 {list(AssetRegistryStatus.ALL)} 之一"
            )
        return v


# ============================================================
# 资产关系
# ============================================================

class RelationCreate(BaseModel):
    """创建资产关系请求"""
    source_id: int = Field(..., gt=0, description="源资产 ID")
    target_id: int = Field(..., gt=0, description="目标资产 ID")
    relation_type: str = Field(
        ...,
        description="关系类型: DEPENDS_ON / USED_BY / IMPLEMENTS / COVERS / "
                    "DERIVED_FROM / VERIFIES / CONTAINS / CONFLICTS_WITH",
    )
    weight: float = Field(default=1.0, ge=0, le=10, description="关系权重 0-10")
    metadata: Optional[Dict[str, Any]] = Field(
        default=None, description="关系扩展元数据 (如 coverage_pct)",
    )

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: str) -> str:
        v = v.upper()
        if v not in AssetRelationType.ALL:
            raise ValueError(
                f"relation_type 必须是 {list(AssetRelationType.ALL)} 之一"
            )
        return v

    @model_validator(mode="after")
    def validate_self_relation(self) -> "RelationCreate":
        if self.source_id == self.target_id:
            raise ValueError("source_id 与 target_id 不能相同")
        return self


class RelationUpdate(BaseModel):
    """更新资产关系(部分字段)"""
    weight: Optional[float] = Field(default=None, ge=0, le=10)
    metadata: Optional[Dict[str, Any]] = Field(default=None)


class RelationQueryParams(BaseModel):
    """资产关系查询参数"""
    asset_id: Optional[int] = Field(
        default=None, description="查询该资产的出入关系 (source 或 target)",
    )
    direction: Optional[str] = Field(
        default=None, description="方向过滤: outgoing / incoming",
    )
    relation_type: Optional[str] = Field(default=None, description="关系类型过滤")
    target_type: Optional[str] = Field(
        default=None, description="对端资产类型过滤",
    )
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.lower()
        if v not in {"outgoing", "incoming"}:
            raise ValueError("direction 必须是 ['outgoing', 'incoming'] 之一")
        return v

    @field_validator("relation_type")
    @classmethod
    def validate_relation_type(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.upper()
        if v not in AssetRelationType.ALL:
            raise ValueError(
                f"relation_type 必须是 {list(AssetRelationType.ALL)} 之一"
            )
        return v


# ============================================================
# 资产搜索 (AssetSearchAgent 输入输出)
# ============================================================

class SearchRequest(BaseModel):
    """资产搜索请求

    三源融合搜索:
      - MySQL: 关键词 / 类型 / 标签匹配
      - Milvus: 语义向量召回 (async, 命中时返回 vector_score)
      - Neo4j: 关系图谱扩展 (async, 命中时返回 relation_score)

    final_score = 0.5 * mysql_score + 0.3 * vector_score + 0.2 * relation_score
    """
    query: str = Field(..., min_length=1, max_length=500, description="自然语言查询")
    asset_types: Optional[List[str]] = Field(
        default=None, description="限定资产类型 (为空则全量)",
    )
    module: Optional[str] = Field(default=None, description="模块过滤")
    tags: Optional[List[str]] = Field(default=None, description="标签过滤")
    include_inactive: bool = Field(
        default=False, description="是否包含 deprecated / archived 资产",
    )
    limit: int = Field(default=10, ge=1, le=50, description="返回数量上限")
    use_vector: bool = Field(default=True, description="是否启用 Milvus 向量召回")
    use_relation: bool = Field(default=True, description="是否启用 Neo4j 关系扩展")

    @field_validator("asset_types")
    @classmethod
    def validate_asset_types(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        for t in v:
            if t not in AssetRegistryType.ALL:
                raise ValueError(
                    f"asset_types 中包含非法类型 {t}, "
                    f"合法值: {list(AssetRegistryType.ALL)}"
                )
        return v


class MatchReason(BaseModel):
    """单个命中原因 (用于搜索结果可解释性)"""
    source: str = Field(
        ..., description="命中来源: mysql / milvus / neo4j",
    )
    field: Optional[str] = Field(
        default=None, description="命中字段 (mysql 用: name / summary / tags)",
    )
    score: float = Field(..., ge=0, le=1, description="该来源得分 0-1")
    detail: Optional[str] = Field(default=None, description="命中详情")


class SearchHitItem(BaseModel):
    """搜索结果项 (含三源得分与命中原因)"""
    asset_id: int
    asset_code: str
    name: str
    asset_type: str
    status: str
    module: Optional[str] = None
    summary: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    quality_score: float = Field(default=0.0)
    reuse_count: int = Field(default=0)
    mysql_score: float = Field(default=0.0, description="MySQL 关键词得分 0-1")
    vector_score: Optional[float] = Field(
        default=None, description="Milvus 语义相似度 0-1, 未启用时为 None",
    )
    relation_score: Optional[float] = Field(
        default=None, description="Neo4j 关系关联度 0-1, 未启用时为 None",
    )
    final_score: float = Field(..., description="融合得分 0-1")
    match_reasons: List[MatchReason] = Field(
        default_factory=list, description="命中原因列表 (可解释性)",
    )


class SearchResponse(BaseModel):
    """搜索响应"""
    query: str = Field(description="原始查询")
    total: int = Field(description="命中总数")
    hits: List[SearchHitItem] = Field(default_factory=list)
    elapsed_ms: int = Field(..., description="查询耗时 (毫秒)")
    sources_used: List[str] = Field(
        ..., description="实际使用的检索源: mysql / milvus / neo4j",
    )


# ============================================================
# 资产复用建议 (AssetReuseAgent 输出)
# ============================================================

class ReuseSuggestionItem(BaseModel):
    """复用建议项"""
    asset_id: int
    asset_code: str
    name: str
    asset_type: str
    reuse_score: float = Field(
        ..., ge=0, le=1,
        description="复用得分 0-1, = 0.35*coverage + 0.20*field_match "
                    "+ 0.15*quality + 0.15*recency + 0.15*history",
    )
    coverage: float = Field(..., ge=0, le=1, description="需求覆盖率 0-1")
    field_match: float = Field(..., ge=0, le=1, description="字段匹配度 0-1")
    quality: float = Field(..., ge=0, le=100, description="资产质量评分 0-100")
    recency: float = Field(..., ge=0, le=1, description="时效性 0-1 (越近越高)")
    history: float = Field(..., ge=0, le=1, description="历史复用率 0-1")
    suggestion: str = Field(..., description="建议: reuse / adapt / skip")
    reason: str = Field(..., description="建议理由")


class ReuseDecision(BaseModel):
    """复用决策汇总"""
    requirement: str = Field(..., description="原始需求描述")
    can_reuse: bool = Field(..., description="是否建议复用")
    suggestions: List[ReuseSuggestionItem] = Field(default_factory=list)
    missing_assets: List[str] = Field(
        default_factory=list, description="缺失资产类型 (需新建)",
    )
    summary: str = Field(..., description="决策摘要")


# ============================================================
# 响应模型
# ============================================================

class AssetResponse(BaseModel):
    """资产详情响应"""
    id: int
    asset_code: str
    name: str
    asset_type: str
    ref_type: str
    ref_id: int
    summary: Optional[str] = None
    description: Optional[str] = None
    module: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    status: str
    source: str
    version: int
    quality_score: float = 0.0
    reuse_count: int = 0
    last_used_at: Optional[datetime] = None
    extra_metadata: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssetListItem(BaseModel):
    """资产列表项 (精简字段)"""
    id: int
    asset_code: str
    name: str
    asset_type: str
    ref_type: str
    ref_id: int
    summary: Optional[str] = None
    module: Optional[str] = None
    status: str
    source: str
    version: int
    quality_score: float = 0.0
    reuse_count: int = 0
    tags: List[str] = Field(default_factory=list)
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class AssetListResponse(BaseModel):
    """资产列表响应"""
    total: int
    page: int
    page_size: int
    items: List[AssetListItem]


class AssetVersionItem(BaseModel):
    """资产版本项 (列表用)"""
    id: int
    asset_id: int
    version: int
    change_log: Optional[str] = None
    change_type: str
    is_current: bool
    published_by: Optional[int] = None
    created_by: Optional[int] = None
    created_at: datetime


class AssetVersionListResponse(BaseModel):
    """资产版本列表响应"""
    total: int
    page: int
    page_size: int
    items: List[AssetVersionItem]


class AssetVersionDetail(AssetVersionItem):
    """资产版本详情 (含快照)"""
    snapshot: Dict[str, Any] = Field(
        ..., description="资产完整快照 (含详情表字段)",
    )
    diff_summary: Optional[Dict[str, Any]] = Field(
        default=None, description="与上一版本的差异摘要",
    )


class AssetRelationItem(BaseModel):
    """资产关系项"""
    id: int
    source_id: int
    target_id: int
    relation_type: str
    weight: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    neo4j_synced: bool = False
    neo4j_synced_at: Optional[datetime] = None
    # 对端资产概要 (列表展示用)
    source_asset: Optional[AssetRefItem] = None
    target_asset: Optional[AssetRefItem] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AssetRelationListResponse(BaseModel):
    """资产关系列表响应"""
    total: int
    page: int
    page_size: int
    items: List[AssetRelationItem]


class AssetStatsResponse(BaseModel):
    """资产统计响应"""
    total: int = Field(description="资产总数")
    by_type: Dict[str, int] = Field(
        default_factory=dict, description="按类型统计",
    )
    by_status: Dict[str, int] = Field(
        default_factory=dict, description="按状态统计",
    )
    by_module: Dict[str, int] = Field(
        default_factory=dict, description="按模块统计",
    )
    by_source: Dict[str, int] = Field(
        default_factory=dict, description="按来源统计",
    )
    avg_quality_score: float = Field(
        default=0.0, description="平均质量评分",
    )
    total_relations: int = Field(
        default=0, description="资产关系总数",
    )
    pending_neo4j_sync: int = Field(
        default=0, description="待同步 Neo4j 的关系数",
    )


class OperationResult(BaseModel):
    """通用操作结果 (用于软删除 / 状态流转 / 回滚等)"""
    success: bool = True
    asset_id: int
    message: str
    previous_status: Optional[str] = None
    current_status: Optional[str] = None
    new_version: Optional[int] = None


class RelationOperationResult(BaseModel):
    """关系操作结果"""
    success: bool = True
    relation_id: int
    message: str
    neo4j_synced: bool = False
