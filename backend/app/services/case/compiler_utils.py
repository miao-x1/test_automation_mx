"""
Case Compiler Utils - 编译服务工具函数与常量

从 compiler.py 拆分而来，包含：
  - RAG_TOP_K_LIMIT 常量
  - _progress_queues 全局进度队列管理器
  - PIPELINE_STATES 状态机
  - push_progress / check_rag_available / get_default_business_rules / limit_rag_result
"""
import time as _time
import asyncio
from typing import Any, Dict, Optional

# RAG限制常量
RAG_TOP_K_LIMIT = 3

# 全局进度队列管理器（供SSE端点注册/查询）
_progress_queues: Dict[int, asyncio.Queue] = {}

# Pipeline状态机
PIPELINE_STATES = {
    "init": "初始化",
    "parsing": "解析输入",
    "rag_done": "RAG检索完成",
    "l1_done": "L1完成",
    "l2_done": "L2完成",
    "l3_done": "L3完成",
    "failed": "失败",
}


def push_progress(queue: Optional[asyncio.Queue], event_type: str, payload: Any = None):
    """推送SSE进度事件"""
    if queue is None:
        return
    try:
        queue.put_nowait({
            "type": event_type,
            "payload": payload,
            "ts": _time.time(),
        })
    except Exception:
        pass


def check_rag_available() -> bool:
    """检查RAG服务是否可用（通过 ContextRouter 健康检查）"""
    try:
        from app.services.context_router import get_context_router
        router = get_context_router()
        health = router.health_check()
        # R2R 或 Milvus 任一可用即可
        r2r_ok = health.get("r2r", {}).get("status") == "healthy"
        milvus_ok = health.get("milvus", {}).get("status") == "healthy"
        return r2r_ok or milvus_ok
    except Exception:
        return False


def get_default_business_rules() -> Dict[str, Any]:
    """RAG不可用时注入默认业务规则"""
    return {
        "context": {
            "apis": [],
            "entities": [],
            "constraints": [
                {"text": "所有接口必须校验必填参数", "score": 1.0, "source": "默认规则"},
                {"text": "所有接口必须校验参数类型和格式", "score": 1.0, "source": "默认规则"},
                {"text": "所有接口必须处理异常和边界情况", "score": 1.0, "source": "默认规则"},
                {"text": "所有写操作必须校验权限", "score": 1.0, "source": "默认规则"},
            ],
            "flows": [],
        },
        "raw_chunks": [],
        "total": 4,
        "fallback": True,
    }


def limit_rag_result(rag_context: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """限制RAG结果：top_k ≤ 3，chunk截断"""
    if not rag_context:
        return rag_context

    ctx = rag_context.get("context", {})
    max_chars = 500 * 3

    for key in ("apis", "entities", "constraints", "flows"):
        items = ctx.get(key, [])
        items = items[:RAG_TOP_K_LIMIT]
        for item in items:
            text = item.get("text", "")
            if len(text) > max_chars:
                item["text"] = text[:max_chars] + "..."
        ctx[key] = items

    rag_context["context"] = ctx
    return rag_context
