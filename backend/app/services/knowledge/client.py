"""
Knowledge Client - R2R 统一客户端

配置：
  R2R_BASE_URL  — R2R 服务地址（默认 http://localhost:7272）
  R2R_API_KEY   — API Key（可选）

R2R 职责（入库前预处理）：
  upload_file    — 上传文件，R2R 内部完成解析+切片
  upload         — 上传文本，R2R 内部完成解析+切片
  get_chunks     — 获取 R2R 解析+切片的结果
  delete_document — 从 R2R 删除文档

运行时检索（降级用，正常走 ContextRouter → Milvus）：
  search   — 语义搜索
  retrieve — 增强检索（RAG）
  health   — 健康检查

规则：
  失败降级 — 无 R2R 继续生成
  Redis 缓存 — 避免重复检索，TTL=300s
  top_k ≤ 3
  上下文 ≤ 1500 token
"""
import json
import hashlib
from typing import Any, Dict, Optional
from app.core.logger import log
from app.core.config import settings


# 限制常量
MAX_TOP_K = 3
MAX_CONTEXT_TOKENS = 1500
CACHE_TTL = 300  # Redis 缓存 TTL（秒）


class AnythingChatClient:
    """
    R2R 统一客户端

    R2R 负责文档入库前的所有预处理工作：
      1. 文档解析（PDF/Word/Markdown/JSON/图片等 → 纯文本）
      2. 文档切片（按策略分块）
    项目负责入库后的工作：
      3. Embedding 向量化
      4. MySQL / Milvus / Neo4j 三库写入
    """

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url or settings.R2R_BASE_URL
        self.api_key = api_key or settings.R2R_API_KEY
        self._memory_cache: Dict[str, Any] = {}

    @property
    def _headers(self) -> dict:
        """请求头（自动注入 API Key）"""
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ===== 缓存 =====

    def _cache_key(self, method: str, params: dict) -> str:
        """生成缓存 key"""
        raw = f"{method}:{json.dumps(params, sort_keys=True)}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _get_redis_client(self):
        """懒加载 Redis 客户端（优先 Redis，不可用时返回 None）"""
        try:
            import redis
            from app.core.config import settings
            if not settings.REDIS_ENABLED:
                return None
            r = redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3, socket_connect_timeout=3)
            r.ping()
            return r
        except Exception:
            return None

    def _get_cache(self, key: str) -> Optional[Any]:
        """从缓存获取（优先 Redis，降级内存）"""
        # 尝试 Redis
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                cached = redis_client.get(f"rag:{key}")
                if cached:
                    log.debug(f"R2RClient | Redis 缓存命中 | key={key[:12]}")
                    return json.loads(cached)
        except Exception:
            pass
        # 降级内存缓存
        return self._memory_cache.get(key)

    def _set_cache(self, key: str, value: Any, ttl: int = CACHE_TTL):
        """写入缓存（优先 Redis，降级内存）"""
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                redis_client.setex(f"rag:{key}", ttl, json.dumps(value, ensure_ascii=False))
                return
        except Exception:
            pass
        self._memory_cache[key] = value

    def _invalidate_cache(self, key_prefix: str = ""):
        """清除缓存"""
        # 内存缓存清除
        if key_prefix:
            self._memory_cache = {k: v for k, v in self._memory_cache.items() if not k.startswith(key_prefix)}
        else:
            self._memory_cache.clear()
        # Redis 缓存清除
        try:
            redis_client = self._get_redis_client()
            if redis_client:
                pattern = f"rag:{key_prefix}*" if key_prefix else "rag:*"
                for key in redis_client.scan_iter(pattern):
                    redis_client.delete(key)
        except Exception:
            pass

    # ===== 工具方法 =====

    def _truncate_context(self, text: str, max_tokens: int = MAX_CONTEXT_TOKENS) -> str:
        """截断上下文到指定 token 数（1 token ≈ 1.5 字符保守估算）"""
        max_chars = max_tokens * 2
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "..."

    def _request(self, method: str, endpoint: str, payload: Optional[dict] = None, timeout: int = 15) -> Optional[dict]:
        """发送 HTTP 请求"""
        import requests as http_requests
        url = f"{self.base_url}{endpoint}"
        try:
            if method.upper() == "POST":
                resp = http_requests.post(url, json=payload or {}, headers=self._headers, timeout=timeout)
            elif method.upper() == "GET":
                resp = http_requests.get(url, headers=self._headers, timeout=timeout)
            elif method.upper() == "DELETE":
                resp = http_requests.delete(url, headers=self._headers, timeout=timeout)
            else:
                return None

            if resp.status_code in (200, 204):
                if resp.status_code == 204:
                    return {"status": "deleted"}
                return resp.json()
            else:
                log.warning(f"R2RClient | HTTP {resp.status_code} | {url}")
                return None
        except Exception as e:
            log.warning(f"R2RClient | 请求失败: {e}")
            return None

    # ===== 核心接口 =====

    def upload(self, content: str, doc_type: str = "text", metadata: Optional[Dict] = None) -> Dict:
        """
        上传文档到知识库

        Args:
            content: 文档内容
            doc_type: 文档类型 (text/markdown/json/swagger)
            metadata: 元数据 (project_id, source_type, etc.)

        Returns:
            {"status", "doc_id"} 或 {"status": "failed", "error"}
        """
        try:
            result = self._request("POST", "/upload", {
                "content": content,
                "doc_type": doc_type,
                "metadata": metadata or {},
            }, timeout=30)

            if result:
                # 上传成功后清除检索缓存
                self._invalidate_cache()
                return result

            return {"status": "failed", "error": "upload request failed"}

        except Exception as e:
            log.warning(f"R2RClient | upload 失败: {e}")
            return {"status": "failed", "error": str(e)}

    def upload_file(self, file_path: str, metadata: Optional[Dict] = None) -> Dict:
        """
        上传文件到 R2R（R2R 内部完成解析+切片）

        R2R 在上传时自动执行：
          1. 文档解析（提取纯文本）
          2. 文档切片（按策略分块）
          3. 向量化+存储（R2R 内部，项目不使用这部分）

        项目后续通过 get_chunks() 获取切片结果，
        再自行完成 Embedding + 三库写入。

        Args:
            file_path: 文件路径
            metadata: 元数据

        Returns:
            {"status": "success", "document_id": "..."} 或 {"status": "failed", "error"}
        """
        try:
            import requests as http_requests
            url = f"{self.base_url}/upload/file"
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            with open(file_path, "rb") as f:
                files = {"file": f}
                data = {"metadata": json.dumps(metadata or {})}
                resp = http_requests.post(url, files=files, data=data, headers=headers, timeout=120)

            if resp.status_code == 200:
                self._invalidate_cache()
                result = resp.json()
                log.info(
                    f"R2RClient | upload_file 成功 | "
                    f"doc_id={result.get('document_id') or result.get('id', 'N/A')}"
                )
                return result

            return {"status": "failed", "error": f"HTTP {resp.status_code}"}

        except Exception as e:
            log.warning(f"R2RClient | upload_file 失败: {e}")
            return {"status": "failed", "error": str(e)}

    def upload_text(
        self,
        text: str,
        title: str = "",
        project_id: str = "",
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        上传文本到 R2R（R2R 内部完成解析+切片）

        兼容 RequirementService.upload_text() 调用。

        Args:
            text: 文本内容
            title: 标题
            project_id: 项目ID
            metadata: 额外元数据

        Returns:
            {"status": "success", "document_id": "..."} 或 {"status": "failed", "error"}
        """
        meta = {**(metadata or {}), "title": title, "project_id": project_id}
        return self.upload(content=text, doc_type="text", metadata=meta)

    def get_chunks(self, document_id: str, limit: int = 1000) -> Dict:
        """
        从 R2R 获取文档的切片结果

        R2R 在文档上传时完成解析+切片，此方法获取切片列表。
        每个 chunk 包含：id, text, metadata 等字段。

        尝试两种 API 路径：
          1. /v3/documents/{id}/chunks （R2R 标准 API）
          2. /documents/{id}/chunks    （简化路径）

        Args:
            document_id: R2R 文档ID（upload_file 返回的 document_id）
            limit: 最大返回数量

        Returns:
            {"results": [...], "total": N} 或 {"results": [], "fallback": True}
        """
        if not document_id:
            log.warning("R2RClient | get_chunks | document_id 为空")
            return {"results": [], "fallback": True}

        # 尝试 R2R 标准 API
        result = self._request(
            "GET",
            f"/v3/documents/{document_id}/chunks?limit={limit}",
            timeout=30,
        )
        if result and result.get("results"):
            chunks = result["results"]
            log.info(f"R2RClient | get_chunks 成功 | doc={document_id} | count={len(chunks)}")
            return result

        # 尝试简化路径
        result = self._request(
            "GET",
            f"/documents/{document_id}/chunks?limit={limit}",
            timeout=30,
        )
        if result and result.get("results"):
            chunks = result["results"]
            log.info(f"R2RClient | get_chunks 成功(简化路径) | doc={document_id} | count={len(chunks)}")
            return result

        log.warning(f"R2RClient | get_chunks 失败 | doc={document_id} | R2R 可能未暴露 chunks 端点")
        return {"results": [], "fallback": True}

    def delete_document(self, document_id: str) -> Dict:
        """
        从 R2R 删除文档

        尝试两种 API 路径：
          1. /v3/documents/{id} （R2R 标准 API）
          2. /documents/{id}     （简化路径）

        Args:
            document_id: R2R 文档ID

        Returns:
            {"status": "deleted"} 或 {"status": "failed", "error"}
        """
        if not document_id:
            return {"status": "failed", "error": "document_id 为空"}

        # 尝试 R2R 标准 API
        result = self._request("DELETE", f"/v3/documents/{document_id}", timeout=15)
        if result:
            log.info(f"R2RClient | delete_document 成功 | doc={document_id}")
            self._invalidate_cache()
            return result

        # 尝试简化路径
        result = self._request("DELETE", f"/documents/{document_id}", timeout=15)
        if result:
            log.info(f"R2RClient | delete_document 成功(简化路径) | doc={document_id}")
            self._invalidate_cache()
            return result

        return {"status": "failed", "error": "delete request failed"}

    def search(self, query: str, top_k: int = 3, filters: Optional[Dict] = None, project_id: str = "") -> Dict:
        """
        语义搜索

        Args:
            query: 搜索查询
            top_k: 返回数量（最大 3）
            filters: 过滤条件
            project_id: 项目 ID

        Returns:
            {"results", "total"} 或降级结果
        """
        top_k = min(top_k, MAX_TOP_K)

        # 检查缓存
        cache_key = self._cache_key("search", {"query": query[:200], "top_k": top_k, "project_id": project_id})
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # 请求
        result = self._request("POST", "/search", {
            "query": query,
            "top_k": top_k,
            "filters": filters,
            "project_id": project_id,
        })

        if result:
            self._set_cache(cache_key, result)
            return result

        # 降级
        log.warning("R2RClient | search 失败，降级返回空结果")
        return {"results": [], "total": 0, "fallback": True}

    def retrieve(self, query: str, top_k: int = 3, filters: Optional[Dict] = None, project_id: str = "") -> Dict:
        """
        增强检索（RAG 模式）

        Args:
            query: 查询文本
            top_k: 返回数量（最大 3）
            filters: 过滤条件
            project_id: 项目 ID

        Returns:
            {"context", "elements", "total"} 或降级结果
        """
        top_k = min(top_k, MAX_TOP_K)

        # 检查缓存
        cache_key = self._cache_key("retrieve", {"query": query[:200], "top_k": top_k, "project_id": project_id})
        cached = self._get_cache(cache_key)
        if cached:
            return cached

        # 请求
        result = self._request("POST", "/retrieve", {
            "query": query,
            "top_k": top_k,
            "filters": filters,
            "project_id": project_id,
        })

        if result:
            # 截断上下文
            if "context" in result and isinstance(result["context"], str):
                result["context"] = self._truncate_context(result["context"])
            self._set_cache(cache_key, result)
            return result

        # 降级：返回默认业务规则
        log.warning("R2RClient | retrieve 失败，降级为默认业务规则")
        return self._fallback_retrieve(query)

    def health(self) -> Dict:
        """
        健康检查

        Returns:
            {"status", "provider", "base_url"}
        """
        result = self._request("GET", "/health", timeout=5)
        if result:
            return {"status": "healthy", "provider": settings.KNOWLEDGE_PROVIDER, **result}
        return {
            "status": "unavailable",
            "provider": settings.KNOWLEDGE_PROVIDER,
            "base_url": self.base_url,
            "fallback": True,
        }

    # ===== 降级 =====

    def _fallback_retrieve(self, query: str) -> Dict:
        """降级检索：返回默认业务规则（无 RAG 继续生成）"""
        return {
            "context": json.dumps({
                "constraints": [
                    "所有接口必须校验必填参数",
                    "所有接口必须校验参数类型和格式",
                    "所有接口必须处理异常和边界情况",
                    "所有写操作必须校验权限",
                ],
            }, ensure_ascii=False),
            "elements": [],
            "total": 4,
            "fallback": True,
        }


# ===== 全局单例 =====

_client: Optional[AnythingChatClient] = None


def get_knowledge_client() -> AnythingChatClient:
    """获取知识客户端单例"""
    global _client
    if _client is None:
        _client = AnythingChatClient()
    return _client


# 兼容旧代码
knowledge_client = None  # 延迟初始化


def _get_legacy_client() -> AnythingChatClient:
    """兼容旧 knowledge_client 全局变量"""
    return get_knowledge_client()
