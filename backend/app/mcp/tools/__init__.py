"""
MCP Tools - 工具模块

4个核心工具，供外部AI客户端调用：

1. analyze_page       — 页面分析（URL抓取 + 视觉元素识别）
2. generate_testcase  — 生成测试用例（需求→测试点→用例）
3. generate_script    — 生成测试脚本（需求→用例→脚本）
4. execute_test       — 执行测试（脚本执行 + 结果报告）

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

# 工具注册表
ALL_TOOLS = [
    (ANALYZE_PAGE_NAME, ANALYZE_PAGE_DESC, ANALYZE_PAGE_SCHEMA, analyze_page_execute),
    (GENERATE_TESTCASE_NAME, GENERATE_TESTCASE_DESC, GENERATE_TESTCASE_SCHEMA, generate_testcase_execute),
    (GENERATE_SCRIPT_NAME, GENERATE_SCRIPT_DESC, GENERATE_SCRIPT_SCHEMA, generate_script_execute),
    (EXECUTE_TEST_NAME, EXECUTE_TEST_DESC, EXECUTE_TEST_SCHEMA, execute_test_execute),
]

__all__ = [
    "ALL_TOOLS",
    "analyze_page_execute",
    "generate_testcase_execute",
    "generate_script_execute",
    "execute_test_execute",
]
