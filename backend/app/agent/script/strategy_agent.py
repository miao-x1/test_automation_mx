"""
StrategyAgent - 脚本生成策略选择Agent

根据可用数据自动选择最佳定位策略：
- DOM: 优先使用CSS/XPath定位器（有RAG/Graph元素时）
- VISION: 使用视觉定位（有截图时）
- OCR: 使用OCR文字识别定位（无定位器但有文字描述时）
- DB: 使用数据库存储的元素定位（有历史元素时）
- PLAYWRIGHT: 标准Playwright脚本（默认策略）
- GRAPH: 使用图数据库路径推理（有Graph业务流时）

策略选择逻辑：
1. 有CSS/XPath定位器 → DOM优先
2. 有截图 → VISION辅助
3. 有Graph业务流 → GRAPH辅助
4. 无定位器但有文字描述 → OCR降级
5. 默认 → PLAYWRIGHT
"""
from typing import Dict, Any, List, Optional
from enum import Enum
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class Strategy(str, Enum):
    """脚本生成策略"""
    DOM = "dom"
    VISION = "vision"
    OCR = "ocr"
    DB = "db"
    PLAYWRIGHT = "playwright"
    GRAPH = "graph"


class StrategyResult:
    """策略选择结果"""

    def __init__(self):
        self.primary: Strategy = Strategy.PLAYWRIGHT
        self.secondary: List[Strategy] = []
        self.confidence: float = 0.5
        self.reason: str = ""
        self.degradation_chain: List[Strategy] = []
        self.locator_priority: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "primary": self.primary.value,
            "secondary": [s.value for s in self.secondary],
            "confidence": self.confidence,
            "reason": self.reason,
            "degradation_chain": [s.value for s in self.degradation_chain],
            "locator_priority": self.locator_priority,
        }


class StrategyAgent(NewBaseAgent):
    """策略选择Agent"""

    agent_name = "strategy"
    display_name = "Strategy Agent"
    description = "脚本生成策略选择Agent - 根据可用数据自动选择最佳定位策略"
    capabilities = [AgentCapability.STRATEGY]

    # 定位器优先级
    LOCATOR_PRIORITY = [
        "data-testid",      # 最稳定
        "data-test",
        "id",
        "name",
        "aria-label",
        "css_selector",
        "xpath",
        "placeholder",
        "text",
    ]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    def select(
        self,
        elements: List[Dict] = None,
        image_paths: List[str] = None,
        graph_business_flow: List[Dict] = None,
        history_scripts: List[Dict] = None,
        execution_records: List[Dict] = None,
        has_url: bool = False,
    ) -> StrategyResult:
        """
        自动选择最佳脚本生成策略

        Args:
            elements: RAG/Graph召回的页面元素
            image_paths: 上传的截图路径
            graph_business_flow: Graph推理业务流
            history_scripts: 历史相似脚本
            execution_records: 历史执行记录
            has_url: 是否有目标URL

        Returns:
            StrategyResult: 策略选择结果
        """
        result = StrategyResult()
        elements = elements or []
        image_paths = image_paths or []
        graph_business_flow = graph_business_flow or []
        history_scripts = history_scripts or []
        execution_records = execution_records or []

        # 分析可用定位器
        locator_stats = self._analyze_locators(elements)
        result.locator_priority = self._get_locator_priority(locator_stats)

        # 计算各策略得分
        scores = {
            Strategy.DOM: self._score_dom(locator_stats, elements),
            Strategy.VISION: self._score_vision(image_paths),
            Strategy.OCR: self._score_ocr(elements, locator_stats),
            Strategy.DB: self._score_db(history_scripts, execution_records),
            Strategy.PLAYWRIGHT: self._score_playwright(has_url),
            Strategy.GRAPH: self._score_graph(graph_business_flow),
        }

        # 选择主策略（得分最高的）
        sorted_strategies = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        result.primary = sorted_strategies[0][0]
        result.confidence = sorted_strategies[0][1]

        # 选择辅助策略（得分 > 0.3 且不是主策略）
        result.secondary = [
            s for s, score in sorted_strategies[1:]
            if score > 0.3 and s != result.primary
        ][:2]

        # 构建降级链
        result.degradation_chain = self._build_degradation_chain(
            result.primary, result.secondary, scores
        )

        # 生成选择原因
        result.reason = self._generate_reason(result, scores, locator_stats)

        log.info(
            f"StrategyAgent选择策略: primary={result.primary.value}, "
            f"secondary={[s.value for s in result.secondary]}, "
            f"confidence={result.confidence:.2f}, "
            f"reason={result.reason[:50]}"
        )

        return result

    def _analyze_locators(self, elements: List[Dict]) -> Dict[str, int]:
        """分析元素中各类定位器的数量"""
        stats = {k: 0 for k in self.LOCATOR_PRIORITY}
        for elem in elements:
            for loc_type in self.LOCATOR_PRIORITY:
                val = elem.get(loc_type, "")
                if not val and loc_type == "css_selector":
                    val = elem.get("css", "")
                if not val and loc_type == "xpath":
                    val = elem.get("xpath", "")
                if val:
                    stats[loc_type] += 1
        return stats

    def _get_locator_priority(self, locator_stats: Dict[str, int]) -> List[str]:
        """获取实际可用的定位器优先级列表"""
        available = [k for k in self.LOCATOR_PRIORITY if locator_stats.get(k, 0) > 0]
        return available if available else ["text"]

    def _score_dom(self, locator_stats: Dict[str, int], elements: List[Dict]) -> float:
        """DOM策略得分：有CSS/XPath/id等定位器时得分高"""
        if not elements:
            return 0.1

        stable_locators = locator_stats.get("data-testid", 0) + locator_stats.get("data-test", 0)
        id_locators = locator_stats.get("id", 0)
        name_locators = locator_stats.get("name", 0)
        css_locators = locator_stats.get("css_selector", 0)
        xpath_locators = locator_stats.get("xpath", 0)

        total_elements = len(elements)
        score = 0.0

        # 稳定定位器（data-testid）加分最多
        if stable_locators > 0:
            score += min(stable_locators / total_elements, 1.0) * 0.4
        if id_locators > 0:
            score += min(id_locators / total_elements, 1.0) * 0.3
        if name_locators > 0:
            score += min(name_locators / total_elements, 1.0) * 0.2
        if css_locators > 0:
            score += min(css_locators / total_elements, 1.0) * 0.15
        if xpath_locators > 0:
            score += min(xpath_locators / total_elements, 1.0) * 0.1

        # 基础分：有元素就有一定信心
        score += min(total_elements / 10, 1.0) * 0.2

        return min(score, 1.0)

    def _score_vision(self, image_paths: List[str]) -> float:
        """VISION策略得分：有截图时可用"""
        if not image_paths:
            return 0.0
        # 有截图时VISION得分应该高于默认PLAYWRIGHT
        return min(0.3 + len(image_paths) * 0.2, 0.9)

    def _score_ocr(self, elements: List[Dict], locator_stats: Dict[str, int]) -> float:
        """OCR策略得分：无定位器但有文字描述时"""
        text_elements = sum(1 for e in elements if e.get("text", ""))
        has_stable_locators = any(locator_stats.get(k, 0) > 0 for k in ["data-testid", "id", "css_selector", "xpath"])

        if has_stable_locators:
            return 0.1  # 有更好的定位器时OCR得分低
        if text_elements > 0:
            return min(text_elements / 5, 1.0) * 0.5
        return 0.0

    def _score_db(self, history_scripts: List[Dict], execution_records: List[Dict]) -> float:
        """DB策略得分：有历史脚本和执行记录时"""
        score = 0.0
        if history_scripts:
            score += min(len(history_scripts) * 0.2, 0.5)
            # 有成功执行记录的脚本更可信
            success_scripts = sum(1 for s in history_scripts if s.get("execution_success", False))
            if success_scripts:
                score += 0.2
        if execution_records:
            success_rate = sum(1 for r in execution_records if r.get("status") == "success") / max(len(execution_records), 1)
            score += success_rate * 0.3
        return min(score, 0.8)

    def _score_playwright(self, has_url: bool) -> float:
        """PLAYWRIGHT策略得分：默认策略，有URL时基础分"""
        return 0.5 if has_url else 0.3

    def _score_graph(self, graph_business_flow: List[Dict]) -> float:
        """GRAPH策略得分：有业务流时对多页面测试很有价值"""
        if not graph_business_flow:
            return 0.0
        flow_count = len(graph_business_flow)
        # 有导航关系的业务流得分更高
        nav_count = sum(1 for f in graph_business_flow if f.get("navigation_targets"))
        score = 0.3 + min(flow_count * 0.15, 0.3) + min(nav_count * 0.1, 0.3)
        return min(score, 0.9)

    def _build_degradation_chain(
        self, primary: Strategy, secondary: List[Strategy], scores: Dict[Strategy, float]
    ) -> List[Strategy]:
        """构建降级链：主策略失败后的备选策略"""
        chain = [primary]

        # DOM失败 → 降级到VISION或OCR
        if primary == Strategy.DOM:
            if Strategy.VISION in secondary:
                chain.append(Strategy.VISION)
            if Strategy.OCR in secondary:
                chain.append(Strategy.OCR)
            chain.append(Strategy.PLAYWRIGHT)

        # VISION失败 → 降级到OCR → PLAYWRIGHT
        elif primary == Strategy.VISION:
            if Strategy.OCR in secondary:
                chain.append(Strategy.OCR)
            if Strategy.DOM in secondary:
                chain.append(Strategy.DOM)
            chain.append(Strategy.PLAYWRIGHT)

        # GRAPH失败 → 降级到DOM → PLAYWRIGHT
        elif primary == Strategy.GRAPH:
            if Strategy.DOM in secondary:
                chain.append(Strategy.DOM)
            chain.append(Strategy.PLAYWRIGHT)

        # 其他策略失败 → 降级到PLAYWRIGHT
        else:
            chain.append(Strategy.PLAYWRIGHT)

        return chain

    def _generate_reason(
        self, result: StrategyResult, scores: Dict[Strategy, float], locator_stats: Dict[str, int]
    ) -> str:
        """生成策略选择原因"""
        reasons = []

        if result.primary == Strategy.DOM:
            stable = locator_stats.get("data-testid", 0) + locator_stats.get("id", 0)
            css = locator_stats.get("css_selector", 0)
            xpath = locator_stats.get("xpath", 0)
            reasons.append(f"检测到{stable}个稳定定位器、{css}个CSS选择器、{xpath}个XPath")
            reasons.append("DOM策略优先使用稳定定位器，脚本可靠性最高")
        elif result.primary == Strategy.VISION:
            reasons.append("检测到UI截图，使用Vision模式进行视觉定位")
        elif result.primary == Strategy.GRAPH:
            reasons.append("检测到Graph业务流，使用图推理路径进行多页面测试")
        elif result.primary == Strategy.DB:
            reasons.append("检测到历史成功脚本，基于已有脚本逻辑复用")
        elif result.primary == Strategy.OCR:
            reasons.append("无稳定定位器但有文字描述，使用OCR文字识别定位")
        else:
            reasons.append("使用标准Playwright脚本生成策略")

        if result.degradation_chain:
            chain_str = " → ".join(s.value.upper() for s in result.degradation_chain)
            reasons.append(f"降级链: {chain_str}")

        return "；".join(reasons)
