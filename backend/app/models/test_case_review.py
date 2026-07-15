"""
测试用例审核模型

存储 TestCaseReviewAgent 对测试用例的审核结果。

关系：
  TestCase (1) → (N) TestCaseReview
"""
from sqlalchemy import Column, String, Text, Integer, Float, ForeignKey, Index
from app.models.base import BaseModel


class TestCaseReview(BaseModel):
    """测试用例审核结果

    由 TestCaseReviewAgent 生成，记录用例质量评分和改进建议。

    字段说明：
    - case_id: 关联的测试用例ID
    - score: 质量评分（0-100）
    - suggestion: 改进建议（JSON数组）
    - review_result: 审核结果（pass/need_revision/reject）
    - issues: 问题列表（JSON数组）
    """
    __tablename__ = "test_case_review"

    # 关联信息
    case_id = Column(
        Integer, ForeignKey("test_case.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="关联的测试用例ID"
    )

    # 审核结果
    score = Column(
        Float, nullable=False, default=0.0,
        comment="质量评分(0-100)"
    )
    review_result = Column(
        String(20), nullable=False, default="need_revision",
        comment="审核结果: pass/need_revision/reject"
    )

    # 详细信息
    suggestion = Column(
        Text, nullable=True,
        comment="改进建议(JSON数组)"
    )
    issues = Column(
        Text, nullable=True,
        comment="问题列表(JSON数组)"
    )
    review_comment = Column(
        Text, nullable=True,
        comment="审核备注"
    )


# 索引
Index("idx_tcr_case", TestCaseReview.case_id)
Index("idx_tcr_result", TestCaseReview.review_result)
Index("idx_tcr_score", TestCaseReview.score)
