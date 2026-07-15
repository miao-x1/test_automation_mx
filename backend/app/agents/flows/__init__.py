"""
业务流 Agent 模块

所有 Agent 继承 BaseRoutedAgent（RoutedAgent），
通过 @message_handler 接收消息，
通过 publish_message() 发布下一步消息。

业务流：
    RequirementMessage → RequirementAgent → PageMessage
    PageMessage       → ImageAgent       → CaseMessage
    CaseMessage        → CaseAgent        → ReviewMessage
    ReviewMessage      → ReviewAgent      → ScriptMessage
    ScriptMessage      → ScriptGenerationAgent → ExportMessage
    ExportMessage      → ExportAgent      → ResultMessage → CollectorAgent

设计原则：
1. 所有 Agent 继承 RoutedAgent，禁止直接函数调用
2. 所有处理逻辑放在 @message_handler
3. 所有通信通过 publish_message() / send_message()
4. 每一步输出保存数据库（FlowResult）
5. 所有消息 Pydantic BaseModel，完全可序列化，支持分布式部署
"""
from app.agent.requirement.requirement_agent import RequirementAgent
from app.agents.flows.image_agent import ImageAgent
from app.agent.case.case_agent import CaseAgent
from app.agent.case.review_agent import ReviewAgent
from app.agent.script.script_generation_agent import ScriptGenerationAgent as ScriptAgent
from app.agents.flows.export_agent import ExportAgent
from app.agents.flows.human_feedback_agent import HumanFeedbackAgent

# 测试用例生成流程 Agent（阶段四新增）
from app.agents.flows.testcase import (
    TestPointAgent,
    TestCaseGeneratorAgent,
    TestCaseReviewAgent,
    TestCaseStorageAgent,
    FLOW_TESTCASE_SPECS,
)

# Flow Agent 注册表（供 AgentFactory 使用）
# 合并通用流程 Agent 和测试用例生成流程 Agent
FLOW_AGENT_SPECS = [
    *FLOW_TESTCASE_SPECS,  # 测试用例生成流程（阶段四）
    {
        "name": "flow_requirement_agent",
        "display_name": "需求解析Agent(Flow)",
        "description": "接收RequirementMessage，解析需求，发布PageMessage",
        "module_path": "app.agent.requirement.requirement_agent",
        "class_name": "RequirementAgent",
        "model_alias": "qwen",
        "capabilities": ["requirement_parse", "flow"],
    },
    {
        "name": "flow_image_agent",
        "display_name": "页面元素Agent(Flow)",
        "description": "接收PageMessage，分析页面元素，发布CaseMessage",
        "module_path": "app.agents.flows.image_agent",
        "class_name": "ImageAgent",
        "model_alias": "qwen_vl",
        "capabilities": ["vision", "flow"],
    },
    {
        "name": "flow_case_agent",
        "display_name": "用例生成Agent(Flow)",
        "description": "接收CaseMessage，生成测试用例，发布ReviewMessage",
        "module_path": "app.agent.case.case_agent",
        "class_name": "CaseAgent",
        "model_alias": "deepseek",
        "capabilities": ["case_generate", "flow"],
    },
    {
        "name": "flow_review_agent",
        "display_name": "用例审查Agent(Flow)",
        "description": "接收ReviewMessage，审查用例，发布ScriptMessage",
        "module_path": "app.agent.case.review_agent",
        "class_name": "ReviewAgent",
        "model_alias": "claude",
        "capabilities": ["review", "flow"],
    },
    {
        "name": "flow_script_agent",
        "display_name": "脚本生成Agent(Flow)",
        "description": "统一脚本生成入口，整合复用检查+策略选择+4级降级链",
        "module_path": "app.agent.script.script_generation_agent",
        "class_name": "ScriptGenerationAgent",
        "model_alias": "qwen_coder",
        "capabilities": ["script_generate", "flow"],
    },
    {
        "name": "flow_export_agent",
        "display_name": "结果导出Agent(Flow)",
        "description": "接收ExportMessage，保存结果，投递ResultMessage给CollectorAgent",
        "module_path": "app.agents.flows.export_agent",
        "class_name": "ExportAgent",
        "model_alias": "qwen",
        "capabilities": ["export", "flow"],
    },
]

__all__ = [
    "RequirementAgent",
    "ImageAgent",
    "CaseAgent",
    "ReviewAgent",
    "ScriptAgent",
    "ExportAgent",
    "HumanFeedbackAgent",
    # 测试用例生成流程
    "TestPointAgent",
    "TestCaseGeneratorAgent",
    "TestCaseReviewAgent",
    "TestCaseStorageAgent",
    "FLOW_TESTCASE_SPECS",
    "FLOW_AGENT_SPECS",
]
