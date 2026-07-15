"""Mock Embedding - 测试用"""
import hashlib
import math
from typing import List
from app.rag.embedding.base import BaseEmbedding


class MockEmbedding(BaseEmbedding):
    """确定性 Mock 向量（基于文本哈希），测试用"""
    
    def __init__(self, dim: int = 1024):
        super().__init__(model_name="mock-embedding", dim=dim)
    
    def can_handle(self) -> bool:
        return True
    
    async def embed(self, text: str) -> List[float]:
        return self._hash_to_vector(text)
    
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._hash_to_vector(t) for t in texts]
    
    def _hash_to_vector(self, text: str) -> List[float]:
        """将文本转为确定性向量"""
        vector = [0.0] * self.dim
        # 用文本哈希初始化随机种子
        h = hashlib.md5(text.encode('utf-8')).hexdigest()
        seed = int(h[:8], 16)
        # 基于文本内容填充向量
        for i in range(min(self.dim, len(text) * 4)):
            char = text[(i // 4) % len(text)] if text else ' '
            vector[i] = (ord(char) % 100) / 100.0
        # 添加哈希成分使相同文本产生相同向量
        for i in range(self.dim):
            h_val = int(h[(i % 32)], 16)
            vector[i] += h_val / 16.0
            vector[i] = vector[i] % 1.0
        # L2 归一化
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]
        return vector
