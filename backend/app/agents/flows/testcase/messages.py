"""
测试用例生成流程 - 消息类型定义

所有消息继承 FlowMessage（在 app.agents.messages 中定义），完全可序列化。

流程：
    TestPointMessage       → TestPointAgent         → TestCaseMessage
    TestCaseMessage        → TestCaseGeneratorAgent → TestCaseReviewMessage
    TestCaseReviewMessage  → TestCaseReviewAgent    → StorageMessage
    StorageMessage         → TestCaseStorageAgent   → ResultMessage（流程结束）

消息携带字段说明：
- TestPointMessage: 需求解析结果（业务模块、功能点、业务流程、测试范围）
- TestCaseMessage:  测试点列表 + RAG上下文
- TestCaseReviewMessage: 生成的用例列表 + 覆盖说明
- StorageMessage: 已存在，复用（storage_type/operation/table/data）
- ResultMessage: 已存在，复用（通知流程结束）
"""
from typing import Any, Dict, List, Optional
from pydantic import Field

from app.agents.messages import FlowMessage


# ================================================================ #
#  Step 1: 测试点消息                                                 #
# ================================================================ #

class TestPointMessage(FlowMessage):
    """
    测试点消息 - 需求分析结果 → 测试点分析Agent

    携带需求解析的结构化结果，由 TestPointAgent 分析生成测试点列表。

    字段说明：
    - business_module: 业务模块名称（如：用户中心、订单管理）
    - function_points: 功能点列表，每项含 name/description/key_actions
    - business_flow: 业务流程列表，每项含 step/action/target/expected
    - test_scope: 测试范围，含 included/excluded/priority_modules
    - requirement_id: 关联的测试需求ID（用于数据库关联）
    """
    step: str = "test_point"
    business_module: str = ""
    function_points: List[Dict[str, Any]] = Field(default_factory=list)
    business_flow: List[Dict[str, Any]] = Field(default_factory=list)
    test_scope: Dict[str, Any] = Field(default_factory=dict)
    requirement_id: Optional[int] = None


# ================================================================ #
#  Step 2: 用例生成消息                                               #
# ================================================================ #

class TestCaseMessage(FlowMessage):
    """
    用例生成消息 - 测试点分析Agent → 用例生成Agent

    携带测试点列表和RAG上下文，由 TestCaseGeneratorAgent 生成结构化用例。

    字段说明：
    - test_points: 测试点列表，每项含 name/type/priority/scenario/description
    - rag_context: RAG检索上下文（历史用例、页面元素等，可选）
    - business_module: 业务模块名称（用于RAG查询）
    - requirement_id: 关联的测试需求ID
    """
    step: str = "testcase_generate"
    test_points: List[Dict[str, Any]] = Field(default_factory=list)
    rag_context: Dict[str, Any] = Field(default_factory=dict)
    business_module: str = ""
    requirement_id: Optional[int] = None


# ================================================================ #
#  Step 3: 用例审查消息                                               #
# ================================================================ #

class TestCaseReviewMessage(FlowMessage):
    """
    用例审查消息 - 用例生成Agent → 用例审查Agent

    携带生成的测试用例列表，由 TestCaseReviewAgent 审查用例质量。

    注意：与已有的 ReviewMessage 不同（ReviewMessage 用于脚本生成流程），
    此消息专用于测试用例生成流程，携带更丰富的用例和测试点关联信息。

    字段说明：
    - test_cases: 生成的测试用例列表
    - test_points: 关联的测试点列表（用于审查时对照）
    - case_count: 用例数量
    - coverage_notes: 覆盖说明
    - rag_used: 是否使用了RAG上下文
    - business_module: 业务模块名称
    - requirement_id: 关联的测试需求ID
    """
    step: str = "testcase_review"
    test_cases: List[Dict[str, Any]] = Field(default_factory=list)
    test_points: List[Dict[str, Any]] = Field(default_factory=list)
    case_count: int = 0
    coverage_notes: str = ""
    rag_used: bool = False
    business_module: str = ""
    requirement_id: Optional[int] = None
