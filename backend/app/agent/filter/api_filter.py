"""
API 数据过滤器

针对 API 测试流程中各 Agent 的输出进行过滤:

    ApiParserFilter   — 过滤 SwaggerParserAgent / APIExtractionAgent 输出
    ApiRagFilter       — 过滤 RAGAgent 在 API 流程中的输出
    ApiCaseFilter     — 过滤 CaseAgent API 编译输出
    ApiScriptFilter   — 过滤 ScriptGenerationAgent API 脚本输出

过滤策略:
    保留: method, url, headers, body, response 等核心 API 字段
    删除: 无关描述, 历史日志, 大文本 (raw_requirement, schema 等)
"""
import logging
from typing import Any, Dict

from app.agent.filter.base_filter import BaseFilter

logger = logging.getLogger(__name__)


class ApiParserFilter(BaseFilter):
    """API 解析过滤器 — 过滤 SwaggerParserAgent / APIExtractionAgent 输出

    保留:
        - intent, summary (需求概要)
        - apis[] (API 定义, 但精简字段)
        - target_url

    删除:
        - raw_requirement (原始大文本, 可达 4000 字符)
        - metadata.apis (冗余的完整 API 定义)
        - source_files, parsed_at, parse_version, user_id
        - pages[].description (页面描述)
        - constraints[].description (约束描述)
        - test_points[].description, test_points[].test_data
    """

    name = "ApiParserFilter"
    description = "过滤 API 解析输出: 保留 API 定义, 删除原始文本和无关描述"

    keep_fields = {
        "status",
        "intent",
        "summary",
        "target_url",
        "apis",
        "total",
        "metadata",
    }

    deep_drop_fields = {
        "raw_requirement",
        "metadata.apis",
        "metadata.api_title",
        "metadata.api_version",
        "pages[].description",
        "pages[].elements",
        "constraints[].description",
        "test_points[].description",
        "test_points[].test_data",
        "apis[].request_schema",
        "apis[].response_schema",
        "apis[].depends",
    }

    drop_fields = {
        "source_files",
        "parsed_at",
        "parse_version",
        "user_id",
        "session_key",
        "source_types",
        "fallback",
        "session_id",
    }


class ApiRagFilter(BaseFilter):
    """API RAG 过滤器 — 过滤 RAGAgent 在 API 流程中的输出

    保留:
        - cases[] (历史 API 用例, 精简为 method/url/assertions)
        - scripts[] 的 script_name (保留名称供参考, 删除内容)

    删除:
        - scripts[].script_content (历史脚本大文本)
        - cases[].description (历史用例描述)
        - cases[].steps (历史用例步骤)
        - elements (UI 元素, API 流程不需要)
        - 各种 count 字段
    """

    name = "ApiRagFilter"
    description = "过滤 API RAG 输出: 保留用例名称, 删除历史脚本内容和描述"

    keep_fields = {
        "status",
        "cases",
        "scripts",
    }

    deep_drop_fields = {
        "scripts[].script_content",
        "scripts[].description",
        "scripts[].source",
        "cases[].description",
        "cases[].steps",
        "cases[].source",
    }

    drop_fields = {
        "elements",
        "element_count",
        "case_count",
        "script_count",
        "query_steps",
    }


class ApiCaseFilter(BaseFilter):
    """API 用例过滤器 — 过滤 CaseAgent API 编译输出

    保留:
        - cases[] 的核心字段: case_id, title, method, url, headers, body, assertions

    删除:
        - pre_steps (前置步骤, 结构较大)
        - variables (变量定义)
        - tags, feature_ref, type (元数据)
        - total, case_types (统计字段)
        - coverage_notes, source, degradation_info
    """

    name = "ApiCaseFilter"
    description = "过滤 API 用例输出: 保留核心 API 字段, 删除前置步骤和变量定义"

    keep_fields = {
        "status",
        "cases",
    }

    deep_drop_fields = {
        "cases[].pre_steps",
        "cases[].variables",
        "cases[].tags",
        "cases[].feature_ref",
        "cases[].type",
        "cases[].priority",
    }

    drop_fields = {
        "total",
        "case_types",
        "case_count",
        "source",
        "coverage_notes",
        "degradation_info",
    }


class ApiScriptFilter(BaseFilter):
    """API 脚本过滤器 — 过滤 ScriptGenerationAgent API 脚本输出

    保留:
        - script_content (核心输出, 但截断到合理长度用于传递)
        - script_format
        - script_quality

    删除:
        - reuse_info (可能包含历史脚本内容)
        - strategy_used (策略详情)
        - retry_strategy (重试配置)
        - degradation_chain (降级链)
        - generation_time_ms (性能指标)
        - degradation_info.message (描述文本)
    """

    name = "ApiScriptFilter"
    description = "过滤 API 脚本输出: 保留脚本内容和质量, 删除策略和重试配置"

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

    # script_content 不截断 (最终产物, 需要完整内容)
