"""项目内专业测试任务工作台。不替代 RequirementTask / TestJob，只做统一外壳。"""
from sqlalchemy import Column, String, Text, Integer, Index

from app.db.types import MEDIUMTEXT
from app.models.base import OwnedModel


class ProjectTestTask(OwnedModel):
    """专业测试人员的任务工作区：登录/支付等局部目标。"""
    __tablename__ = "project_test_task"
    __table_args__ = (
        Index("idx_ptt_project", "user_id", "project_id", "status"),
    )

    project_id = Column(Integer, nullable=False, index=True, comment="所属项目")
    name = Column(String(200), nullable=False, comment="任务名称，如登录功能")
    focus = Column(String(200), nullable=True, comment="当前关注模块")
    status = Column(String(20), nullable=False, default="draft", comment="draft/ready/running/done")
    requirement_text = Column(MEDIUMTEXT, nullable=True, comment="当前任务需求")
    analysis_json = Column(MEDIUMTEXT, nullable=True, comment="测试分析结果")
    strategy_json = Column(MEDIUMTEXT, nullable=True, comment="测试策略")
    test_requirement_id = Column(Integer, nullable=True, comment="关联 test_requirement.id")
    last_execution_id = Column(Integer, nullable=True)
    extra_json = Column(Text, nullable=True)
