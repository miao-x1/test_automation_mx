"""
LLM Gateway 管理 API

提供模型供应商、路由链、健康状态、调用统计、费用查询等管理接口。
挂载在 /api/llm-gateway 下。
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.llm import get_gateway
from app.llm.model_router import RouteTarget, get_model_router
from app.llm.cost_calculator import get_cost_calculator
from app.llm.providers.factory import get_provider_factory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm-gateway", tags=["LLM Gateway"])


# ===== 请求模型 =====


class FallbackChainRequest(BaseModel):
    """创建/更新路由链"""
    name: str = Field(..., description="链名(agent_name / task_type / default)")
    targets: List[Dict[str, str]] = Field(
        ..., description='目标列表 [{"provider": "qwen", "model": "qwen-plus"}]'
    )


class PricingUpdateRequest(BaseModel):
    """更新模型单价"""
    model: str
    input_price: float = Field(..., description="输入单价(元/千token)")
    output_price: float = Field(..., description="输出单价(元/千token)")
    provider: str = ""
    note: str = ""


class ChatTestRequest(BaseModel):
    """手动测试调用"""
    agent_name: str = "test"
    system_prompt: str = ""
    user_prompt: str = "Hello"
    temperature: float = 0.7
    max_tokens: int = 100
    preferred_model: str = ""
    preferred_provider: str = ""


# ===== 供应商管理 =====


@router.get("/providers")
async def list_providers():
    """列出所有供应商"""
    gateway = get_gateway()
    return {"providers": gateway.list_providers()}


@router.get("/providers/health")
async def check_providers_health():
    """对所有启用的供应商执行健康检查"""
    gateway = get_gateway()
    results = await gateway.health_check_all()
    return {"results": results}


@router.get("/providers/{provider_name}/models")
async def list_provider_models(provider_name: str):
    """列出指定供应商支持的模型"""
    factory = get_provider_factory()
    provider = factory.get(provider_name)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"Provider '{provider_name}' not found")
    models = await provider.list_models()
    return {"provider": provider_name, "models": models}


# ===== 路由链管理 =====


@router.get("/chains")
async def list_chains():
    """列出所有路由链"""
    router_ = get_model_router()
    return {"chains": [c.to_dict() for c in router_.list_chains()]}


@router.get("/chains/{chain_name}")
async def get_chain(chain_name: str):
    """查看指定路由链"""
    router_ = get_model_router()
    chain = router_.get_chain(chain_name)
    return chain.to_dict()


@router.post("/chains")
async def create_chain(req: FallbackChainRequest):
    """创建或更新路由链"""
    router_ = get_model_router()
    targets = [
        RouteTarget(provider=t["provider"], model=t["model"])
        for t in req.targets
    ]
    router_.register_chain(req.name, targets)
    return {"message": f"Chain '{req.name}' updated", "chain": router_.get_chain(req.name).to_dict()}


@router.delete("/chains/{chain_name}")
async def delete_chain(chain_name: str):
    """删除路由链(不允许删除 default)"""
    if chain_name == "default":
        raise HTTPException(status_code=400, detail="Cannot delete 'default' chain")
    router_ = get_model_router()
    ok = router_.remove_chain(chain_name)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Chain '{chain_name}' not found")
    return {"message": f"Chain '{chain_name}' deleted"}


# ===== 健康与熔断器 =====


@router.get("/health")
async def list_health():
    """列出所有供应商的熔断器状态"""
    router_ = get_model_router()
    return {"health": [h.to_dict() for h in router_.list_health()]}


@router.post("/health/{provider_name}/reset")
async def reset_provider_health(provider_name: str):
    """重置指定供应商的熔断器"""
    router_ = get_model_router()
    router_.reset_health(provider_name)
    return {"message": f"Health reset for '{provider_name}'"}


@router.post("/health/reset")
async def reset_all_health():
    """重置所有熔断器"""
    router_ = get_model_router()
    router_.reset_health()
    return {"message": "All health states reset"}


# ===== 费用与单价 =====


@router.get("/pricing")
async def list_pricing():
    """列出所有模型单价"""
    calc = get_cost_calculator()
    return calc.to_dict()


@router.put("/pricing")
async def update_pricing(req: PricingUpdateRequest):
    """更新模型单价"""
    calc = get_cost_calculator()
    calc.update_pricing(
        model=req.model,
        input_price=req.input_price,
        output_price=req.output_price,
        provider=req.provider,
        note=req.note,
    )
    return {"message": f"Pricing updated for '{req.model}'"}


# ===== 调用统计 =====


@router.get("/stats")
async def get_stats(
    agent_name: str = Query("", description="按 Agent 过滤"),
    days: int = Query(7, description="最近 N 天"),
):
    """查询调用统计"""
    gateway = get_gateway()
    from datetime import timedelta
    start = datetime.now() - timedelta(days=days) if days > 0 else None
    stats = gateway.get_stats(agent_name=agent_name, start_time=start)
    return {
        "filter": {"agent_name": agent_name or "all", "days": days},
        "stats": stats,
    }


@router.get("/logs")
async def list_logs(
    agent_name: str = Query(""),
    status: str = Query(""),
    limit: int = Query(50, le=500),
):
    """查询最近调用记录"""
    gateway = get_gateway()
    logs = gateway.list_recent_logs(agent_name=agent_name, limit=limit, status=status)
    return {"logs": logs, "count": len(logs)}


# ===== 手动测试 =====


@router.post("/chat/test")
async def test_chat(req: ChatTestRequest):
    """手动测试 Gateway 调用(用于验证配置)"""
    gateway = get_gateway()
    try:
        content = await gateway.chat(
            agent_name=req.agent_name,
            system_prompt=req.system_prompt,
            user_prompt=req.user_prompt,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            preferred_model=req.preferred_model,
            preferred_provider=req.preferred_provider,
        )
        return {"success": True, "content": content}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ===== 总览 =====


@router.get("/overview")
async def overview():
    """Gateway 总览(所有信息)"""
    gateway = get_gateway()
    return gateway.to_dict()
