"""
统一 LLM 调用工具

所有 Agent/Service 必须通过此模块调用 LLM，禁止重复实现 httpx.post 直连 DashScope。

使用方式：
    from app.core.llm import call_llm, call_llm_json

    # 文本调用
    response = call_llm(system_prompt, user_prompt)

    # JSON 调用（自动解析 JSON）
    result = call_llm_json(system_prompt, user_prompt)

配置来源：
    - QWEN_API_KEY: API密钥
    - QWEN_API_URL: API地址（默认 dashscope）
    - QWEN_MODEL: 模型名
    - LLM_TEMPERATURE: 温度（默认 0.3）
    - LLM_MAX_TOKENS: 最大token（默认 8192）
"""
import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _get_llm_config() -> Dict[str, Any]:
    """获取 LLM 配置"""
    return {
        "api_key": settings.QWEN_API_KEY,
        "api_url": getattr(settings, "QWEN_API_URL",
                           "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"),
        "model": getattr(settings, "QWEN_MODEL", "qwen-plus"),
        "temperature": getattr(settings, "LLM_TEMPERATURE", 0.3),
        "max_tokens": getattr(settings, "LLM_MAX_TOKENS", 8192),
        "timeout": getattr(settings, "LLM_TIMEOUT", 120),
    }


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
    timeout: Optional[int] = None,
) -> str:
    """同步调用 LLM，返回文本响应

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        temperature: 温度（None=使用配置默认值）
        max_tokens: 最大token（None=使用配置默认值）
        model: 模型名（None=使用配置默认值）
        timeout: 超时秒数（None=使用配置默认值）

    Returns:
        LLM 生成的文本

    Raises:
        RuntimeError: LLM 调用失败
    """
    config = _get_llm_config()

    api_key = config["api_key"]
    if not api_key:
        raise RuntimeError("未配置 QWEN_API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model or config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": temperature if temperature is not None else config["temperature"],
        "max_tokens": max_tokens or config["max_tokens"],
    }

    try:
        with httpx.Client(timeout=timeout or config["timeout"]) as client:
            resp = client.post(config["api_url"], headers=headers, json=body)
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except httpx.TimeoutException:
        logger.error(f"LLM 调用超时 | timeout={timeout or config['timeout']}s")
        raise RuntimeError(f"LLM 调用超时")
    except Exception as e:
        logger.error(f"LLM 调用失败: {e}")
        raise RuntimeError(f"LLM 调用失败: {e}")


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    model: Optional[str] = None,
) -> Any:
    """同步调用 LLM 并解析 JSON 响应

    Args:
        同 call_llm

    Returns:
        解析后的 JSON 对象（dict 或 list）

    Raises:
        RuntimeError: LLM 调用失败或 JSON 解析失败
    """
    text = call_llm(system_prompt, user_prompt, temperature, max_tokens, model)

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start) if "```" in text[start:] else len(text)
        json_str = text[start:end].strip()
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # 尝试提取 { ... } 或 [ ... ]
    for start_char, end_char in [("{", "}"), ("[", "]")]:
        if start_char in text and end_char in text:
            start = text.index(start_char)
            end = text.rindex(end_char) + 1
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue

    logger.warning(f"LLM JSON 解析失败，返回原始文本 | text={text[:200]}")
    raise RuntimeError(f"LLM 返回内容无法解析为 JSON: {text[:200]}")
