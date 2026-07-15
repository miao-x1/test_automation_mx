"""
需求分析结果模型

L1 输出：RequirementResult
存储 L1 分析产出的 features（测试意图）
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import OwnedModel


class RequirementResult(OwnedModel):
    """L1 需求分析结果"""
    __tablename__ = "requirement_result"

    title = Column(
        String(200), nullable=False, comment="需求标题"
    )
    source_type = Column(
        String(20), nullable=False, default="text", comment="来源类型: text/pdf/swagger/url"
    )
    source_ref = Column(
        String(500), nullable=True, comment="来源引用（文件路径/URL）"
    )
    raw_input = Column(
        Text, nullable=True, comment="原始输入文本"
    )
    features = Column(
        Text, nullable=False, comment="L1分析结果（JSON数组）: [{title, type, test_points, risk_level}]"
    )
    case_task_id = Column(
        Integer, ForeignKey("case_task.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="关联的CaseTask ID"
    )
    status = Column(
        String(20), nullable=False, default="completed", comment="状态: completed/failed"
    )
    error_message = Column(
        Text, nullable=True, comment="错误信息"
    )

Index('idx_req_result_user', RequirementResult.user_id, RequirementResult.created_at)
