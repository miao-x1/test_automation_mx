"""
检索器基类

定义统一的检索接口，所有检索器必须继承BaseRetriever。
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class RetrievalResult:
    """检索结果"""
    source: str = ""                # 数据来源: mysql/milvus/neo4j
    success: bool = True
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    duration: float = 0.0
    count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "duration": self.duration,
            "count": self.count,
        }


class BaseRetriever(ABC):
    """检索器基类

    所有数据库检索器必须继承此类，实现search方法。
    """

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"retrieval.{name}")

    @abstractmethod
    def search(self, query: Dict[str, Any]) -> RetrievalResult:
        """
        执行检索

        Args:
            query: 检索参数（由RetrievalPlan中的各类查询计划提供）

        Returns:
            RetrievalResult: 检索结果
        """
        pass

    def _safe_execute(self, query: Dict[str, Any]) -> RetrievalResult:
        """安全执行检索（带异常捕获）

        子类可以调用此方法进行安全的检索操作。
        """
        import time
        start = time.time()
        try:
            result = self.search(query)
            result.duration = time.time() - start
            return result
        except Exception as e:
            self.logger.error(f"[{self.name}] 检索失败: {e}", exc_info=True)
            return RetrievalResult(
                source=self.name,
                success=False,
                error=str(e),
                duration=time.time() - start,
            )
