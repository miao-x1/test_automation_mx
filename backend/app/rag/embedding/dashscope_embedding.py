"""DashScope (通义千问) Embedding — 统一实现

项目中唯一的 Embedding 实现，所有需要 Embedding 的地方都应通过 EmbeddingFactory 获取：
    from app.rag.embedding.factory import get_embedding_factory
    embedding = get_embedding_factory().get_embedding()
    vector = await embedding.embed(text)

配置：
    API Key:  settings.QWEN_API_KEY（与通义千问 LLM 共用）
    API URL:  https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings（OpenAI 兼容）
    Model:    settings.EMBEDDING_MODEL（默认 text-embedding-v3）
    Dim:      settings.EMBEDDING_DIM（默认 1024）

禁止：
    ❌ 在 Agent / Service / Router 中重复实现 DashScope Embedding
    ❌ 使用不同的 API Key 或 API 端点
    ❌ 使用不一致的向量维度
"""
import logging
from typing import List

import httpx

from app.core.config import settings
from app.rag.embedding.base import BaseEmbedding

logger = logging.getLogger(__name__)


class DashScopeEmbedding(BaseEmbedding):
    """DashScope text-embedding-v3（统一实现）

    使用 OpenAI 兼容 API，与通义千问 LLM 共用 API Key。
    """

    def __init__(self) -> None:
        super().__init__(
            model_name=settings.EMBEDDING_MODEL,
            dim=settings.EMBEDDING_DIM,
        )
        self.api_key = settings.QWEN_API_KEY or ""
        self.api_url = "https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings"

    def can_handle(self) -> bool:
        """检查 API Key 是否可用"""
        return bool(self.api_key)

    async def embed(self, text: str) -> List[float]:
        """单条文本 Embedding"""
        if not self.api_key:
            logger.warning("[DashScopeEmbedding] No API key, returning zero vector")
            return [0.0] * self.dim
        try:
            results = await self._call_api([text])
            return results[0] if results else [0.0] * self.dim
        except Exception as e:
            logger.error(f"[DashScopeEmbedding] embed failed: {e}")
            return [0.0] * self.dim

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """批量文本 Embedding（DashScope 批量上限 25 条）"""
        if not self.api_key:
            return [[0.0] * self.dim for _ in texts]

        results: List[List[float]] = []
        batch_size = 25
        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            try:
                batch_results = await self._call_api(batch)
                results.extend(batch_results)
            except Exception as e:
                logger.error(f"[DashScopeEmbedding] batch failed at [{i}:{i + len(batch)}]: {e}")
                results.extend([[0.0] * self.dim for _ in batch])
        return results

    def embed_sync(self, text: str) -> List[float]:
        """同步 Embedding（用于非异步上下文，如 ContextRouter.retrieve_sync）

        内部使用 httpx 同步客户端。
        """
        if not self.api_key:
            logger.warning("[DashScopeEmbedding] No API key, returning zero vector")
            return [0.0] * self.dim
        try:
            resp = httpx.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "input": text,
                    "dimensions": self.dim,
                    "encoding_format": "float",
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            embedding = data.get("data", [{}])[0].get("embedding", [])
            if embedding:
                return embedding
            return [0.0] * self.dim
        except Exception as e:
            logger.error(f"[DashScopeEmbedding] embed_sync failed: {e}")
            return [0.0] * self.dim

    def embed_batch_sync(self, texts: List[str]) -> List[List[float]]:
        """同步批量 Embedding"""
        if not self.api_key:
            return [[0.0] * self.dim for _ in texts]

        results: List[List[float]] = []
        batch_size = 25
        for i in range(0, len(texts), batch_size):
            batch = texts[i: i + batch_size]
            try:
                resp = httpx.post(
                    self.api_url,
                    json={
                        "model": self.model_name,
                        "input": batch,
                        "dimensions": self.dim,
                        "encoding_format": "float",
                    },
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
                embeddings = data.get("data", [])
                for emb in embeddings:
                    results.append(emb.get("embedding", [0.0] * self.dim))
            except Exception as e:
                logger.error(f"[DashScopeEmbedding] batch_sync failed at [{i}:{i + len(batch)}]: {e}")
                results.extend([[0.0] * self.dim for _ in batch])
        return results

    async def _call_api(self, texts: List[str]) -> List[List[float]]:
        """调用 DashScope OpenAI 兼容 API"""
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                self.api_url,
                json={
                    "model": self.model_name,
                    "input": texts,
                    "dimensions": self.dim,
                    "encoding_format": "float",
                },
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            embeddings = data.get("data", [])
            return [emb.get("embedding", [0.0] * self.dim) for emb in embeddings]
