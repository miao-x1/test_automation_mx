"""
ModelRouter - 模型路由器

职责:
1. 模型选择:根据 Agent 名称 / 任务类型路由到最优模型
2. 失败切换:按配置的 fallback chain 自动切换备用模型
3. 健康检查:维护各供应商的熔断状态,跳过不可用的 provider
4. 熔断恢复:冷却期后自动放试探请求恢复

设计:
- 路由策略:Agent 显式指定 > Agent 默认配置 > 全局默认
- fallback chain:qwen → deepseek → ollama → mock(可热更新)
- 熔断器:连续失败 N 次进入 OPEN,冷却后 HALF_OPEN 试探
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.llm.types import ProviderHealth
from app.llm.providers.base import BaseProvider
from app.llm.providers.factory import get_provider_factory

logger = logging.getLogger(__name__)


@dataclass
class RouteTarget:
    """一个路由目标(模型 + provider)"""
    provider: str
    model: str
    # 该目标是否可用(运行时由熔断器决定)
    available: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "available": self.available,
        }


@dataclass
class FallbackChain:
    """失败切换链"""
    name: str  # 链名(通常是 agent_name 或 "default")
    targets: List[RouteTarget] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "targets": [t.to_dict() for t in self.targets],
        }


class ModelRouter:
    """模型路由器(单例)"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # agent_name / task_type -> FallbackChain
        self._chains: Dict[str, FallbackChain] = {}
        # provider -> ProviderHealth(熔断器)
        self._health: Dict[str, ProviderHealth] = {}
        # 全局默认 fallback chain
        self._default_chain_name = "default"
        self._init_default_chains()

    def _init_default_chains(self) -> None:
        """初始化默认路由链"""
        # 全局默认:qwen → deepseek → ollama → mock
        self.register_chain(
            self._default_chain_name,
            [
                RouteTarget("qwen", "qwen-plus"),
                RouteTarget("deepseek", "deepseek-chat"),
                RouteTarget("ollama", "qwen2.5:7b"),
                RouteTarget("mock", "mock-model"),
            ],
        )
        # 视觉类任务:优先 qwen-vl
        self.register_chain(
            "vision",
            [
                RouteTarget("qwen", "qwen-vl-plus"),
                RouteTarget("qwen", "qwen-vl-max"),
                RouteTarget("mock", "mock-model"),
            ],
        )
        # 代码生成:优先 coder
        self.register_chain(
            "code",
            [
                RouteTarget("qwen", "qwen-coder-plus"),
                RouteTarget("deepseek", "deepseek-coder"),
                RouteTarget("ollama", "qwen2.5:7b"),
                RouteTarget("mock", "mock-model"),
            ],
        )

    # ------------------------------------------------------------------ #
    #  路由链管理                                                         #
    # ------------------------------------------------------------------ #

    def register_chain(self, name: str, targets: List[RouteTarget]) -> None:
        """注册或覆盖一条路由链"""
        with self._lock:
            self._chains[name] = FallbackChain(name=name, targets=list(targets))
        logger.info(f"ModelRouter: registered chain '{name}' "
                    f"({len(targets)} targets)")

    def get_chain(self, name: str) -> FallbackChain:
        """获取路由链(不存在则返回 default)"""
        with self._lock:
            chain = self._chains.get(name)
            if chain is None:
                chain = self._chains.get(self._default_chain_name)
        if chain is None:
            # 极端情况:default 也没注册
            chain = FallbackChain(name=name, targets=[RouteTarget("mock", "mock-model")])
        return chain

    def list_chains(self) -> List[FallbackChain]:
        with self._lock:
            return list(self._chains.values())

    def remove_chain(self, name: str) -> bool:
        with self._lock:
            return self._chains.pop(name, None) is not None

    # ------------------------------------------------------------------ #
    #  模型选择 + 失败切换                                                #
    # ------------------------------------------------------------------ #

    def select_targets(
        self,
        agent_name: str = "",
        task_type: str = "",
        preferred_model: str = "",
        preferred_provider: str = "",
    ) -> Tuple[FallbackChain, List[RouteTarget]]:
        """
        选择路由目标序列(按优先级排序)

        返回:(命中的 FallbackChain, 实际可用的 target 列表)

        路由优先级:
        1. 调用方显式指定的 preferred_model + preferred_provider
        2. agent_name 对应的专属链
        3. task_type 对应的链(vision/code)
        4. default 链

        每个 target 都会经过熔断器过滤:OPEN 状态的 provider 被跳过。
        """
        chain = self._resolve_chain(agent_name, task_type)

        targets = list(chain.targets)

        # 如果调用方指定了 preferred,插到最前面
        if preferred_model and preferred_provider:
            preferred = RouteTarget(preferred_provider, preferred_model)
            targets = [preferred] + targets

        # 过滤掉熔断中的 provider,但保留至少一个兜底(mock 永不熔断)
        available: List[RouteTarget] = []
        for t in targets:
            if self._is_provider_available(t.provider):
                t.available = True
                available.append(t)
            else:
                t.available = False
                logger.debug(f"ModelRouter: skip provider '{t.provider}' (circuit open)")

        # 如果全部熔断,强制放 mock(最后兜底)
        if not available:
            mock_target = RouteTarget("mock", "mock-model")
            mock_target.available = True
            available = [mock_target]
            logger.warning(
                f"ModelRouter: all providers circuit-open, fallback to mock"
            )

        return chain, available

    def _resolve_chain(self, agent_name: str, task_type: str) -> FallbackChain:
        """解析命中的路由链"""
        with self._lock:
            # 1. agent 专属链
            if agent_name and agent_name in self._chains:
                return self._chains[agent_name]
            # 2. task_type 链
            if task_type and task_type in self._chains:
                return self._chains[task_type]
            # 3. default
            return self._chains.get(
                self._default_chain_name,
                FallbackChain(name="empty", targets=[RouteTarget("mock", "mock-model")]),
            )

    # ------------------------------------------------------------------ #
    #  熔断器                                                             #
    # ------------------------------------------------------------------ #

    def _is_provider_available(self, provider: str) -> bool:
        """检查 provider 是否可用(熔断器状态)"""
        with self._lock:
            health = self._health.get(provider)
            if health is None:
                return True  # 未追踪 = 可用
            return health.allow_request()

    def record_success(self, provider: str) -> None:
        with self._lock:
            health = self._health.get(provider)
            if health is None:
                health = ProviderHealth(provider=provider)
                self._health[provider] = health
            health.record_success()

    def record_failure(self, provider: str) -> None:
        with self._lock:
            health = self._health.get(provider)
            if health is None:
                health = ProviderHealth(provider=provider)
                self._health[provider] = health
            health.record_failure()
            logger.warning(
                f"ModelRouter: provider '{provider}' failure "
                f"(count={health.consecutive_failures}, state={health.state})"
            )

    def get_health(self, provider: str) -> ProviderHealth:
        with self._lock:
            return self._health.get(provider, ProviderHealth(provider=provider))

    def list_health(self) -> List[ProviderHealth]:
        with self._lock:
            return list(self._health.values())

    def reset_health(self, provider: str = "") -> None:
        """手动重置熔断器(管理 API 用)"""
        with self._lock:
            if provider:
                if provider in self._health:
                    self._health[provider] = ProviderHealth(provider=provider)
            else:
                self._health.clear()
        logger.info(f"ModelRouter: reset health for '{provider or 'all'}'")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "chains": [c.to_dict() for c in self._chains.values()],
                "health": [h.to_dict() for h in self._health.values()],
                "default_chain": self._default_chain_name,
            }


# 单例
_router: Optional[ModelRouter] = None


def get_model_router() -> ModelRouter:
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router
