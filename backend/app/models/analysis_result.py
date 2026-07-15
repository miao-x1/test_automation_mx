"""
分析结果模型
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class AnalysisResult(OwnedModel):
    """
    分析结果表
    
    存储AI Agent对UI图片的分析结果
    一个任务对应一个分析结果
    """
    __tablename__ = "analysis_result"
    
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
        comment="任务ID"
    )
    
    agent_type = Column(
        String(50),
        nullable=False,
        comment="使用的Agent类型"
    )
    
    page_type = Column(
        String(100),
        nullable=True,
        comment="页面类型（如：登录页、列表页）"
    )
    
    elements_json = Column(
        Text,
        nullable=True,
        comment="识别的UI元素JSON"
    )
    
    interactions_json = Column(
        Text,
        nullable=True,
        comment="交互操作JSON"
    )
    
    layout_json = Column(
        Text,
        nullable=True,
        comment="布局信息JSON"
    )
    
    analysis_summary = Column(
        Text,
        nullable=True,
        comment="分析总结"
    )
    
    raw_output = Column(
        Text,
        nullable=True,
        comment="Agent原始输出"
    )
    
    # 关联关系
    task = relationship("Task", back_populates="analysis_result")
    
    def __repr__(self):
        return f"<AnalysisResult(id={self.id}, task_id={self.task_id}, agent={self.agent_type})>"
