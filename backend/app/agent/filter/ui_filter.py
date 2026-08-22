"""
UI 数据过滤器

针对 UI 测试流程中各 Agent 的输出进行过滤:

    RequirementFilter — 过滤 RequirementAgent 输出
    UiRagFilter        — 过滤 RAGAgent 在 UI 流程中的输出
    UiCaseFilter      — 过滤 CaseAgent UI 用例输出
    UiScriptFilter    — 过滤 ScriptGenerationAgent UI 脚本输出

过滤策略:
    保留: 页面元素 (locator, element_name, element_type)
    删除: 历史脚本内容, 用例描述, 风险点, 冗余包装
"""
import logging
from typing import Any, Dict

from app.agent.filter.base_filter import BaseFilter

logger = logging.getLogger(__name__)


class RequirementFilter(BaseFilter):
    """需求解析过滤器 — 过滤 RequirementAgent 输出

    保留:
        - intent, summary, target_url, steps (核心需求信息)
        - test_points (测试点, 精简描述)
        - business_flow.stages (业务流程阶段)

    删除:
        - risk_points (风险点, 下游 Agent 不消费)
        - requirement_items (冗余包装)
        - business_flow.description (大文本描述)
        - test_points[].description (测试点描述)
    """

    name = "RequirementFilter"
    description = "过滤需求解析输出: 保留意图和步骤, 删除风险点和冗余包装"

    keep_fields = {
        "status",
        "step",
        "task_id",
        "intent",
        "summary",
        "target_url",
        "steps",
        "business_flow",
        "test_points",
    }

    deep_drop_fields = {
        "business_flow.description",
        "test_points[].description",
        "test_points[].priority",
    }

    drop_fields = {
        "risk_points",
        "requirement_items",
    }


class UiRagFilter(BaseFilter):
    """UI RAG 过滤器 — 过滤 RAGAgent 在 UI 流程中的输出

    保留:
        - elements[] 的核心字段: element_name, element_type, locator, page_name, score
        - cases[] 的 case_name (保留名称供参考)

    删除:
        - scripts[] (整体删除, 历史脚本内容太大)
        - cases[].steps (历史用例步骤)
        - cases[].description (历史用例描述)
        - elements[].description (元素描述)
        - elements[].source (数据来源)
        - 各种 count 字段
    """

    name = "UiRagFilter"
    description = "过滤 UI RAG 输出: 保留页面元素, 删除历史脚本和描述"

    keep_fields = {
        "status",
        "elements",
        "cases",
    }

    deep_drop_fields = {
        "scripts[].script_content",
        "scripts[].description",
        "scripts[].source",
        "scripts[].task_id",
        "cases[].description",
        "cases[].steps",
        "cases[].source",
        "cases[].task_id",
        "elements[].description",
        "elements[].source",
        "elements[].task_id",
    }

    drop_fields = {
        "scripts",
        "element_count",
        "case_count",
        "script_count",
        "query_steps",
    }


class UiCaseFilter(BaseFilter):
    """UI 用例过滤器 — 过滤 CaseAgent UI 用例输出

    保留:
        - cases[] 的核心字段: case_name, steps, assertions, expected_result

    删除:
        - preconditions (前置条件, ScriptAgent 不使用)
        - description (用例描述)
        - coverage_notes, source, degradation_info
    """

    name = "UiCaseFilter"
    description = "过滤 UI 用例输出: 保留步骤和断言, 删除前置条件和描述"

    keep_fields = {
        "status",
        "cases",
        "case_count",
    }

    deep_drop_fields = {
        "cases[].preconditions",
        "cases[].description",
        "cases[].priority",
        "cases[].steps[].description",
    }

    drop_fields = {
        "source",
        "coverage_notes",
        "degradation_info",
    }


class UiScriptFilter(BaseFilter):
    """UI 脚本过滤器 — 过滤 ScriptGenerationAgent UI 脚本输出

    保留:
        - script_content (核心输出)
        - script_format, script_quality
        - degradation_info.level, degradation_info.source

    删除:
        - reuse_info (可能包含历史脚本)
        - strategy_used (策略详情)
        - retry_strategy (重试配置)
        - degradation_chain (降级链)
        - generation_time_ms (性能指标)
        - degradation_info.message (描述文本)
    """

    name = "UiScriptFilter"
    description = "过滤 UI 脚本输出: 保留脚本内容, 删除策略和重试配置"

    keep_fields = {
        "status",
        "script_content",
        "script_format",
        "script_quality",
        "degradation_info",
    }

    deep_drop_fields = {
        "degradation_info.message",
        "degradation_info.action_required",
        "strategy_used.reason",
        "strategy_used.locator_priority",
        "reuse_info.script_content",
    }

    drop_fields = {
        "reuse_info",
        "strategy_used",
        "retry_strategy",
        "degradation_chain",
        "generation_time_ms",
    }
