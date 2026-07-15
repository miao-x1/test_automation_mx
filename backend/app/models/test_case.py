"""
测试用例模型

存储由 TestCaseGeneratorAgent 生成的标准化测试用例。

关系：
  TestCasePoint (1) → (N) TestCase (1) → (N) TestCaseReview
"""
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, Index
from app.models.base import OwnedModel


class TestCase(OwnedModel):
    """测试用例

    由 TestCaseGeneratorAgent 根据测试点 + RAG上下文生成。

    字段说明：
    - task_id: 关联的AgentRuntime任务ID
    - point_id: 关联的测试点ID
    - case_name: 用例名称
    - precondition: 前置条件
    - steps: 测试步骤（JSON数组）
    - expected_result: 预期结果
    - priority: 优先级
    - type: 用例类型
    - status: 用例状态
    - rag_references: RAG检索引用（JSON，记录参考的历史用例ID等）
    """
    __tablename__ = "test_case"

    # 关联信息
    task_id = Column(
        String(64), nullable=True, index=True,
        comment="关联的AgentRuntime任务ID"
    )
    point_id = Column(
        Integer, ForeignKey("test_case_point.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="关联的测试点ID"
    )

    # 用例内容
    case_name = Column(
        String(200), nullable=False,
        comment="用例名称"
    )
    precondition = Column(
        Text, nullable=True,
        comment="前置条件"
    )
    steps = Column(
        Text, nullable=True,
        comment="测试步骤(JSON数组)"
    )
    expected_result = Column(
        Text, nullable=True,
        comment="预期结果"
    )

    # 分类
    priority = Column(
        String(5), nullable=False, default="P1",
        comment="优先级: P0/P1/P2/P3"
    )
    type = Column(
        String(30), nullable=False, default="functional",
        comment="用例类型: functional/error/boundary/permission/data_validation"
    )

    # 状态
    status = Column(
        String(20), nullable=False, default="draft",
        comment="状态: draft/reviewed/published/archived"
    )

    # RAG引用
    rag_references = Column(
        Text, nullable=True,
        comment="RAG检索引用(JSON)，记录参考的历史用例ID等"
    )

    # 版本
    version = Column(
        Integer, nullable=False, default=1,
        comment="版本号"
    )
    is_deleted = Column(
        Boolean, nullable=False, default=False, index=True,
        comment="软删除"
    )


# 索引
Index("idx_tc_task", TestCase.task_id)
Index("idx_tc_point", TestCase.point_id)
Index("idx_tc_status", TestCase.status)
Index("idx_tc_priority", TestCase.priority)
