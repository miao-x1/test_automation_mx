"""
测试需求模型

存储用户输入的测试需求信息，作为测试用例生成流程的起点。

关系：
  TestRequirement (1) → (N) TestCasePoint (1) → (N) TestCase (1) → (N) TestCaseReview
  TestRequirement (1) → (1) MindMap
"""
from sqlalchemy import Column, String, Text, Integer, Index
from app.models.base import OwnedModel


class TestRequirement(OwnedModel):
    """测试需求

    用户通过自然语言/图片/文档/API文档/数据库Schema输入的测试需求。
    作为测试用例生成流程的入口数据。

    字段说明：
    - task_id: 关联的AgentRuntime任务ID（用于追踪执行流程）
    - content: 需求内容（文本描述）
    - source_type: 需求来源类型
    - raw_input: 原始输入数据（JSON，包含图片URL、文件路径等）
    - parsed_result: 解析结果（JSON，RequirementAnalysisAgent的输出）
    - status: 需求状态
    """
    __tablename__ = "test_requirement"

    # 关联信息
    task_id = Column(
        String(64), nullable=True, index=True,
        comment="关联的AgentRuntime任务ID"
    )

    # 需求内容
    content = Column(
        Text, nullable=False,
        comment="需求内容（文本描述）"
    )
    source_type = Column(
        String(20), nullable=False, default="text",
        comment="需求来源: text/image/pdf/word/api_doc/db_schema"
    )
    raw_input = Column(
        Text, nullable=True,
        comment="原始输入数据(JSON)，包含图片URL、文件路径等"
    )

    # 解析结果
    parsed_result = Column(
        Text, nullable=True,
        comment="需求解析结果(JSON)，RequirementAnalysisAgent的输出"
    )

    # 状态
    status = Column(
        String(20), nullable=False, default="pending",
        comment="状态: pending/analyzing/analyzed/generating/completed/failed"
    )


# 索引
Index("idx_test_req_task", TestRequirement.task_id)
Index("idx_test_req_status", TestRequirement.status)
Index("idx_test_req_source", TestRequirement.source_type)
