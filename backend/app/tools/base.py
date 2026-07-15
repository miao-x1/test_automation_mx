"""
工具基类 - 所有工具的统一接口

设计原则：
  1. 所有工具继承 BaseTool
  2. 统一 execute() 方法签名
  3. 统一 ToolResult 返回格式
  4. 支持异步执行
  5. 支持上下文传递（ToolContext）
"""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ToolResult:
    """工具执行结果"""
    success: bool = True                    # 是否成功
    data: Any = None                        # 返回数据
    error: str = ""                         # 错误信息
    duration: float = 0.0                   # 耗时（秒）
    metadata: Dict[str, Any] = field(default_factory=dict)  # 元数据

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration": self.duration,
            "metadata": self.metadata,
        }


@dataclass
class ToolContext:
    """工具执行上下文

    携带会话和任务信息，用于工具内部状态管理。
    """
    session_key: str = "default"
    task_id: str = ""
    user_id: int = 0
    agent_name: str = ""
    options: Dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    """工具基类

    所有工具必须继承此类并实现 execute() 方法。
    """

    def __init__(self, name: str = "", description: str = ""):
        self.name = name or self.__class__.__name__
        self.description = description
        self._initialized = False

    @abstractmethod
    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """执行工具

        Args:
            ctx: 工具执行上下文
            **kwargs: 工具参数

        Returns:
            ToolResult 执行结果
        """
        pass

    def initialize(self) -> None:
        """初始化工具（懒加载资源）"""
        if not self._initialized:
            self._do_initialize()
            self._initialized = True
            logger.info(f"[Tool:{self.name}] 初始化完成")

    def _do_initialize(self) -> None:
        """子类重写：实际初始化逻辑"""
        pass

    def can_handle(self) -> bool:
        """检查工具是否可用"""
        return True

    def get_info(self) -> Dict[str, Any]:
        """获取工具信息"""
        return {
            "name": self.name,
            "description": self.description,
            "initialized": self._initialized,
            "available": self.can_handle(),
        }

    async def safe_execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        """安全执行（捕获异常）"""
        start = time.time()
        try:
            self.initialize()
            result = await self.execute(ctx, **kwargs)
            result.duration = time.time() - start
            return result
        except Exception as e:
            logger.error(f"[Tool:{self.name}] 执行失败: {e}", exc_info=True)
            return ToolResult(
                success=False,
                error=str(e),
                duration=time.time() - start,
            )
