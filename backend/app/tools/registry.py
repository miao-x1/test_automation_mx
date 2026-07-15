"""
工具注册表 - 统一管理所有工具

所有工具统一注册到 ToolRegistry。
Agent 通过 AgentFactory 配置 tools=["rag_search", "browser", ...]。
AgentFactory 创建 Agent 时自动注入对应工具实例。
"""
import logging
from typing import Any, Dict, List, Optional

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ToolRegistry:
    """工具注册表

    统一管理所有工具的注册、获取、列表。
    支持懒加载（首次使用时才初始化工具实例）。
    """

    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}
        self._tool_classes: Dict[str, type] = {}  # 延迟实例化

    def register(self, name: str, tool: BaseTool) -> None:
        """注册工具实例"""
        self._tools[name] = tool
        logger.info(f"[ToolRegistry] 注册工具: {name}")

    def register_class(self, name: str, tool_class: type) -> None:
        """注册工具类（延迟实例化）"""
        self._tool_classes[name] = tool_class
        logger.info(f"[ToolRegistry] 注册工具类: {name}")

    def get(self, name: str) -> Optional[BaseTool]:
        """获取工具实例

        如果工具已实例化则直接返回，否则尝试从注册类实例化。
        """
        if name in self._tools:
            return self._tools[name]

        if name in self._tool_classes:
            tool_class = self._tool_classes[name]
            try:
                tool = tool_class()
                self._tools[name] = tool
                logger.info(f"[ToolRegistry] 懒加载工具: {name}")
                return tool
            except Exception as e:
                logger.error(f"[ToolRegistry] 实例化工具失败: {name}: {e}")
                return None

        logger.warning(f"[ToolRegistry] 工具未注册: {name}")
        return None

    def list_tools(self) -> List[str]:
        """列出所有已注册工具名"""
        return list(set(list(self._tools.keys()) + list(self._tool_classes.keys())))

    def get_info(self) -> List[Dict[str, Any]]:
        """获取所有工具信息"""
        infos = []
        for name in self.list_tools():
            tool = self.get(name)
            if tool:
                infos.append(tool.get_info())
        return infos

    def unregister(self, name: str) -> bool:
        """取消注册"""
        removed = False
        if name in self._tools:
            del self._tools[name]
            removed = True
        if name in self._tool_classes:
            del self._tool_classes[name]
            removed = True
        if removed:
            logger.info(f"[ToolRegistry] 取消注册: {name}")
        return removed


# ===== 默认工具注册 =====
def _register_default_tools(registry: ToolRegistry) -> None:
    """注册默认工具集"""
    from app.tools.browser_tool import BrowserTool
    from app.tools.rag_tool import RAGSearchTool, RAGIndexTool
    from app.tools.database_tool import DatabaseQueryTool, DatabaseSaveTool
    from app.tools.playwright_tool import PlaywrightTool
    from app.tools.swagger_tool import SwaggerParseTool

    # 注册工具类（延迟实例化）
    registry.register_class("browser", BrowserTool)
    registry.register_class("rag_search", RAGSearchTool)
    registry.register_class("rag_index", RAGIndexTool)
    registry.register_class("db_query", DatabaseQueryTool)
    registry.register_class("db_save", DatabaseSaveTool)
    registry.register_class("playwright", PlaywrightTool)
    registry.register_class("swagger_parse", SwaggerParseTool)


# ===== 单例 =====
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """获取工具注册表单例"""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
        _register_default_tools(_tool_registry)
        logger.info(f"[ToolRegistry] 初始化完成，已注册 {len(_tool_registry.list_tools())} 个工具")
    return _tool_registry
