"""Embedding 基类"""
from abc import ABC, abstractmethod
from typing import List


class BaseEmbedding(ABC):
    """向量嵌入基类

    所有 Embedding 实现必须继承此类。
    项目中唯一的实例化管理通过 EmbeddingFactory。
    """

    def __init__(self, model_name: str = "", dim: int = 1024):
        self.model_name = model_name
        self.dim = dim

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """生成单个文本的向量（异步）"""
        pass

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量生成向量（异步）"""
        pass

    @abstractmethod
    def can_handle(self) -> bool:
        """检查是否可用"""
        pass

    def embed_sync(self, text: str) -> List[float]:
        """生成单个文本的向量（同步）

        默认实现返回零向量，子类可覆盖。
        用于非异步上下文（如 ContextRouter.retrieve_sync）。
        """
        return [0.0] * self.dim

    def embed_batch_sync(self, texts: List[str]) -> List[List[float]]:
        """批量生成向量（同步）

        默认实现返回零向量列表，子类可覆盖。
        """
        return [[0.0] * self.dim for _ in texts]

    def get_dim(self) -> int:
        """获取向量维度"""
        return self.dim
