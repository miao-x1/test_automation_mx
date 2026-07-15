"""
ApiMetadata模型 - API元数据

存储从需求中提取的API信息，支持：
  - API列表管理
  - 与Session关联
  - 用例生成引用
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import OwnedModel


class ApiMetadata(OwnedModel):
    """API元数据"""
    __tablename__ = "api_metadata"

    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="会话ID"
    )
    method = Column(
        String(10), nullable=False, default="GET",
        comment="HTTP方法: GET/POST/PUT/DELETE/PATCH"
    )
    url = Column(
        String(500), nullable=False,
        comment="API路径"
    )
    summary = Column(
        String(500), nullable=True,
        comment="API描述"
    )
    request_schema = Column(
        Text, nullable=True,
        comment="请求体Schema(JSON)"
    )
    response_schema = Column(
        Text, nullable=True,
        comment="响应体Schema(JSON)"
    )
    headers = Column(
        Text, nullable=True,
        comment="请求头(JSON)"
    )
    tags = Column(
        String(500), nullable=True,
        comment="标签(JSON数组)"
    )
    source = Column(
        String(20), nullable=False, default="ai",
        comment="来源: ai/swagger/manual"
    )


Index('idx_api_metadata_session', ApiMetadata.session_id)
