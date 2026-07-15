"""
TestPoint模型 - 测试点（需求→测试点→测试用例）

禁止：需求→直接生成用例
必须：需求→测试点→测试用例
"""
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey
from app.models.base import OwnedModel


class TestPoint(OwnedModel):
    """测试点"""
    session_id = Column(Integer, ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True, comment="会话ID")
    feature = Column(String(200), nullable=False, comment="所属功能")
    risk_level = Column(String(20), default="medium", comment="风险等级: high/medium/low")
    title = Column(String(500), nullable=False, comment="测试点标题")
    description = Column(Text, nullable=True, comment="测试点描述")
    test_type = Column(String(20), default="API", comment="测试类型: API/UI/WEB/ANDROID")
    priority = Column(String(5), default="P1", comment="优先级: P0/P1/P2/P3")
    # 关联的用例数
    case_count = Column(Integer, default=0, comment="已生成用例数")
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除")
