"""
UI 测试工作流

流程图:
    RequirementAgent → Filter(需求提取) → RAGAgent → Filter(元素提取)
    → CaseAgent → Filter(用例提取) → ScriptGenerationAgent

数据流:
    requirement(str) → {intent, steps, target_url, test_points}
    → {steps} → RAG → {elements, cases, scripts}
    → {requirement_analysis, elements} → Case → {case_name, steps, assertions}
    → {test_cases, elements} → Script → {script_content, script_quality}
"""
import logging
from typing import Any, Dict

from app.workflow.base import BaseFlow
from app.workflow.nodes import AgentNode, FilterNode
from app.workflow.state import WorkflowState

logger = logging.getLogger(__name__)


class UIFlow(BaseFlow):
    """UI 自动化测试工作流

    需求测试流程:
        RequirementAgent → Filter → RAGAgent → Filter → CaseAgent → Filter → ScriptAgent

    使用:
        flow = UIFlow()
        state = WorkflowState.create(requirement="测试登录功能")
        result = await flow.run(state)
    """

    def __init__(self) -> None:
        super().__init__(
            name="ui_test_flow",
            description="UI自动化测试: 需求解析 → RAG检索 → 用例生成 → 脚本生成",
        )
        self._build_graph()

    def _build_graph(self) -> None:
        """构建 UI 测试工作流图"""

        # ===== 节点定义 =====

        # 1. 需求解析节点
        req_node = AgentNode(
            name="requirement",
            agent_name="requirement_agent",
            action="analyze",
            input_keys=[],  # 只需 requirement (自动注入)
            output_key="requirement",
            description="解析用户需求, 输出意图、步骤、测试点",
        )

        # 2. 需求过滤 — 提取 RAG 需要的步骤数据
        req_filter = FilterNode(
            name="requirement_filter",
            filter_func=_extract_rag_query,
            output_key="rag_input",
            description="从需求解析结果中提取 RAG 检索所需的步骤",
        )

        # 3. RAG 检索节点
        rag_node = AgentNode(
            name="rag",
            agent_name="rag_agent",
            action="retrieve_batch",
            input_keys=["steps"],
            output_key="rag",
            description="根据步骤检索页面元素、历史用例、历史脚本",
        )

        # 4. 元素过滤 — 提取 CaseAgent 需要的 elements
        rag_filter = FilterNode(
            name="rag_filter",
            filter_func=_extract_elements,
            output_key="elements_input",
            description="从 RAG 结果中提取页面元素列表",
        )

        # 5. 用例生成节点
        case_node = AgentNode(
            name="case",
            agent_name="case_agent",
            action="generate",
            input_keys=["intent", "steps", "elements", "requirement_analysis"],
            output_key="case",
            description="根据需求和 RAG 元素生成测试用例",
        )

        # 6. 用例过滤 — 提取 ScriptAgent 需要的 test_cases
        case_filter = FilterNode(
            name="case_filter",
            filter_func=_extract_test_cases,
            output_key="script_input",
            description="从用例结果中提取脚本生成所需的用例数据",
        )

        # 7. 脚本生成节点
        script_node = AgentNode(
            name="script",
            agent_name="script_generation_agent",
            action="execute",
            input_keys=["test_cases", "elements", "target_url", "requirement"],
            output_key="script",
            description="根据用例和元素生成自动化测试脚本",
        )

        # ===== 边定义 (线性 DAG) =====
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
        """构建最终结果"""
        req = state.get_node_output("requirement")
        rag = state.get_node_output("rag")
        case = state.get_node_output("case")
        script = state.get_node_output("script")

        return {
            "workflow_name": self.name,
            "requirement": state.requirement,
            "intent": req.get("intent", ""),
            "target_url": req.get("target_url", ""),
            "rag_elements_count": len(rag.get("elements", [])) if rag else 0,
            "rag_cases_count": len(rag.get("cases", [])) if rag else 0,
            "test_case": case.get("case_name", "") if case else "",
            "script_content": script.get("script_content", "") if script else "",
            "script_format": script.get("script_format", "playwright") if script else "",
            "script_quality": script.get("script_quality", 0.0) if script else 0.0,
            "degradation_info": script.get("degradation_info") if script else None,
        }


# ================================================================== #
#  Filter 函数 — 集成 BaseFilter 数据过滤层                          #
# ================================================================== #

def _extract_rag_query(state: WorkflowState) -> Dict[str, Any]:
    """从需求解析结果中提取 RAG 检索所需的步骤 (使用 RequirementFilter)"""
    from app.agent.filter import RequirementFilter

    req_output = state.get_node_output("requirement")

    # 使用 RequirementFilter 过滤需求解析输出
    filtered = RequirementFilter().apply_to_workflow(req_output)

    steps = filtered.get("steps", [])

    # 如果没有步骤, 从需求文本生成查询
    if not steps:
        intent = filtered.get("intent", "")
        summary = filtered.get("summary", "")
        query = intent or summary or state.requirement
        return {"query": query, "steps": [query]}

    return {"steps": steps, "query": steps[0] if steps else state.requirement}


def _extract_elements(state: WorkflowState) -> Dict[str, Any]:
    """从 RAG 结果中提取 CaseAgent 需要的 elements (使用 UiRagFilter)"""
    from app.agent.filter import UiRagFilter

    rag_output = state.get_node_output("rag")

    # 使用 UiRagFilter 过滤 RAG 输出 (删除 scripts, 描述等)
    filtered = UiRagFilter().apply_to_workflow(rag_output)

    elements = filtered.get("elements", [])

    # 合并 requirement 的步骤到 elements_input
    req_output = state.get_node_output("requirement")
    return {
        "elements": elements,
        "requirement_analysis": {
            "intent": req_output.get("intent", ""),
            "summary": req_output.get("summary", ""),
            "steps": req_output.get("steps", []),
            "target_url": req_output.get("target_url", ""),
            "test_points": req_output.get("test_points", []),
        },
    }


def _extract_test_cases(state: WorkflowState) -> Dict[str, Any]:
    """从用例结果中提取 ScriptAgent 需要的数据 (使用 UiCaseFilter)"""
    from app.agent.filter import UiCaseFilter

    case_output = state.get_node_output("case")

    # 使用 UiCaseFilter 过滤用例输出
    filtered = UiCaseFilter().apply_to_workflow(case_output)

    rag_output = state.get_node_output("rag")
    req_output = state.get_node_output("requirement")

    return {
        "test_cases": [filtered] if filtered else [],
        "elements": rag_output.get("elements", []),
        "target_url": req_output.get("target_url", ""),
        "requirement": state.requirement,
    }
