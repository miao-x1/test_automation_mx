"""
统一工具层 - app/tools/

MCP 工具统一封装为 Tool，由 Agent 调用，不直接调用 Python 函数。
支持 Browser、RAG、Database、Playwright、Swagger、Chat2DB 等工具。

设计原则：
  1. 所有工具继承 BaseTool
  2. 统一注册到 ToolRegistry
  3. Agent 通过 AgentFactory 配置 tools=["browser", "rag", ...]
  4. 工具执行结果统一为 ToolResult

使用示例：
    from app.tools import get_tool_registry

    registry = get_tool_registry()
    tool = registry.get("rag_search")
    result = await tool.execute(query="用户登录", top_k=5)
"""
from app.tools.base import BaseTool, ToolResult, ToolContext
from app.tools.registry import ToolRegistry, get_tool_registry
from app.tools.browser_tool import BrowserTool
from app.tools.rag_tool import RAGSearchTool, RAGIndexTool
from app.tools.database_tool import DatabaseQueryTool, DatabaseSaveTool
from app.tools.playwright_tool import PlaywrightTool
from app.tools.swagger_tool import SwaggerParseTool

__all__ = [
    "BaseTool",
    "ToolResult",
    "ToolContext",
    "ToolRegistry",
    "get_tool_registry",
    "BrowserTool",
    "RAGSearchTool",
    "RAGIndexTool",
    "DatabaseQueryTool",
    "DatabaseSaveTool",
    "PlaywrightTool",
    "SwaggerParseTool",
]
