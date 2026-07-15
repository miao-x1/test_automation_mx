"""
测试用例生成流程 Agent 模块

所有 Agent 继承 BaseRoutedAgent（RoutedAgent），
通过 @message_handler 接收消息，
通过 publish_message() 发布下一步消息。

测试用例生成流程：
    TestPointMessage       → TestPointAgent         → TestCaseMessage
    TestCaseMessage        → TestCaseGeneratorAgent → TestCaseReviewMessage
    TestCaseReviewMessage  → TestCaseReviewAgent    → StorageMessage
    StorageMessage         → TestCaseStorageAgent   → ResultMessage（流程结束）

设计原则：
1. 所有 Agent 继承 BaseRoutedAgent，使用 @default_subscription 装饰器
2. 所有处理逻辑放在 @message_handler 标注的方法中
3. 所有通信通过 publish_message() / send_request()
4. 每一步输出保存数据库（FlowResult）
5. 所有消息继承 FlowMessage，Pydantic BaseModel，完全可序列化
"""
from app.agents.flows.testcase.test_point_agent import TestPointAgent
from app.agents.flows.testcase.testcase_generator_agent import TestCaseGeneratorAgent
from app.agents.flows.testcase.testcase_review_agent import TestCaseReviewAgent
from app.agents.flows.testcase.testcase_storage_agent import TestCaseStorageAgent

# Flow Agent 注册表（供 AgentFactory 使用，格式参考 flows/__init__.py 的 FLOW_AGENT_SPECS）
FLOW_TESTCASE_SPECS = [
    {
        "name": "flow_test_point_agent",
        "display_name": "测试点分析Agent(Flow)",
        "description": "接收TestPointMessage，分析需求生成测试点，发布TestCaseMessage",
        "module_path": "app.agents.flows.testcase.test_point_agent",
        "class_name": "TestPointAgent",
        "model_alias": "deepseek",
        "capabilities": ["test_point_analysis", "testcase_flow"],
    },
    {
        "name": "flow_testcase_generator_agent",
        "display_name": "用例生成Agent(Flow)",
        "description": "接收TestCaseMessage，RAG检索+LLM生成结构化用例，发布TestCaseReviewMessage",
        "module_path": "app.agents.flows.testcase.testcase_generator_agent",
        "class_name": "TestCaseGeneratorAgent",
        "model_alias": "deepseek",
        "capabilities": ["case_generate", "rag", "testcase_flow"],
    },
    {
        "name": "flow_testcase_review_agent",
        "display_name": "用例审查Agent(Flow)",
        "description": "接收TestCaseReviewMessage，审核用例质量，发布StorageMessage",
        "module_path": "app.agents.flows.testcase.testcase_review_agent",
        "class_name": "TestCaseReviewAgent",
        "model_alias": "qwen",
        "capabilities": ["test_case_review", "testcase_flow"],
    },
    {
        "name": "flow_testcase_storage_agent",
        "display_name": "用例存储Agent(Flow)",
        "description": "接收StorageMessage，持久化用例到数据库，生成思维导图，发布ResultMessage",
        "module_path": "app.agents.flows.testcase.testcase_storage_agent",
        "class_name": "TestCaseStorageAgent",
        "model_alias": "qwen",
        "capabilities": ["storage", "testcase_flow"],
    },
]

__all__ = [
    "TestPointAgent",
    "TestCaseGeneratorAgent",
    "TestCaseReviewAgent",
    "TestCaseStorageAgent",
    "FLOW_TESTCASE_SPECS",
]
