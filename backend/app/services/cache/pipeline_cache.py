"""
Pipeline缓存服务

缓存策略：
1. PDF/文档解析结果：SHA256(file_bytes) → 解析文本
2. RAG检索结果：SHA256(query) → RAG context
3. L1结果：task_id → features/entities/api_candidates/test_strategy

缓存存储：文件系统（cache_dir），可选Redis
"""
import hashlib
import json
import os
import time
from typing import Any, Dict, Optional
from app.core.config import settings
from app.core.logger import log


class PipelineCache:
    """三层流水线缓存"""

    def __init__(self, cache_dir: Optional[str] = None, ttl: int = 3600):
        """
        Args:
            cache_dir: 缓存目录，默认为 settings.UPLOAD_DIR/cache/pipeline
            ttl: 缓存过期时间（秒），默认1小时
        """
        self.cache_dir = cache_dir or os.path.join(settings.UPLOAD_DIR, "cache", "pipeline")
        self.ttl = ttl
        os.makedirs(self.cache_dir, exist_ok=True)

    @staticmethod
    def file_hash(file_bytes: bytes) -> str:
        """计算文件SHA256哈希"""
        return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def text_hash(text: str) -> str:
        """计算文本SHA256哈希"""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    def _cache_path(self, key: str) -> str:
        """获取缓存文件路径"""
        return os.path.join(self.cache_dir, f"{key}.json")

    def get(self, key: str) -> Optional[Any]:
        """读取缓存"""
        path = self._cache_path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                entry = json.load(f)
            # 检查过期
            if time.time() - entry.get("ts", 0) > self.ttl:
                os.remove(path)
                return None
            return entry.get("data")
        except Exception:
            return None

    def set(self, key: str, data: Any) -> None:
        """写入缓存"""
        path = self._cache_path(key)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"ts": time.time(), "data": data}, f, ensure_ascii=False)
        except Exception as e:
            log.warning(f"PipelineCache | 写入缓存失败: {e}")

    def get_parsed_content(self, file_path: str) -> Optional[str]:
        """获取已缓存的文件解析结果"""
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            key = f"parse_{self.file_hash(file_bytes)}"
            return self.get(key)
        except Exception:
            return None

    def set_parsed_content(self, file_path: str, content: str) -> None:
        """缓存文件解析结果"""
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()
            key = f"parse_{self.file_hash(file_bytes)}"
            self.set(key, content)
        except Exception:
            pass

    def get_rag_context(self, query: str, project_id: str = "") -> Optional[Dict]:
        """获取已缓存的RAG检索结果"""
        key = f"rag_{self.text_hash(query + project_id)}"
        return self.get(key)

    def set_rag_context(self, query: str, project_id: str, context: Dict) -> None:
        """缓存RAG检索结果"""
        key = f"rag_{self.text_hash(query + project_id)}"
        self.set(key, context)

    def get_l1_result(self, task_id: int) -> Optional[Dict]:
        """获取已缓存的L1结果"""
        return self.get(f"l1_{task_id}")

    def set_l1_result(self, task_id: int, result: Dict) -> None:
        """缓存L1结果"""
        self.set(f"l1_{task_id}", result)


# 全局单例
_cache_instance: Optional[PipelineCache] = None


def get_pipeline_cache() -> PipelineCache:
    """获取缓存单例"""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = PipelineCache()
    return _cache_instance
