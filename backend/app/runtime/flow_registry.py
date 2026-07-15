"""
统一流程注册表

定义所有业务流程，替代 YAML 硬编码。
使用 Python dataclass 定义，提供类型安全和 IDE 自动补全。

支持的流程：
  1. unified_test_flow      统一测试生成（文本/图片/文件/URL 任意组合）
  2. image_test_flow        图片测试（截图分析 → 用例 → 脚本）
  3. requirement_test_flow  需求测试（需求解析 → 分类 → RAG → 用例 → 脚本）
  4. execution_flow          脚本执行（执行 → 反馈 → 知识更新）
  5. knowledge_ingest_flow  知识入库（文档解析 → 向量化 → 存储）
  6. graph_build_flow       图谱构建（关系推理 → 图谱构建）
  7. testcase_pipeline_flow 用例流水线（需求分析 → 测试点 → 用例 → 审查 → 同步）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class FlowStep:
    """流程步骤定义"""
    step_name: str
    agent_name: str
    action: str
    description: str = ""
    required: bool = True                  # 是否必需（失败时终止流程）
    on_failure: str = "abort"             # abort | continue
    condition: Optional[str] = None       # 条件表达式（None=始终执行）


@dataclass
class TaskFlow:
    """流程定义"""
    flow_name: str
    description: str = ""
    steps: List[FlowStep] = field(default_factory=list)


# ══════════════════════════════════════════════════════════════
# 流程定义
# ══════════════════════════════════════════════════════════════

_FLOWS: Dict[str, TaskFlow] = {}


def _register(flow: TaskFlow) -> TaskFlow:
    """注册流程"""
    _FLOWS[flow.flow_name] = flow
    return flow


# ── 1. 统一测试生成流程（唯一入口） ──
_register(TaskFlow(
    flow_name="unified_test_flow",
    description="统一测试生成入口：支持文本/图片/文件任意组合输入",
    steps=[
        # Step 1: 图片元素识别（仅当有图片时执行）
        FlowStep(
            step_name="analyze_image",
            agent_name="element_agent",
            action="analyze",
            description="分析页面截图，识别UI元素和页面URL",
            required=False,
            on_failure="continue",
            condition="has:image_paths",
        ),
        # Step 2: 需求解析（仅当有需求文本时执行）
        FlowStep(
            step_name="parse_requirement",
            agent_name="requirement_agent",
            action="parse",
            description="解析自然语言需求为结构化测试信息",
            required=False,
            on_failure="continue",
            condition="has:requirement",
        ),
        # Step 3: 类型识别
        FlowStep(
            step_name="classify_type",
            agent_name="test_type_classifier",
            action="classify",
            description="识别测试类型（WEB/API/Android/Performance）",
            required=False,
            on_failure="continue",
            condition="no:test_type",
        ),
        # Step 4: 复用检查（可选）
        FlowStep(
            step_name="reuse_check",
            agent_name="script_reuse_agent",
            action="execute",
            description="检查是否有可复用的历史脚本",
            required=False,
            on_failure="continue",
            condition="enable_reuse_check",
        ),
        # Step 5: RAG检索（仅当有 target_url 时执行）
        FlowStep(
            step_name="rag_retrieve",
            agent_name="rag_agent",
            action="retrieve",
            description="RAG检索历史页面元素和用例",
            required=False,
            on_failure="continue",
            condition="has:target_url",
        ),
        # Step 6: 页面关联推理（可选）
        FlowStep(
            step_name="discover_relations",
            agent_name="relation_agent",
            action="execute",
            description="推理页面间关联关系",
            required=False,
            on_failure="continue",
            condition="enable_knowledge_graph",
        ),
        # Step 7: 图谱路径推理（可选）
        FlowStep(
            step_name="graph_reason",
            agent_name="graph_agent",
            action="execute",
            description="基于知识图谱推理测试路径",
            required=False,
            on_failure="continue",
            condition="enable_knowledge_graph",
        ),
        # Step 8: 用例生成（必需）
        FlowStep(
            step_name="generate_cases",
            agent_name="case_agent",
            action="generate",
            description="生成测试用例",
            required=True,
            on_failure="abort",
        ),
        # Step 9: 用例审查（可选）
        FlowStep(
            step_name="review_cases",
            agent_name="review_agent",
            action="review",
            description="审查用例完整性和可执行性",
            required=False,
            on_failure="continue",
            condition="enable_human_review",
        ),
        # Step 10: 脚本生成（必需）
        FlowStep(
            step_name="generate_script",
            agent_name="script_generation_agent",
            action="execute",
            description="统一脚本生成（含4级降级链）",
            required=True,
            on_failure="abort",
        ),
    ],
))


# ── 2. 图片测试流程 ──
_register(TaskFlow(
    flow_name="image_test_flow",
    description="图片测试流程：截图分析 → 用例生成 → 脚本生成",
    steps=[
        FlowStep(
            step_name="analyze_image",
            agent_name="element_agent",
            action="analyze",
            description="分析页面截图，识别UI元素",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="generate_cases",
            agent_name="case_agent",
            action="generate",
            description="根据元素生成测试用例",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="generate_script",
            agent_name="script_generation_agent",
            action="generate",
            description="根据用例生成测试脚本",
            required=True,
            on_failure="abort",
        ),
    ],
))


# ── 3. 需求测试流程 ──
_register(TaskFlow(
    flow_name="requirement_test_flow",
    description="需求测试流程：需求解析 → 类型分类 → RAG检索 → 用例生成 → 用例审查 → 脚本生成",
    steps=[
        FlowStep(
            step_name="parse_requirement",
            agent_name="requirement_agent",
            action="parse",
            description="解析自然语言需求",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="classify_type",
            agent_name="test_type_classifier",
            action="classify",
            description="分类测试类型（WEB/API/PERFORMANCE）",
            required=False,
            on_failure="continue",
        ),
        FlowStep(
            step_name="rag_retrieve",
            agent_name="rag_agent",
            action="retrieve",
            description="RAG检索历史知识",
            required=False,
            on_failure="continue",
        ),
        FlowStep(
            step_name="generate_cases",
            agent_name="case_agent",
            action="generate",
            description="生成测试用例",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="review_cases",
            agent_name="review_agent",
            action="review",
            description="审查测试用例",
            required=False,
            on_failure="continue",
        ),
        FlowStep(
            step_name="generate_script",
            agent_name="script_generation_agent",
            action="generate",
            description="生成测试脚本",
            required=True,
            on_failure="abort",
        ),
    ],
))


# ── 4. 脚本执行流程 ──
_register(TaskFlow(
    flow_name="execution_flow",
    description="脚本执行流程：执行 → 反馈分析 → 知识更新",
    steps=[
        FlowStep(
            step_name="execute_script",
            agent_name="execution_agent",
            action="execute",
            description="执行测试脚本",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="analyze_feedback",
            agent_name="feedback_agent",
            action="analyze",
            description="分析执行结果",
            required=False,
            on_failure="continue",
        ),
        FlowStep(
            step_name="update_knowledge",
            agent_name="knowledge_update_agent",
            action="update",
            description="更新知识库",
            required=False,
            on_failure="continue",
        ),
    ],
))


# ── 5. 知识入库流程 ──
_register(TaskFlow(
    flow_name="knowledge_ingest_flow",
    description="知识入库流程：文档解析 → 向量化 → 存储",
    steps=[
        FlowStep(
            step_name="parse_document",
            agent_name="document_parser",
            action="parse",
            description="解析上传的文档",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="embed_elements",
            agent_name="embedding_agent",
            action="embed",
            description="向量化元素",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="store_knowledge",
            agent_name="storage_agent",
            action="store",
            description="存储到三库",
            required=True,
            on_failure="abort",
        ),
    ],
))


# ── 6. 图谱构建流程 ──
_register(TaskFlow(
    flow_name="graph_build_flow",
    description="图谱构建流程：关系推理 → 图谱构建",
    steps=[
        FlowStep(
            step_name="infer_relations",
            agent_name="relation_agent",
            action="infer",
            description="推理页面关系",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="build_graph",
            agent_name="graph_agent",
            action="build",
            description="构建知识图谱",
            required=True,
            on_failure="abort",
        ),
    ],
))


# ── 7. 用例流水线 ──
_register(TaskFlow(
    flow_name="testcase_pipeline_flow",
    description="TestCase流水线：需求分析 → 测试点 → 用例生成 → 用例审查 → 知识同步",
    steps=[
        FlowStep(
            step_name="analyze_requirement",
            agent_name="requirement_analysis_agent",
            action="analyze",
            description="需求分析",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="analyze_test_points",
            agent_name="test_point_analysis_agent",
            action="analyze",
            description="测试点分析",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="generate_cases",
            agent_name="testcase_generator_agent",
            action="generate",
            description="生成测试用例",
            required=True,
            on_failure="abort",
        ),
        FlowStep(
            step_name="review_cases",
            agent_name="testcase_review_agent",
            action="review",
            description="审查用例",
            required=False,
            on_failure="continue",
        ),
        FlowStep(
            step_name="sync_knowledge",
            agent_name="knowledge_sync_agent",
            action="sync",
            description="知识同步",
            required=False,
            on_failure="continue",
        ),
    ],
))


# ══════════════════════════════════════════════════════════════
# 查询接口
# ══════════════════════════════════════════════════════════════

def list_flows() -> List[Dict]:
    """列出所有可用流程"""
    results = []
    for name, flow in _FLOWS.items():
        results.append({
            "flow_name": name,
            "description": flow.description,
            "step_count": len(flow.steps),
            "steps": [
                {
                    "step_name": s.step_name,
                    "agent_name": s.agent_name,
                    "action": s.action,
                    "description": s.description,
                    "required": s.required,
                    "condition": s.condition,
                }
                for s in flow.steps
            ],
        })
    return results


def get_flow(flow_name: str) -> Optional[TaskFlow]:
    """获取流程定义"""
    return _FLOWS.get(flow_name)


def is_flow_exists(flow_name: str) -> bool:
    """检查流程是否存在"""
    return flow_name in _FLOWS


def get_flow_names() -> List[str]:
    """获取所有流程名称"""
    return list(_FLOWS.keys())
