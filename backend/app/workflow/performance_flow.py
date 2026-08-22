"""
性能测试工作流

流程图:
    RequirementAgent → Filter(性能场景提取)
    → RAGAgent → Filter(历史性能数据)
    → CaseAgent → Filter(性能场景格式化)
    → ScriptAgent(性能脚本生成)

数据流:
    requirement(str) → {intent, performance_scenarios, test_points}
    → {query} → RAG → {history_scripts, elements}
    → {scenarios, elements} → Case → {performance_cases}
    → {test_cases} → Script → {script_content, script_format}
"""
import logging
from typing import Any, Dict

from app.workflow.base import BaseFlow
from app.workflow.nodes import AgentNode, FilterNode
from app.workflow.state import WorkflowState

logger = logging.getLogger(__name__)


class PerformanceFlow(BaseFlow):
    """性能测试工作流

    流程:
        RequirementAgent → Filter → RAGAgent → Filter
        → CaseAgent → Filter → ScriptGenerationAgent

    使用:
        flow = PerformanceFlow()
        state = WorkflowState.create(
            requirement="测试登录接口的并发性能",
            metadata={"test_type": "performance"}
        )
        result = await flow.run(state)
    """

    def __init__(self) -> None:
        super().__init__(
            name="performance_test_flow",
            description="性能测试: 需求解析 → 历史数据检索 → 性能用例生成 → JMeter脚本生成",
        )
        self._build_graph()

    def _build_graph(self) -> None:
        """构建性能测试工作流图"""

        # 1. 需求解析节点
        req_node = AgentNode(
            name="requirement",
            agent_name="requirement_agent",
            action="analyze",
            input_keys=[],
            output_key="requirement",
            description="解析性能测试需求, 输出性能场景和测试策略",
        )

        # 2. 性能场景过滤
        req_filter = FilterNode(
            name="requirement_filter",
            filter_func=_extract_performance_scenario,
            output_key="rag_input",
            description="从需求中提取性能测试场景和检索关键词",
        )

        # 3. RAG 检索节点 — 检索历史性能脚本和数据
        rag_node = AgentNode(
            name="rag",
            agent_name="rag_agent",
            action="retrieve",
            input_keys=["query"],
            output_key="rag",
            description="检索历史性能测试脚本和参考用例",
        )

        # 4. 历史数据过滤
        rag_filter = FilterNode(
            name="rag_filter",
            filter_func=_extract_performance_history,
            output_key="case_input",
            description="从 RAG 结果中提取历史性能数据和参考脚本",
        )

        # 5. 性能用例生成节点
        case_node = AgentNode(
            name="case",
            agent_name="case_agent",
            action="generate",
            input_keys=["intent", "steps", "elements", "requirement_analysis"],
            output_key="case",
            description="生成性能测试用例 (并发数、持续时间、指标阈值)",
        )

        # 6. 性能场景格式化
        case_filter = FilterNode(
            name="case_filter",
            filter_func=_format_performance_cases,
            output_key="script_input",
            description="格式化性能用例数据, 添加 JMeter 配置",
        )

        # 7. 脚本生成节点 — 生成 JMeter 脚本
        script_node = AgentNode(
            name="script",
            agent_name="script_generation_agent",
            action="execute",
            input_keys=["test_cases", "elements", "target_url", "requirement"],
            output_key="script",
            description="生成 JMeter 性能测试脚本",
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
            "target_url": req.get("target_url", ""),
            "rag_scripts_count": len(rag.get("scripts", [])) if rag else 0,
            "test_case": case.get("case_name", "") if case else "",
            "script_content": script.get("script_content", "") if script else "",
            "script_format": script.get("script_format", "jmeter") if script else "",
            "script_quality": script.get("script_quality", 0.0) if script else 0.0,
        }


# ================================================================== #
#  Filter 函数                                                         #
# ================================================================== #

def _extract_performance_scenario(state: WorkflowState) -> Dict[str, Any]:
    """从需求解析结果中提取性能测试场景"""
    req_output = state.get_node_output("requirement")
    intent = req_output.get("intent", "")
    summary = req_output.get("summary", "")
    steps = req_output.get("steps", [])
    test_points = req_output.get("test_points", [])

    # 构建性能场景检索 query
    perf_keywords = ["性能", "并发", "压力", "负载", "吞吐", "响应时间", "TPS", "QPS"]
    query_parts = [summary or intent or state.requirement]
    for tp in test_points:
        if isinstance(tp, dict):
            query_parts.append(tp.get("description", ""))
        elif isinstance(tp, str):
            query_parts.append(tp)

    return {
        "query": " ".join(query_parts),
        "intent": intent,
        "performance_scenarios": test_points,
        "target_url": req_output.get("target_url", ""),
    }


def _extract_performance_history(state: WorkflowState) -> Dict[str, Any]:
    """从 RAG 结果中提取历史性能数据"""
    rag_output = state.get_node_output("rag")
    req_output = state.get_node_output("requirement")

    # 历史脚本和用例作为参考
    history_scripts = rag_output.get("scripts", [])
    history_cases = rag_output.get("cases", [])

    return {
        "elements": rag_output.get("elements", []),
        "requirement_analysis": {
            "intent": req_output.get("intent", ""),
            "summary": req_output.get("summary", ""),
            "steps": req_output.get("steps", []),
            "target_url": req_output.get("target_url", ""),
            "test_points": req_output.get("test_points", []),
        },
        "history_scripts": history_scripts,
        "history_cases": history_cases,
    }


def _format_performance_cases(state: WorkflowState) -> Dict[str, Any]:
    """格式化性能用例数据"""
    case_output = state.get_node_output("case")
    rag_output = state.get_node_output("rag")
    req_output = state.get_node_output("requirement")

    return {
        "test_cases": [case_output] if case_output else [],
        "elements": rag_output.get("elements", []),
        "target_url": req_output.get("target_url", ""),
        "requirement": state.requirement,
        # 性能测试特殊参数
        "script_format": "jmeter",
    }
