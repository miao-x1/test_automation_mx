"""
API 接口管理模型

提供独立的"接口管理"能力,与既有 api_knowledge(知识库语义)解耦:
  - ApiEndpoint: 接口基础信息 + 请求/响应结构 + 状态管理
  - ApiEndpointVersion: 接口版本快照,支持版本回溯

设计要点:
  1. 继承 OwnedModel,自动获得 id/created_at/updated_at/user_id/created_by
  2. 软删除(is_deleted),不物理删除,保证历史可追溯
  3. 请求/响应用 JSON 字段存储,灵活适配不同接口形态
  4. 状态机: draft → active → deprecated → archived
  5. 版本号字段(version),每次发布自增,关联 ApiEndpointVersion 表

与 api_knowledge.py 的关系:
  - api_knowledge 偏向 RAG 知识库(milvus_id, neo4j_synced)
  - api_endpoint 是纯接口管理,不绑定三库
  - 未来可通过 ContextRouter 把 api_endpoint 关联到 api_knowledge(可选)
"""
from enum import Enum
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship

from app.models.base import OwnedModel


class EndpointStatus(str, Enum):
    """接口状态机"""
    DRAFT = "draft"           # 草稿: 刚创建,未发布
    ACTIVE = "active"         # 已发布: 可用于测试用例生成
    DEPRECATED = "deprecated" # 已废弃: 不推荐使用,但保留历史
    ARCHIVED = "archived"     # 已归档: 不再使用,仅存档


class EndpointSource(str, Enum):
    """接口来源"""
    MANUAL = "manual"         # 手动创建
    SWAGGER = "swagger"       # 从 Swagger/OpenAPI 导入
    POSTMAN = "postman"       # 从 Postman Collection 导入
    HAR = "har"               # 从 HAR 文件导入
    IMPORT = "import"         # 其他格式导入
    AI_GENERATED = "ai"       # AI 自动识别


class HTTPMethod(str, Enum):
    """HTTP 方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class AuthType(str, Enum):
    """认证类型"""
    NONE = "none"             # 无认证
    BASIC = "basic"           # Basic Auth
    BEARER = "bearer"         # Bearer Token
    API_KEY = "api_key"       # API Key
    OAUTH2 = "oauth2"         # OAuth 2.0
    CUSTOM = "custom"         # 自定义


class ApiEndpoint(OwnedModel):
    """API 接口管理主表

    存储接口的完整定义,包括请求方法、路径、参数、请求体、响应、认证等。
    支持状态管理与版本控制。

    继承 OwnedModel 自动获得:
      id, created_at, updated_at, user_id, created_by
    """
    __tablename__ = "api_endpoint"

    # ===== 基本信息 =====
    name = Column(String(200), nullable=False, comment="接口名称(人类可读)")
    method = Column(String(10), nullable=False, comment="HTTP 方法: GET/POST/PUT/DELETE/PATCH/HEAD/OPTIONS")
    path = Column(String(500), nullable=False, comment="接口路径,如 /api/v1/users/{id}")
    summary = Column(String(500), nullable=True, comment="接口摘要(一句话描述)")
    description = Column(Text, nullable=True, comment="接口详细说明")
    tags = Column(String(500), nullable=True, comment="标签,逗号分隔,如 用户,登录,认证")
    module = Column(String(100), nullable=True, comment="所属模块,如 用户管理/订单管理")

    # ===== 状态与来源 =====
    status = Column(String(20), nullable=False, default="draft", comment="状态: draft/active/deprecated/archived")
    source = Column(String(20), nullable=False, default="manual", comment="来源: manual/swagger/postman/har/import/ai")

    # ===== 请求结构(JSON) =====
    headers_json = Column(Text, nullable=True, comment="请求头 JSON,如 [{key,value,desc}]")
    params_json = Column(Text, nullable=True, comment="Query/Path 参数 JSON,如 [{name,in,type,required,desc}]")
    body_json = Column(Text, nullable=True, comment="请求体 JSON,含 raw/form/json/schema")

    # ===== 响应结构(JSON) =====
    response_json = Column(Text, nullable=True, comment="响应 JSON,含 status_code/headers/body/example")

    # ===== 认证 =====
    auth_type = Column(String(20), nullable=False, default="none", comment="认证类型: none/basic/bearer/api_key/oauth2/custom")
    auth_details_json = Column(Text, nullable=True, comment="认证详情 JSON,不含敏感信息(密钥用占位符)")

    # ===== 版本与删除 =====
    version = Column(Integer, nullable=False, default=1, comment="当前版本号,每次发布自增")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="软删除标记")

    # ===== 关联 =====
    versions = relationship("ApiEndpointVersion", back_populates="endpoint", cascade="all, delete-orphan")

    # ===== 索引 =====
    __table_args__ = (
        Index("ix_api_endpoint_user_status", "user_id", "status"),
        Index("ix_api_endpoint_method_path", "method", "path"),
        Index("ix_api_endpoint_module", "module"),
        Index("ix_api_endpoint_is_deleted", "is_deleted"),
        {"comment": "API 接口管理主表"},
    )

    def __repr__(self):
        return f"<ApiEndpoint(id={self.id}, name={self.name}, method={self.method}, path={self.path})>"


class ApiEndpointVersion(OwnedModel):
    """API 接口版本快照表

    每次接口发布(active)时,把当前完整结构保存为快照。
    支持版本回溯、差异对比、回滚。

    继承 OwnedModel 自动获得:
      id, created_at, updated_at, user_id, created_by
    """
    __tablename__ = "api_endpoint_version"

    endpoint_id = Column(
        Integer,
        ForeignKey("api_endpoint.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的接口 ID",
    )
    version = Column(Integer, nullable=False, comment="版本号,从 1 递增")
    snapshot_json = Column(Text, nullable=False, comment="接口完整快照 JSON,含 method/path/headers/params/body/response")
    change_log = Column(String(500), nullable=True, comment="本次变更说明")
    is_current = Column(Boolean, nullable=False, default=False, comment="是否为当前版本(同一 endpoint 只有一个 true)")

    # ===== 关联 =====
    endpoint = relationship("ApiEndpoint", back_populates="versions")

    # ===== 索引 =====
    __table_args__ = (
        Index("ix_api_endpoint_version_ep_ver", "endpoint_id", "version"),
        {"comment": "API 接口版本快照表"},
    )

    def __repr__(self):
        return f"<ApiEndpointVersion(id={self.id}, endpoint_id={self.endpoint_id}, version={self.version})>"


# ================================================================
# 数据分离子表 (031 迁移新增)
# ================================================================

class ApiHeader(OwnedModel):
    """API 请求头子表 — 每行一个 Header

    替代 api_endpoint.headers_json 的 JSON 文本存储方式。
    每个 Header 独立一行, 支持按 api_id 批量查询。
    """
    __tablename__ = "api_header"

    api_id = Column(
        Integer,
        ForeignKey("api_endpoint.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的接口 ID",
    )
    key = Column(String(200), nullable=False, comment="Header 名, 如 Content-Type")
    value = Column(Text, nullable=True, comment="Header 值")
    required = Column(Boolean, nullable=False, default=True, comment="是否必填")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序序号")

    def __repr__(self):
        return f"<ApiHeader(id={self.id}, api_id={self.api_id}, key={self.key})>"


class ApiBody(OwnedModel):
    """API 请求体子表 — 每个接口最多一行

    替代 api_endpoint.body_json 的 JSON 文本存储方式。
    将 body_type / schema / example 分离为独立列。
    """
    __tablename__ = "api_body"

    api_id = Column(
        Integer,
        ForeignKey("api_endpoint.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的接口 ID",
    )
    body_type = Column(String(50), nullable=False, default="application/json",
                       comment="Body 类型: application/json/form-data/x-www-form-urlencoded/raw")
    schema_json = Column(Text, nullable=True, comment="JSON Schema 定义")
    example_json = Column(Text, nullable=True, comment="示例数据 JSON")
    raw_text = Column(Text, nullable=True, comment="原始文本(当 body_type=raw 时)")

    def __repr__(self):
        return f"<ApiBody(id={self.id}, api_id={self.api_id}, body_type={self.body_type})>"


class ApiParameter(OwnedModel):
    """API 参数子表 — 每行一个参数

    替代 api_endpoint.params_json 的 JSON 文本存储方式。
    将 location / name / type / required 分离为独立列。
    """
    __tablename__ = "api_parameter"

    api_id = Column(
        Integer,
        ForeignKey("api_endpoint.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="关联的接口 ID",
    )
    location = Column(String(20), nullable=False, default="query",
                      comment="参数位置: query/path/header/cookie")
    name = Column(String(200), nullable=False, comment="参数名")
    type = Column(String(50), nullable=False, default="string",
                  comment="参数类型: string/integer/number/boolean/array/object")
    required = Column(Boolean, nullable=False, default=False, comment="是否必填")
    default_value = Column(String(500), nullable=True, comment="默认值")
    description = Column(String(500), nullable=True, comment="参数说明")
    example = Column(String(500), nullable=True, comment="示例值")
    sort_order = Column(Integer, nullable=False, default=0, comment="排序序号")

    def __repr__(self):
        return f"<ApiParameter(id={self.id}, api_id={self.api_id}, name={self.name}, location={self.location})>"
