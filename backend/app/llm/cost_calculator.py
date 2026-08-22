"""
费用计算器

维护各模型的单价表(元 / 千 token),根据 token 用量计算费用。
支持:
- 按模型名查询单价(input/output 分开)
- 按供应商前缀匹配(qwen-* / deepseek-* / gpt-*)
- 运行时更新单价(管理 API 热更新)
- 费用汇总统计
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    """模型单价(单位:元 / 千 token)"""
    model: str
    input_price: float  # 输入 token 单价(元/千)
    output_price: float  # 输出 token 单价(元/千)
    provider: str = ""
    currency: str = "CNY"
    note: str = ""


# 默认单价表(参考各供应商官方定价,2024-2026,单位:元/千token)
# 实际部署时应通过管理 API 更新为最新价格
DEFAULT_PRICING: List[ModelPricing] = [
    # ===== Qwen (DashScope) =====
    ModelPricing("qwen-plus", 0.0008, 0.002, "qwen", note="通义千问Plus"),
    ModelPricing("qwen-max", 0.02, 0.06, "qwen", note="通义千问Max"),
    ModelPricing("qwen-turbo", 0.0003, 0.0006, "qwen", note="通义千问Turbo"),
    ModelPricing("qwen-vl-plus", 0.0008, 0.002, "qwen", note="通义千问VL Plus"),
    ModelPricing("qwen-vl-max", 0.02, 0.06, "qwen", note="通义千问VL Max"),
    ModelPricing("qwen-coder-plus", 0.0008, 0.002, "qwen", note="通义千问Coder"),
    # ===== DeepSeek =====
    ModelPricing("deepseek-chat", 0.001, 0.002, "deepseek", note="DeepSeek Chat"),
    ModelPricing("deepseek-coder", 0.001, 0.002, "deepseek", note="DeepSeek Coder"),
    ModelPricing("deepseek-reasoner", 0.004, 0.016, "deepseek", note="DeepSeek R1"),
    # ===== OpenAI (USD→CNY 粗估,7.2汇率) =====
    ModelPricing("gpt-4o", 0.0175, 0.07, "openai", note="GPT-4o"),
    ModelPricing("gpt-4o-mini", 0.00105, 0.0042, "openai", note="GPT-4o mini"),
    ModelPricing("gpt-4-turbo", 0.07, 0.21, "openai", note="GPT-4 Turbo"),
    ModelPricing("gpt-3.5-turbo", 0.0035, 0.007, "openai", note="GPT-3.5 Turbo"),
    # ===== 本地模型(零成本) =====
    ModelPricing("qwen2.5:7b", 0.0, 0.0, "ollama", note="本地模型-零成本"),
    ModelPricing("qwen2.5:14b", 0.0, 0.0, "ollama", note="本地模型-零成本"),
    ModelPricing("llama3.1:8b", 0.0, 0.0, "ollama", note="本地模型-零成本"),
    ModelPricing("deepseek-r1:7b", 0.0, 0.0, "ollama", note="本地模型-零成本"),
    # ===== Mock =====
    ModelPricing("mock-model", 0.0, 0.0, "mock", note="测试-零成本"),
]


class CostCalculator:
    """费用计算器(线程安全单例)"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # model_name -> ModelPricing
        self._exact: Dict[str, ModelPricing] = {}
        # provider -> ModelPricing(前缀匹配用)
        self._by_provider: Dict[str, ModelPricing] = {}
        self._load_defaults()

    def _load_defaults(self) -> None:
        with self._lock:
            for p in DEFAULT_PRICING:
                self._exact[p.model] = p
                # 记录每个 provider 的默认单价(取最后一个作为兜底)
                self._by_provider[p.provider] = p

    def calculate(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        provider: str = "",
    ) -> float:
        """
        计算单次调用费用(元)

        匹配规则:
        1. 精确匹配 model name
        2. provider 默认单价
        3. 未知模型返回 0(保守处理,不报错)
        """
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return 0.0
        pricing = self._lookup(model, provider)
        if pricing is None:
            return 0.0
        cost = (
            (prompt_tokens / 1000.0) * pricing.input_price
            + (completion_tokens / 1000.0) * pricing.output_price
        )
        return round(cost, 6)

    def _lookup(self, model: str, provider: str = "") -> Optional[ModelPricing]:
        with self._lock:
            # 1. 精确匹配
            if model in self._exact:
                return self._exact[model]
            # 2. 前缀匹配(qwen-xxx → qwen-)
            for name, p in self._exact.items():
                if model.startswith(name.rsplit("-", 1)[0] + "-") or name.startswith(model.rsplit(":", 1)[0]):
                    return p
            # 3. provider 默认
            if provider and provider in self._by_provider:
                return self._by_provider[provider]
            # 4. 兜底
            return None

    def get_pricing(self, model: str) -> Optional[ModelPricing]:
        return self._lookup(model)

    def list_pricing(self) -> List[ModelPricing]:
        with self._lock:
            return list(self._exact.values())

    def update_pricing(self, model: str, input_price: float, output_price: float,
                       provider: str = "", note: str = "") -> None:
        """热更新单价(管理 API 调用)"""
        with self._lock:
            p = ModelPricing(
                model=model,
                input_price=input_price,
                output_price=output_price,
                provider=provider,
                note=note,
            )
            self._exact[model] = p
            if provider:
                self._by_provider[provider] = p
        logger.info(f"CostCalculator: updated pricing for '{model}' "
                    f"(input={input_price}, output={output_price})")

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "pricing": [
                    {
                        "model": p.model,
                        "input_price": p.input_price,
                        "output_price": p.output_price,
                        "provider": p.provider,
                        "currency": p.currency,
                        "note": p.note,
                    }
                    for p in self._exact.values()
                ],
            }


# 单例
_calculator: Optional[CostCalculator] = None


def get_cost_calculator() -> CostCalculator:
    global _calculator
    if _calculator is None:
        _calculator = CostCalculator()
    return _calculator
