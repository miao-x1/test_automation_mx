"""
API 测试工作流

流程图:
    RequirementAgent → Filter(API 意图提取)
    → RAGAgent → Filter(API 知识提取)
    → CaseAgent(compile_stream) → Filter(用例格式化)
    → ScriptAgent(API 脚本生成)

数据流:
    requirement(str) → {intent, api_candidates, test_strategy}
    → {query} → RAG → {api_definitions, test_cases, scripts}
    → {features, api_candidates} → Case(compile) → {http_requests, assertions}
    → {test_cases} → Script → {script_content, script_format}
"""
import logging
from typing import Any, Dict

from app.workflow.base import BaseFlow
from app.workflow.nodes import AgentNode, FilterNode
from app.workflow.state import WorkflowState

logger = logging.getLogger(__name__)


class APIFlow(BaseFlow):
    """API 自动化测试工作流

    流程:
        RequirementAgent → Filter → RAGAgent → Filter
        → CaseAgent(compile) → Filter → ScriptGenerationAgent

    使用:
        flow = APIFlow()
        state = WorkflowState.create(
            requirement="测试用户登录接口",
            metadata={"test_type": "api"}
        )
        result = await flow.run(state)
    """

    def __init__(self) -> None:
        super().__init__(
            name="api_test_flow",
            description="API自动化测试: 需求解析 → API知识检索 → 用例编译 → 脚本生成",
        )
        self._build_graph()

    def _build_graph(self) -> None:
        """构建 API 测试工作流图"""

        # 1. 需求解析节点
        req_node = AgentNode(
            name="requirement",
            agent_name="requirement_agent",
            action="analyze",
            input_keys=[],
            output_key="requirement",
            description="解析 API 测试需求, 输出意图和接口候选",
        )

        # 2. API 意图过滤
        req_filter = FilterNode(
            name="requirement_filter",
            filter_func=_extract_api_intent,
            output_key="rag_input",
            description="从需求中提取 API 测试意图和检索关键词",
        )

        # 3. RAG 检索节点
        rag_node = AgentNode(
            name="rag",
            agent_name="rag_agent",
            action="retrieve",
            input_keys=["query"],
            output_key="rag",
            description="检索 API 定义、历史用例、历史脚本",
        )

        # 4. API 知识过滤
        rag_filter = FilterNode(
            name="rag_filter",
            filter_func=_extract_api_knowledge,
            output_key="case_input",
            description="从 RAG 结果中提取 API 定义和测试特征",
        )

        # 5. 用例编译节点 (compile_stream)
        case_node = AgentNode(
            name="case",
            agent_name="case_agent",
            action="compile",
            input_keys=["features", "rag_context", "requirement_context"],
            output_key="case",
            description="编译结构化 API 测试用例",
        )

        # 6. 用例格式化过滤
        case_filter = FilterNode(
            name="case_filter",
            filter_func=_format_api_test_cases,
            output_key="script_input",
            description="格式化 API 用例数据供脚本生成",
        )

        # 7. 脚本生成节点
        script_node = AgentNode(
            name="script",
            agent_name="script_generation_agent",
            action="execute",
            input_keys=["test_cases", "requirement"],
            output_key="script",
            description="生成 API 自动化测试脚本",
        )

        # ===== 边定义 =====
        self.add_node(req_node)
        self.add_node(req_filter)
        self.add_node(rag_node)
        self.add_node(rag_filter)
        self.add_node(case_node)
        self.add_node(case_filter)
        self.add_node(script_node)

        self.add_edge("requirement", "requirement_filter")
        self.add_edge("requirement_filter", "rag")
        self.add_edge("rag", "rag_filter")
        self.add_edge("rag_filter", "case")
        self.add_edge("case", "case_filter")
        self.add_edge("case_filter", "script")

    def _build_final_result(self, state: WorkflowState) -> Dict[str, Any]:
        req = state.get_node_output("requirement")
        rag = state.get_node_output("rag")
        case = state.get_node_output("case")
        script = state.get_node_output("script")

        return {
            "workflow_name": self.name,
            "requirement": state.requirement,
            "intent": req.get("intent", ""),
            "api_candidates": req.get("api_candidates", []),
            "rag_api_count": len(rag.get("cases", [])) if rag else 0,
            "test_case": case.get("case_name", "") if case else "",
            "script_content": script.get("script_content", "") if script else "",
            "script_format": script.get("script_format", "pytest") if script else "",
            "script_quality": script.get("script_quality", 0.0) if script else 0.0,
        }


# ================================================================== #
#  Filter 函数                                                         #
# ================================================================== #

def _extract_api_intent(state: WorkflowState) -> Dict[str, Any]:
    """从需求解析结果中提取 API 测试意图"""
    req_output = state.get_node_output("requirement")
    intent = req_output.get("intent", "")
    summary = req_output.get("summary", "")
    steps = req_output.get("steps", [])

    # 构建检索 query
    query = intent or summary or state.requirement
    if steps:
        query = f"{query} {' '.join(steps)}"

    return {
        "query": query,
        "intent": intent,
        "api_candidates": req_output.get("api_candidates", []),
    }


def _extract_api_knowledge(state: WorkflowState) -> Dict[str, Any]:
    """从 RAG 结果中提取 API 知识"""
    rag_output = state.get_node_output("rag")
    req_output = state.get_node_output("requirement")

    # 提取 API 定义和历史用例
    api_defs = rag_output.get("cases", [])
    scripts = rag_output.get("scripts", [])

    return {
        "features": {
            "intent": req_output.get("intent", ""),
            "api_candidates": req_output.get("api_candidates", []),
            "test_strategy": req_output.get("test_strategy", {}),
        },
        "rag_context": {
            "api_definitions": api_defs,
            "history_scripts": scripts,
        },
        "requirement_context": {
            "requirement": state.requirement,
            "summary": req_output.get("summary", ""),
        },
    }


def _format_api_test_cases(state: WorkflowState) -> Dict[str, Any]:
    """格式化 API 用例数据"""
    case_output = state.get_node_output("case")
    req_output = state.get_node_output("requirement")

    # CaseAgent.compile() 返回编译后的用例
    test_cases = [case_output] if case_output else []

    return {
        "test_cases": test_cases,
        "requirement": state.requirement,
        "target_url": req_output.get("target_url", ""),
    }
