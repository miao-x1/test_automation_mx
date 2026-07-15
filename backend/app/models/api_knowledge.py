"""
APIKnowledge 模型 - 接口知识库

支持从 Swagger / OpenAPI / Postman / JMeter / JSON 自动解析：
  接口 → 参数 → Header → Body → Response → 数据库

建立接口依赖关系，后续 API Agent 能查询相关接口。
"""
import enum
from sqlalchemy import (
    Column, String, Integer, Text, Boolean, Float,
    ForeignKey, Index, JSON,
)
from app.models.base import OwnedModel


class APISourceType(str, enum.Enum):
    """接口来源类型"""
    SWAGGER = "swagger"
    OPENAPI = "openapi"
    POSTMAN = "postman"
    JMETER = "jmeter"
    JSON = "json"
    MANUAL = "manual"
    AI_GENERATED = "ai_generated"


class APIKnowledge(OwnedModel):
    """接口知识表

    存储完整的接口信息：方法、路径、参数、Header、Body、Response。
    一次解析永久存储，后续 API Agent 直接查询。
    """
    __tablename__ = "api_knowledge"

    # 接口标识
    api_name = Column(
        String(200), nullable=False, index=True,
        comment="接口名称（语义描述）"
    )
    method = Column(
        String(10), nullable=False, default="GET", index=True,
        comment="HTTP方法: GET/POST/PUT/DELETE/PATCH"
    )
    path = Column(
        String(500), nullable=False, index=True,
        comment="接口路径 /api/v1/xxx"
    )
    full_url = Column(
        String(1024), nullable=True,
        comment="完整URL（含baseURL）"
    )

    # 来源信息
    source_type = Column(
        String(20), nullable=False, default=APISourceType.MANUAL,
        index=True, comment="来源: swagger/openapi/postman/jmeter/json/manual/ai_generated"
    )
    source_file = Column(
        String(500), nullable=True,
        comment="来源文件路径"
    )

    # 接口描述
    summary = Column(
        String(500), nullable=True,
        comment="接口摘要"
    )
    description = Column(
        Text, nullable=True,
        comment="接口详细描述"
    )
    tags = Column(
        String(500), nullable=True,
        comment="接口标签（逗号分隔，如: user,auth）"
    )
    module = Column(
        String(100), nullable=True, index=True,
        comment="所属模块: auth/user/order/admin等"
    )

    # 请求信息
    parameters_json = Column(
        Text, nullable=True,
        comment="请求参数列表(JSON): [{name, in, type, required, description, default, enum}]"
    )
    headers_json = Column(
        Text, nullable=True,
        comment="请求头列表(JSON): [{key, value, required, description}]"
    )
    request_body_json = Column(
        Text, nullable=True,
        comment="请求体(JSON): {content_type, schema, example, required_fields}"
    )

    # 响应信息
    responses_json = Column(
        Text, nullable=True,
        comment="响应列表(JSON): [{status_code, description, content_type, schema, example}]"
    )
    success_response_example = Column(
        Text, nullable=True,
        comment="成功响应示例(JSON)"
    )

    # 认证信息
    auth_type = Column(
        String(50), nullable=True,
        comment="认证类型: bearer/basic/apikey/none"
    )
    auth_details = Column(
        Text, nullable=True,
        comment="认证详情(JSON)"
    )

    # 依赖关系
    depends_on_json = Column(
        Text, nullable=True,
        comment="依赖的接口列表(JSON): [{api_path, method, dependency_type, description}]"
    )
    consumed_by_json = Column(
        Text, nullable=True,
        comment="被哪些接口依赖(JSON): [{api_path, method}]"
    )

    # 数据库操作
    db_operations_json = Column(
        Text, nullable=True,
        comment="接口操作的数据库表(JSON): [{table, operation: SELECT/INSERT/UPDATE/DELETE}]"
    )

    # 三库存储状态
    milvus_id = Column(
        Integer, nullable=True,
        comment="Milvus 向量ID"
    )
    neo4j_synced = Column(
        Boolean, default=False, nullable=False,
        comment="Neo4j 是否已同步"
    )

    # 版本
    version = Column(
        String(20), nullable=True,
        comment="API版本（如 v1, v2）"
    )
    is_deprecated = Column(
        Boolean, default=False, nullable=False,
        comment="是否已废弃"
    )

    __table_args__ = (
        Index("idx_api_knowledge_method_path", "method", "path"),
        Index("idx_api_knowledge_module_tags", "module", "tags"),
    )


class APIDependency(OwnedModel):
    """接口依赖关系表

    存储接口之间的依赖关系：
      接口A 依赖 接口B（例如：删除用户依赖登录获取token）
    """
    __tablename__ = "api_dependency"

    api_id = Column(
        Integer, ForeignKey("api_knowledge.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="接口ID"
    )
    depends_on_api_id = Column(
        Integer, ForeignKey("api_knowledge.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="依赖的接口ID"
    )
    dependency_type = Column(
        String(50), nullable=False, default="data",
        comment="依赖类型: data/auth/sequence/conditional"
    )
    description = Column(
        String(500), nullable=True,
        comment="依赖说明"
    )

    __table_args__ = (
        Index("idx_api_dep_api_depends", "api_id", "depends_on_api_id"),
    )
