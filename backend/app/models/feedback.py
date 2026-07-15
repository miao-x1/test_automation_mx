"""
用户反馈模型

存储用户对脚本执行结果的评分和反馈，支持重新生成流程
"""
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Index
from app.models.base import OwnedModel


class Feedback(OwnedModel):
    """
    用户反馈表

    存储用户对执行结果的评分、评论，以及反馈驱动的重新生成信息
    """
    __tablename__ = "feedback"

    requirement_id = Column(
        Integer,
        ForeignKey("requirement_task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="需求任务ID"
    )

    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的测试任务ID"
    )

    script_id = Column(
        Integer,
        nullable=True,
        comment="关联的脚本ID"
    )

    score = Column(
        Integer,
        nullable=False,
        comment="用户评分: 1=不满意, 2=一般, 3=满意, 4=非常满意, 5=完美"
    )

    comment = Column(
        Text,
        nullable=True,
        comment="用户反馈评论/问题描述"
    )

    accepted = Column(
        Boolean,
        default=None,
        nullable=True,
        comment="是否接受脚本: True=接受, False=拒绝, None=未评价"
    )

    failure_analysis = Column(
        Text,
        nullable=True,
        comment="FeedbackAgent分析的失败原因(JSON)"
    )

    regenerated = Column(
        Boolean,
        default=False,
        nullable=False,
        comment="是否已基于反馈重新生成脚本"
    )

    def __repr__(self):
        return f"<Feedback(id={self.id}, req_id={self.requirement_id}, score={self.score})>"


Index('idx_feedback_requirement', Feedback.requirement_id)
Index('idx_feedback_score', Feedback.score)
