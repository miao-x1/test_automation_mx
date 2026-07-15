"""
测试点模型

存储从测试需求中分析出的测试点。

注意：此表与已有的 test_point 表不同：
- test_point: 关联 session_id（旧架构）
- test_case_point: 关联 requirement_id（新架构，测试用例生成流程）

关系：
  TestRequirement (1) → (N) TestCasePoint (1) → (N) TestCase
"""
from sqlalchemy import Column, String, Text, Integer, Boolean, ForeignKey, Index
from app.models.base import OwnedModel


class TestCasePoint(OwnedModel):
    """测试点

    由 TestPointAnalysisAgent 从需求中分析得出，
    每个测试点对应一个或多个测试用例。

    字段说明：
    - requirement_id: 关联的测试需求ID
    - name: 测试点名称（如"账号密码登录"）
    - description: 测试点详细描述
    - priority: 优先级（P0/P1/P2/P3）
    - type: 测试类型（functional/error/boundary/permission/data_validation）
    - scenario: 测试场景描述
    - expected_behavior: 期望的系统行为
    - case_count: 已生成的用例数
    """
    __tablename__ = "test_case_point"

    # 关联信息
    requirement_id = Column(
        Integer, ForeignKey("test_requirement.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="关联的测试需求ID"
    )

    # 测试点信息
    name = Column(
        String(200), nullable=False,
        comment="测试点名称"
    )
    description = Column(
        Text, nullable=True,
        comment="测试点描述"
    )
    priority = Column(
        String(5), nullable=False, default="P1",
        comment="优先级: P0/P1/P2/P3"
    )
    type = Column(
        String(30), nullable=False, default="functional",
        comment="测试类型: functional/error/boundary/permission/data_validation"
    )
    scenario = Column(
        String(500), nullable=True,
        comment="测试场景描述"
    )
    expected_behavior = Column(
        Text, nullable=True,
        comment="期望的系统行为"
    )

    # 统计
    case_count = Column(
        Integer, nullable=False, default=0,
        comment="已生成的用例数"
    )
    is_deleted = Column(
        Boolean, nullable=False, default=False, index=True,
        comment="软删除"
    )


# 索引
Index("idx_tcp_req", TestCasePoint.requirement_id)
Index("idx_tcp_priority", TestCasePoint.priority)
Index("idx_tcp_type", TestCasePoint.type)
