"""
LLM Gateway 数据结构定义

- LLMResponse: 一次模型调用的统一返回结构
- LLMCallContext: 调用上下文(传递给 Provider 的参数集)
- ProviderHealth: 供应商健康状态(熔断用)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class LLMResponse:
    """
    统一的模型调用返回结构

    无论是哪个 Provider 返回的,都封装为 LLMResponse,
    上层 Agent 只关心 content 与 token 统计。
    """
    content: str = ""
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost: float = 0.0  # 单位:元(人民币)
    duration: float = 0.0  # 秒
    success: bool = True
    error: Optional[str] = None
    error_type: Optional[str] = None  # timeout / rate_limit / auth / network / unknown
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)
    # 切换链信息:实际命中第几个候选,便于追踪 fallback 行为
    fallback_used: bool = False
    fallback_chain: List[str] = field(default_factory=list)
    requested_model: str = ""  # 原始请求的模型(可能与实际命中的 model 不同)

    @property
    def usage(self) -> Dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "content": self.content,
            "model": self.model,
            "provider": self.provider,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost": round(self.cost, 6),
            "duration": round(self.duration, 3),
            "success": self.success,
            "error": self.error,
            "error_type": self.error_type,
            "fallback_used": self.fallback_used,
            "fallback_chain": self.fallback_chain,
            "requested_model": self.requested_model,
        }


@dataclass
class LLMCallContext:
    """
    一次 LLM 调用的上下文参数

    由 LLMGateway.chat() 构造,传给 Provider.chat()。
    Provider 只读取自己需要的字段。
    """
    messages: List[Dict[str, str]] = field(default_factory=list)
    model: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    timeout: int = 120
    # 扩展参数(top_p / frequency_penalty / stop 等)
    extra_params: Dict[str, Any] = field(default_factory=dict)
    # 追踪字段(用于落库,不影响调用)
    agent_name: str = ""
    task_id: str = ""
    step: str = ""
    session_key: str = ""
    # 调用方标识,用于路由与配额
    caller: str = ""


@dataclass
class ProviderHealth:
    """
    供应商健康状态(熔断器)

    - 连续失败超过 threshold 进入 OPEN(熔断),拒绝调用
    - 经过 cooldown 秒后进入 HALF_OPEN,放一次试探请求
    - 试探成功 → CLOSED,失败 → 重新 OPEN
    """
    provider: str
    consecutive_failures: int = 0
    state: str = "closed"  # closed / open / half_open
    last_failure_time: Optional[datetime] = None
    last_success_time: Optional[datetime] = None
    failure_threshold: int = 3
    cooldown: int = 60  # 秒

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.state = "closed"
        self.last_success_time = datetime.now()

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        self.last_failure_time = datetime.now()
        if self.consecutive_failures >= self.failure_threshold:
            self.state = "open"

    def allow_request(self) -> bool:
        """是否允许调用(熔断器是否闭合/半开)"""
        if self.state == "closed":
            return True
        if self.state == "open":
            # 冷却期过后转半开
            if self.last_failure_time:
                elapsed = (datetime.now() - self.last_failure_time).total_seconds()
                if elapsed >= self.cooldown:
                    self.state = "half_open"
                    return True
            return False
        # half_open:只允许一次试探
        return True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.state,
            "consecutive_failures": self.consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "cooldown": self.cooldown,
            "last_failure_time": self.last_failure_time.isoformat() if self.last_failure_time else None,
            "last_success_time": self.last_success_time.isoformat() if self.last_success_time else None,
        }
