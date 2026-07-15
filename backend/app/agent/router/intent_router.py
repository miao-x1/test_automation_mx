"""
IntentRouter - 意图路由器

根据任务类型自动选择 Agent。
所有选择逻辑集中管理，禁止散落 if-else。

使用方式：
    router = IntentRouter()
    agent_name = router.route(input_data)
    # agent_name = "requirement_agent"

扩展方式：
    1. 在 rules.py 中添加 RoutingRule
    2. 或调用 IntentRouter.register_rule(rule)
"""
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from urllib.parse import urlparse

from app.agent.core.types import IntentType
from app.core.logger import log


@dataclass
class RoutingRule:
    """
    路由规则。

    匹配逻辑（OR 关系，任一命中即路由）：
    - file_extensions: 文件扩展名匹配
    - keywords: 关键词匹配
    - url_patterns: URL 前缀匹配
    - custom_matcher: 自定义匹配函数
    - is_default: 默认规则（所有规则都不匹配时使用）
    """
    intent: IntentType
    agent_name: str
    description: str = ""
    keywords: List[str] = field(default_factory=list)
    file_extensions: List[str] = field(default_factory=list)
    url_patterns: List[str] = field(default_factory=list)
    custom_matcher: Optional[Callable[[Dict[str, Any]], bool]] = None
    is_default: bool = False
    priority: int = 0  # 数字越大优先级越高


class IntentRouter:
    """
    意图路由器（单例）。

    职责：
    1. 根据输入数据自动判断意图类型
    2. 根据意图选择目标 Agent
    3. 支持自定义规则注册
    4. 支持优先级排序

    禁止散落 if-else，所有路由逻辑通过规则表管理。
    """

    _instance: Optional["IntentRouter"] = None
    _rules: List[RoutingRule] = []

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._rules = []
        self._load_default_rules()

    def _load_default_rules(self) -> None:
        """加载默认规则"""
        from app.agent.router.rules import get_default_rules
        self._rules = get_default_rules()
        log.info(f"IntentRouter loaded {len(self._rules)} default rules")

    # ---- 路由 ----

    def route(self, input_data: Dict[str, Any]) -> str:
        """
        根据输入数据路由到目标 Agent。

        参数：
        - input_data: 包含 text, images, urls, file_path, script_content 等

        返回：Agent 名称
        """
        # 按优先级排序
        rules = sorted(self._rules, key=lambda r: -r.priority)

        # 默认 Agent
        default_agent = "requirement_agent"

        for rule in rules:
            if rule.is_default:
                default_agent = rule.agent_name
                continue

            if self._match_rule(rule, input_data):
                log.info(
                    f"IntentRouter: matched rule '{rule.description}' "
                    f"→ agent='{rule.agent_name}'"
                )
                return rule.agent_name

        log.info(f"IntentRouter: no rule matched, using default='{default_agent}'")
        return default_agent

    def route_with_intent(self, input_data: Dict[str, Any]) -> tuple:
        """
        路由并返回 (agent_name, intent_type)。

        返回：(Agent名称, IntentType)
        """
        rules = sorted(self._rules, key=lambda r: -r.priority)
        default_agent = "requirement_agent"
        default_intent = IntentType.REQUIREMENT

        for rule in rules:
            if rule.is_default:
                default_agent = rule.agent_name
                default_intent = rule.intent
                continue

            if self._match_rule(rule, input_data):
                log.info(
                    f"IntentRouter: matched '{rule.intent.value}' "
                    f"→ agent='{rule.agent_name}'"
                )
                return rule.agent_name, rule.intent

        return default_agent, default_intent

    def _match_rule(self, rule: RoutingRule, input_data: Dict[str, Any]) -> bool:
        """检查输入是否匹配规则"""
        # 自定义匹配
        if rule.custom_matcher:
            try:
                if rule.custom_matcher(input_data):
                    return True
            except Exception:
                pass

        # 文件扩展名匹配
        if rule.file_extensions:
            file_path = input_data.get("file_path", "")
            filename = input_data.get("filename", "")
            for ext in rule.file_extensions:
                if file_path.lower().endswith(ext) or filename.lower().endswith(ext):
                    return True

        # URL 模式匹配
        if rule.url_patterns:
            urls = input_data.get("urls", [])
            if isinstance(urls, str):
                urls = [urls]
            text = input_data.get("text", "")
            for url in urls:
                for pattern in rule.url_patterns:
                    if pattern in str(url).lower():
                        return True
            for pattern in rule.url_patterns:
                if pattern in text.lower():
                    return True

        # 关键词匹配
        if rule.keywords:
            text = input_data.get("text", "")
            text_lower = text.lower()
            for kw in rule.keywords:
                if kw.lower() in text_lower:
                    return True

        return False

    # ---- 规则管理 ----

    def register_rule(self, rule: RoutingRule) -> None:
        """注册自定义路由规则"""
        self._rules.append(rule)
        log.info(f"IntentRouter: rule registered '{rule.description}' → '{rule.agent_name}'")

    def unregister_rule(self, intent: IntentType, agent_name: str) -> None:
        """注销路由规则"""
        self._rules = [
            r for r in self._rules
            if not (r.intent == intent and r.agent_name == agent_name)
        ]

    def list_rules(self) -> List[dict]:
        """列出所有路由规则"""
        return [
            {
                "intent": r.intent.value,
                "agent_name": r.agent_name,
                "description": r.description,
                "keywords": r.keywords,
                "file_extensions": r.file_extensions,
                "url_patterns": r.url_patterns,
                "is_default": r.is_default,
                "priority": r.priority,
            }
            for r in sorted(self._rules, key=lambda r: -r.priority)
        ]

    def get_agent_for_intent(self, intent: IntentType) -> str:
        """根据 IntentType 获取 Agent 名称"""
        for rule in self._rules:
            if rule.intent == intent:
                return rule.agent_name
        return "requirement_agent"

    # ---- 便捷路由方法 ----

    def route_by_file(self, filename: str) -> str:
        """根据文件名路由"""
        return self.route({"file_path": filename, "filename": filename, "text": ""})

    def route_by_text(self, text: str) -> str:
        """根据文本路由"""
        return self.route({"text": text})

    def route_by_url(self, url: str) -> str:
        """根据URL路由"""
        return self.route({"urls": [url], "text": url})


# 全局单例
_intent_router: Optional[IntentRouter] = None


def get_intent_router() -> IntentRouter:
    """获取 IntentRouter 单例"""
    global _intent_router
    if _intent_router is None:
        _intent_router = IntentRouter()
    return _intent_router
