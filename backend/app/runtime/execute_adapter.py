"""适配 Agent.execute 的两种签名，禁止用空 except 吞掉不匹配。"""
from __future__ import annotations

import inspect
from typing import Any


async def invoke_execute(agent: Any, payload: Any, ctx: Any = None) -> Any:
    """调用 agent.execute。

    支持：
      - execute(payload, ctx)   BaseRoutedAgent / Gen2
      - execute(self, **kwargs)  Gen1（如 TestTypeClassifierAgent）
    """
    execute = getattr(agent, "execute", None)
    if execute is None:
        raise RuntimeError(f"Agent '{getattr(agent, 'agent_name', type(agent).__name__)}' 没有 execute")

    try:
        sig = inspect.signature(execute)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"无法读取 execute 签名: {exc}") from exc

    params = [p for p in sig.parameters.values() if p.name != "self"]
    positional = [
        p for p in params
        if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    ]
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)

    if len(positional) >= 2:
        result = execute(payload, ctx)
    elif len(positional) == 1:
        result = execute(payload)
    elif has_var_kw:
        if not isinstance(payload, dict):
            raise TypeError(
                f"{type(agent).__name__}.execute(**kwargs) 需要 dict payload，实际={type(payload).__name__}"
            )
        result = execute(**payload)
    else:
        raise RuntimeError(
            f"Agent '{getattr(agent, 'agent_name', type(agent).__name__)}' "
            f"execute 签名无法适配: {sig}"
        )

    if inspect.isawaitable(result):
        return await result
    return result
