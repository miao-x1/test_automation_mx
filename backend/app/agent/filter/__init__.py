"""
app.agent.filter — Agent 数据过滤层

架构:
    Agent Output → BaseFilter.apply() → 过滤后数据 → Next Agent

过滤器类型:
    API 流程:
        ApiParserFilter   — 过滤 API 解析输出 (保留 method/url/headers/body)
        ApiRagFilter       — 过滤 RAG 输出 (删除历史脚本内容)
        ApiCaseFilter     — 过滤 API 用例输出
        ApiScriptFilter   — 过滤 API 脚本输出

    UI 流程:
        RequirementFilter — 过滤需求解析输出
        UiRagFilter        — 过滤 RAG 输出 (保留页面元素)
        UiCaseFilter      — 过滤 UI 用例输出
        UiScriptFilter    — 过滤 UI 脚本输出

    上下文:
        ContextPayloadFilter — 裁剪传递给 Agent 的 payload
        GraphStateFilter     — 清理中间结果中的大文本

快速使用:
    from app.agent.filter import RequirementFilter

    # 过滤 Agent 输出
    filter = RequirementFilter()
    result = filter.apply(agent_output)
    # result.data — 过滤后数据
    # result.metrics — 过滤效果统计 (压缩比/删除字段)

    # 在 GraphFlow 中使用 (通过 FilterNode)
    from app.workflow.nodes import FilterNode
    node = FilterNode(
        name="requirement_filter",
        filter_func=lambda state: RequirementFilter().apply_to_workflow(
            state.get_node_output("requirement")
        ),
    )
"""
from app.agent.filter.base_filter import (
    BaseFilter,
    FilterMetrics,
    FilterResult,
)
from app.agent.filter.api_filter import (
    ApiParserFilter,
    ApiRagFilter,
    ApiCaseFilter,
    ApiScriptFilter,
)
from app.agent.filter.ui_filter import (
    RequirementFilter,
    UiRagFilter,
    UiCaseFilter,
    UiScriptFilter,
)
from app.agent.filter.context_filter import (
    ContextPayloadFilter,
    GraphStateFilter,
)

__all__ = [
    # Base
    "BaseFilter",
    "FilterMetrics",
    "FilterResult",
    # API
    "ApiParserFilter",
    "ApiRagFilter",
    "ApiCaseFilter",
    "ApiScriptFilter",
    # UI
    "RequirementFilter",
    "UiRagFilter",
    "UiCaseFilter",
    "UiScriptFilter",
    # Context
    "ContextPayloadFilter",
    "GraphStateFilter",
]
