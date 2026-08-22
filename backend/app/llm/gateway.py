"""
LLMGateway - 大模型统一调用网关(核心)

这是所有 Agent 调用大模型的唯一入口。

调用链:
    Agent → LLMGateway.chat()
              ├─ ModelRouter.select_targets() → 路由目标序列
              ├─ 遍历 targets:
              │    ├─ ProviderFactory.get(provider) → BaseProvider
              │    ├─ provider.chat(ctx) → LLMResponse
              │    ├─ 成功 → 计算费用 + 落库 + 返回
              │    └─ 失败 → ModelRouter.record_failure() → 继续下一个
              └─ 全部失败 → 返回最后一个错误(或 mock 兜底)

设计原则:
- Agent 禁止直接调用模型 API,必须经过 Gateway
- 所有调用(成功/失败)都落库 llm_call_log
- 失败自动切换,调用方无感知
- Token 与费用统计实时更新
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.llm.types import LLMCallContext, LLMResponse
from app.llm.cost_calculator import get_cost_calculator
from app.llm.providers.base import BaseProvider
from app.llm.providers.factory import get_provider_factory
from app.llm.model_router import RouteTarget, get_model_router

logger = logging.getLogger(__name__)


class LLMGateway:
    """
    大模型统一调用网关(单例)

    使用方式:
        from app.llm import get_gateway
        gateway = get_gateway()
        content = await gateway.chat(
            agent_name="case_agent",
            system_prompt="你是一个用例生成专家",
            user_prompt="为登录功能生成测试用例",
        )
    """

    def __init__(self) -> None:
        self._router = get_model_router()
        self._factory = get_provider_factory()
        self._cost = get_cost_calculator()
        self._initialized = False

    def initialize(self, settings: Any = None, force: bool = False) -> None:
        """初始化(加载 Provider 配置)"""
        if self._initialized and not force:
            return
        self._factory.initialize(settings, force=force)
        self._initialized = True
        logger.info("LLMGateway initialized")

    # ------------------------------------------------------------------ #
    #  主入口:chat()                                                      #
    # ------------------------------------------------------------------ #

    async def chat(
        self,
        agent_name: str = "",
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
        task_id: str = "",
        step: str = "",
        session_key: str = "",
        task_type: str = "",
        preferred_model: str = "",
        preferred_provider: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        统一大模型调用入口,返回文本内容

        等价于 chat_with_response() 后取 .content,
        供只需要文本结果的调用方使用。
        """
        resp = await self.chat_with_response(
            agent_name=agent_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            task_id=task_id,
            step=step,
            session_key=session_key,
            task_type=task_type,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
            extra_params=extra_params,
        )
        if not resp.success:
            raise RuntimeError(
                f"LLMGateway: all providers failed. Last error ({resp.error_type}): {resp.error}"
            )
        return resp.content

    # ------------------------------------------------------------------ #
    #  chat_with_response() - 返回完整 LLMResponse                        #
    # ------------------------------------------------------------------ #

    async def chat_with_response(
        self,
        agent_name: str = "",
        system_prompt: str = "",
        user_prompt: str = "",
        messages: Optional[List[Dict[str, str]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        timeout: int = 120,
        task_id: str = "",
        step: str = "",
        session_key: str = "",
        task_type: str = "",
        preferred_model: str = "",
        preferred_provider: str = "",
        extra_params: Optional[Dict[str, Any]] = None,
    ) -> LLMResponse:
        """
        调用大模型,返回完整 LLMResponse(含 token/费用/耗时)

        与 chat() 相同,但返回结构化响应,供调用方获取统计信息。
        Agent 的 call_llm 用这个方法,以便 emit_event 时携带 token 信息。
        """
        if not self._initialized:
            self.initialize()

        if messages is None:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": user_prompt})

        chain, targets = self._router.select_targets(
            agent_name=agent_name,
            task_type=task_type,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
        )
        chain_names = [f"{t.provider}:{t.model}" for t in targets]

        last_error: Optional[str] = None
        last_error_type: Optional[str] = None
        last_response: Optional[LLMResponse] = None

        for idx, target in enumerate(targets):
            provider = self._factory.get(target.provider)
            if provider is None or not provider.enabled:
                continue

            ctx = LLMCallContext(
                messages=messages,
                model=target.model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=timeout,
                extra_params=extra_params or {},
                agent_name=agent_name,
                task_id=task_id,
                step=step,
                session_key=session_key,
            )

            start = time.time()
            resp = await provider.chat(ctx)
            resp.duration = time.time() - start

            if resp.success:
                self._router.record_success(target.provider)
                resp.cost = self._cost.calculate(
                    model=resp.model,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    provider=target.provider,
                )
                resp.requested_model = preferred_model or targets[0].model
                resp.fallback_used = idx > 0
                resp.fallback_chain = chain_names

                await self._log_call(
                    agent_name=agent_name,
                    task_id=task_id,
                    step=step,
                    session_key=session_key,
                    provider=target.provider,
                    model=resp.model,
                    requested_model=resp.requested_model,
                    response=resp,
                    status="success",
                    fallback_used=resp.fallback_used,
                    fallback_chain=chain_names,
                    attempt_index=idx,
                    prompt_preview=system_prompt,
                )

                logger.info(
                    f"[Gateway] chat success: agent={agent_name}, "
                    f"provider={target.provider}, model={resp.model}, "
                    f"tokens={resp.total_tokens}, cost={resp.cost:.6f}, "
                    f"duration={resp.duration:.2f}s, fallback={resp.fallback_used}"
                )
                return resp

            self._router.record_failure(target.provider)
            last_error = resp.error or "unknown error"
            last_error_type = resp.error_type
            last_response = resp

            logger.warning(
                f"[Gateway] target {target.provider}:{target.model} failed "
                f"(attempt {idx + 1}/{len(targets)}): {resp.error_type} - {resp.error}"
            )

            await self._log_call(
                agent_name=agent_name,
                task_id=task_id,
                step=step,
                session_key=session_key,
                provider=target.provider,
                model=target.model,
                requested_model=preferred_model or targets[0].model,
                response=resp,
                status="failed",
                fallback_used=idx > 0,
                fallback_chain=chain_names,
                attempt_index=idx,
                prompt_preview=system_prompt,
            )

        logger.error(
            f"[Gateway] all targets failed for agent={agent_name}, "
            f"chain={chain_names}, last_error={last_error}"
        )
        # 返回最后一个失败的响应(而非抛异常,由调用方决定如何处理)
        if last_response is None:
            last_response = LLMResponse(
                success=False,
                error=f"All providers failed: {last_error}",
                error_type=last_error_type or "unknown",
                fallback_chain=chain_names,
            )
        return last_response

    # ------------------------------------------------------------------ #
    #  chat_json() - 返回解析后的 JSON                                    #
    # ------------------------------------------------------------------ #

    async def chat_json(
        self,
        agent_name: str = "",
        system_prompt: str = "",
        user_prompt: str = "",
        temperature: float = 0.3,
        task_id: str = "",
        step: str = "",
        session_key: str = "",
        task_type: str = "",
        preferred_model: str = "",
        preferred_provider: str = "",
    ) -> Dict[str, Any]:
        """调用 chat 并解析 JSON 结果"""
        import re
        raw = await self.chat(
            agent_name=agent_name,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            task_id=task_id,
            step=step,
            session_key=session_key,
            task_type=task_type,
            preferred_model=preferred_model,
            preferred_provider=preferred_provider,
        )
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # 尝试从 markdown 代码块提取
            match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw)
            if match:
                return json.loads(match.group(1))
            # 尝试提取 { ... }
            start = raw.find("{")
            end = raw.rfind("}")
            if start != -1 and end != -1 and end > start:
                return json.loads(raw[start:end + 1])
            return {"error": "Failed to parse JSON", "raw": raw[:500]}

    # ------------------------------------------------------------------ #
    #  落库                                                              #
    # ------------------------------------------------------------------ #

    async def _log_call(
        self,
        agent_name: str,
        task_id: str,
        step: str,
        session_key: str,
        provider: str,
        model: str,
        requested_model: str,
        response: LLMResponse,
        status: str,
        fallback_used: bool,
        fallback_chain: List[str],
        attempt_index: int,
        prompt_preview: str,
    ) -> None:
        """写入 llm_call_log 表(失败不阻塞主流程)"""
        try:
            from app.db.database import SessionLocal
            from app.models.llm_call_log import LLMCallLog
            db = SessionLocal()
            try:
                log = LLMCallLog(
                    agent_name=agent_name or "unknown",
                    task_id=task_id or None,
                    step=step or None,
                    session_key=session_key or None,
                    provider=provider,
                    model=model,
                    requested_model=requested_model or None,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    total_tokens=response.total_tokens,
                    cost=response.cost,
                    currency="CNY",
                    duration=response.duration,
                    status=status,
                    error_message=response.error,
                    error_type=response.error_type,
                    fallback_used=1 if fallback_used else 0,
                    fallback_chain=json.dumps(fallback_chain, ensure_ascii=False),
                    attempt_index=attempt_index,
                    prompt_preview=(prompt_preview[:500] if prompt_preview else None),
                )
                db.add(log)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[Gateway] _log_call failed: {e}")

    # ------------------------------------------------------------------ #
    #  查询统计                                                          #
    # ------------------------------------------------------------------ #

    def get_stats(
        self,
        agent_name: str = "",
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """查询调用统计(同步,从 DB 聚合)"""
        try:
            from app.db.database import SessionLocal
            from app.models.llm_call_log import LLMCallLog
            from sqlalchemy import func, select
            db = SessionLocal()
            try:
                stmt = select(
                    func.count(LLMCallLog.id).label("total_calls"),
                    func.sum(LLMCallLog.prompt_tokens).label("total_prompt_tokens"),
                    func.sum(LLMCallLog.completion_tokens).label("total_completion_tokens"),
                    func.sum(LLMCallLog.total_tokens).label("total_tokens"),
                    func.sum(LLMCallLog.cost).label("total_cost"),
                    func.avg(LLMCallLog.duration).label("avg_duration"),
                    func.sum(LLMCallLog.fallback_used).label("fallback_count"),
                )
                if agent_name:
                    stmt = stmt.where(LLMCallLog.agent_name == agent_name)
                if start_time:
                    stmt = stmt.where(LLMCallLog.created_at >= start_time)
                if end_time:
                    stmt = stmt.where(LLMCallLog.created_at <= end_time)
                result = db.execute(stmt).one()
                return {
                    "total_calls": result.total_calls or 0,
                    "total_prompt_tokens": result.total_prompt_tokens or 0,
                    "total_completion_tokens": result.total_completion_tokens or 0,
                    "total_tokens": result.total_tokens or 0,
                    "total_cost": round(float(result.total_cost or 0), 4),
                    "avg_duration": round(float(result.avg_duration or 0), 3),
                    "fallback_count": result.fallback_count or 0,
                }
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[Gateway] get_stats failed: {e}")
            return {
                "total_calls": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_cost": 0,
                "avg_duration": 0,
                "fallback_count": 0,
            }

    def list_recent_logs(
        self,
        agent_name: str = "",
        limit: int = 50,
        status: str = "",
    ) -> List[Dict[str, Any]]:
        """查询最近调用记录"""
        try:
            from app.db.database import SessionLocal
            from app.models.llm_call_log import LLMCallLog
            db = SessionLocal()
            try:
                q = db.query(LLMCallLog)
                if agent_name:
                    q = q.filter(LLMCallLog.agent_name == agent_name)
                if status:
                    q = q.filter(LLMCallLog.status == status)
                q = q.order_by(LLMCallLog.created_at.desc()).limit(limit)
                return [log.to_dict() for log in q.all()]
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"[Gateway] list_recent_logs failed: {e}")
            return []

    # ------------------------------------------------------------------ #
    #  运维接口                                                          #
    # ------------------------------------------------------------------ #

    def list_providers(self) -> List[Dict[str, Any]]:
        """列出所有供应商"""
        providers = self._factory.list_providers(include_disabled=True)
        return [
            {
                "name": p.name,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "default_model": p.config.default_model,
                "models": p.config.models,
            }
            for p in providers
        ]

    def list_chains(self) -> List[Dict[str, Any]]:
        """列出所有路由链"""
        return [c.to_dict() for c in self._router.list_chains()]

    def list_health(self) -> List[Dict[str, Any]]:
        """列出所有供应商健康状态"""
        return [h.to_dict() for h in self._router.list_health()]

    async def health_check_all(self) -> List[Dict[str, Any]]:
        """对所有供应商执行健康检查"""
        import asyncio
        providers = self._factory.list_providers(include_disabled=False)
        async def _check(p: BaseProvider) -> Dict[str, Any]:
            try:
                ok = await p.health_check()
                return {
                    "provider": p.name,
                    "display_name": p.display_name,
                    "healthy": ok,
                    "enabled": p.enabled,
                }
            except Exception as e:
                return {
                    "provider": p.name,
                    "display_name": p.display_name,
                    "healthy": False,
                    "enabled": p.enabled,
                    "error": str(e),
                }
        results = await asyncio.gather(*[_check(p) for p in providers])
        return results

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initialized": self._initialized,
            "providers": self.list_providers(),
            "chains": self.list_chains(),
            "health": self.list_health(),
            "stats": self.get_stats(),
        }


# 单例
_gateway: Optional[LLMGateway] = None


def get_gateway() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway()
    return _gateway
