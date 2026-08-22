"""
MCP Tools - 工具模块

7个工具，供外部AI客户端调用：

核心测试工具 (4个):
1. analyze_page       — 页面分析（URL抓取 + 视觉元素识别）
2. generate_testcase  — 生成测试用例（需求→测试点→用例）
3. generate_script    — 生成测试脚本（需求→用例→脚本）
4. execute_test       — 执行测试（脚本执行 + 结果报告）

浏览器性能监控工具 (3个):
5. get_page_metrics      — 页面性能指标采集 (加载时间/DOM/Web Vitals)
6. get_network_metrics   — 网络性能指标采集 (请求/资源大小/分组统计)
7. get_performance_report — 综合性能报告 + AI分析

每个工具模块导出:
  - TOOL_NAME: str          工具名称
  - TOOL_DESCRIPTION: str   工具描述
  - TOOL_SCHEMA: dict       JSON Schema 输入定义
  - async def execute(**kwargs) -> dict   工具执行函数
"""
from app.mcp.tools.analyze_page import (
    TOOL_NAME as ANALYZE_PAGE_NAME,
    TOOL_SCHEMA as ANALYZE_PAGE_SCHEMA,
    TOOL_DESCRIPTION as ANALYZE_PAGE_DESC,
    execute as analyze_page_execute,
)
from app.mcp.tools.generate_testcase import (
    TOOL_NAME as GENERATE_TESTCASE_NAME,
    TOOL_SCHEMA as GENERATE_TESTCASE_SCHEMA,
    TOOL_DESCRIPTION as GENERATE_TESTCASE_DESC,
    execute as generate_testcase_execute,
)
from app.mcp.tools.generate_script import (
    TOOL_NAME as GENERATE_SCRIPT_NAME,
    TOOL_SCHEMA as GENERATE_SCRIPT_SCHEMA,
    TOOL_DESCRIPTION as GENERATE_SCRIPT_DESC,
    execute as generate_script_execute,
)
from app.mcp.tools.execute_test import (
    TOOL_NAME as EXECUTE_TEST_NAME,
    TOOL_SCHEMA as EXECUTE_TEST_SCHEMA,
    TOOL_DESCRIPTION as EXECUTE_TEST_DESC,
    execute as execute_test_execute,
)
from app.mcp.tools.get_page_metrics import (
    TOOL_NAME as GET_PAGE_METRICS_NAME,
    TOOL_SCHEMA as GET_PAGE_METRICS_SCHEMA,
    TOOL_DESCRIPTION as GET_PAGE_METRICS_DESC,
    execute as get_page_metrics_execute,
)
from app.mcp.tools.get_network_metrics import (
    TOOL_NAME as GET_NETWORK_METRICS_NAME,
    TOOL_SCHEMA as GET_NETWORK_METRICS_SCHEMA,
    TOOL_DESCRIPTION as GET_NETWORK_METRICS_DESC,
    execute as get_network_metrics_execute,
)
from app.mcp.tools.get_performance_report import (
    TOOL_NAME as GET_PERFORMANCE_REPORT_NAME,
    TOOL_SCHEMA as GET_PERFORMANCE_REPORT_SCHEMA,
    TOOL_DESCRIPTION as GET_PERFORMANCE_REPORT_DESC,
    execute as get_performance_report_execute,
)

# 工具注册表
ALL_TOOLS = [
    # 核心测试工具
    (ANALYZE_PAGE_NAME, ANALYZE_PAGE_DESC, ANALYZE_PAGE_SCHEMA, analyze_page_execute),
    (GENERATE_TESTCASE_NAME, GENERATE_TESTCASE_DESC, GENERATE_TESTCASE_SCHEMA, generate_testcase_execute),
    (GENERATE_SCRIPT_NAME, GENERATE_SCRIPT_DESC, GENERATE_SCRIPT_SCHEMA, generate_script_execute),
    (EXECUTE_TEST_NAME, EXECUTE_TEST_DESC, EXECUTE_TEST_SCHEMA, execute_test_execute),
    # 浏览器性能监控工具
    (GET_PAGE_METRICS_NAME, GET_PAGE_METRICS_DESC, GET_PAGE_METRICS_SCHEMA, get_page_metrics_execute),
    (GET_NETWORK_METRICS_NAME, GET_NETWORK_METRICS_DESC, GET_NETWORK_METRICS_SCHEMA, get_network_metrics_execute),
    (GET_PERFORMANCE_REPORT_NAME, GET_PERFORMANCE_REPORT_DESC, GET_PERFORMANCE_REPORT_SCHEMA, get_performance_report_execute),
]

__all__ = [
    "ALL_TOOLS",
    "analyze_page_execute",
    "generate_testcase_execute",
    "generate_script_execute",
    "execute_test_execute",
    "get_page_metrics_execute",
    "get_network_metrics_execute",
    "get_performance_report_execute",
]
