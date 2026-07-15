"""
FusionAgent - 多模态输入融合Agent

将TextParser/VisionParser/UrlParser/ScriptParser的解析结果
融合为统一的UnifiedRequirement，供后续流程使用

融合策略：
1. 意图对齐：多源意图取优先级最高的（script > vision > url > text）
2. 步骤合并：去重 + 排序（URL步骤优先，图片步骤补充）
3. 关键词聚合：多源关键词合并去重
4. 元素合并：图片识别的元素 + URL抓取的元素 + 脚本中的选择器
5. 生成统一需求文本
"""
import json
import re
from typing import Dict, Any, List, Optional
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class FusionAgent(NewBaseAgent):
    """多模态输入融合Agent"""

    agent_name = "fusion"
    display_name = "Fusion Agent"
    description = "多模态输入融合Agent - 将多路解析结果融合为统一需求"
    capabilities = [AgentCapability.DATA_FUSION]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    # 意图优先级：脚本复用 > 视觉识别 > URL推断 > 文本推断
    INTENT_PRIORITY = {
        "script_reuse": 4,
        "vision_test": 3,
        "ui_test": 3,
        "url_test": 2,
        "login_test": 2,
        "register_test": 2,
        "search_test": 2,
        "general_test": 1,
        "unknown_test": 0,
    }

    def fuse(self, parse_results: List[Dict], mode: str = "text") -> Dict[str, Any]:
        """
        融合多路解析结果为UnifiedRequirement

        Args:
            parse_results: 各Parser的解析结果列表
            mode: 输入模式

        Returns:
            UnifiedRequirement: {
                intent: str,
                summary: str,
                steps: list[str],
                keywords: list[str],
                target_url: str,
                elements: list[dict],
                unified_requirement: str,  # 融合后的统一需求文本
                sources: list[str],  # 使用了哪些来源
                confidence: float,  # 融合置信度
            }
        """
        if not parse_results:
            return {
                "intent": "unknown_test",
                "summary": "",
                "steps": [],
                "keywords": [],
                "target_url": "",
                "elements": [],
                "unified_requirement": "",
                "sources": [],
                "confidence": 0.0,
            }

        # 单一来源直接返回
        if len(parse_results) == 1:
            result = parse_results[0]
            unified_text = self._generate_unified_text(result)
            result["unified_requirement"] = unified_text
            result["sources"] = [result.get("source", "unknown")]
            result["confidence"] = 0.7 if result.get("success") else 0.3
            return result

        # 多源融合
        fused = self._multi_source_fuse(parse_results, mode)
        return fused

    def _multi_source_fuse(self, results: List[Dict], mode: str) -> Dict[str, Any]:
        """多源融合核心逻辑"""
        # 1. 意图对齐
        intent = self._align_intent(results)

        # 2. 摘要合并
        summary = self._merge_summaries(results)

        # 3. 步骤合并
        steps = self._merge_steps(results)

        # 4. 关键词聚合
        keywords = self._merge_keywords(results)

        # 5. URL合并
        target_url = self._merge_urls(results)

        # 6. 元素合并
        elements = self._merge_elements(results)

        # 7. 额外信息合并
        extra = self._merge_extras(results)

        # 8. 生成统一需求文本
        unified = {
            "intent": intent,
            "summary": summary,
            "steps": steps,
            "keywords": keywords,
            "target_url": target_url,
            "elements": elements,
            "extra": extra,
            "sources": [r.get("source", "unknown") for r in results],
            "success": True,
        }
        unified["unified_requirement"] = self._generate_unified_text(unified)
        unified["confidence"] = self._calculate_confidence(results)

        return unified

    def _align_intent(self, results: List[Dict]) -> str:
        """意图对齐：取优先级最高的意图"""
        best_intent = "unknown_test"
        best_priority = -1

        for r in results:
            intent = r.get("intent", "unknown_test")
            priority = self.INTENT_PRIORITY.get(intent, 0)
            if priority > best_priority:
                best_priority = priority
                best_intent = intent

        return best_intent

    def _merge_summaries(self, results: List[Dict]) -> str:
        """摘要合并：优先使用最详细的摘要"""
        summaries = [r.get("summary", "") for r in results if r.get("summary")]
        if not summaries:
            return ""
        # 选择最长的摘要作为基础，其他作为补充
        summaries.sort(key=len, reverse=True)
        return summaries[0]

    def _merge_steps(self, results: List[Dict]) -> List[str]:
        """步骤合并：去重 + 排序"""
        all_steps = []
        seen = set()

        # 优先使用URL/脚本中的步骤（更具体）
        priority_sources = ["url", "script", "vision"]
        for source in priority_sources:
            for r in results:
                if r.get("source") == source:
                    for step in r.get("steps", []):
                        step_key = re.sub(r'[\s\d]', '', step.lower())
                        if step_key not in seen:
                            all_steps.append(step)
                            seen.add(step_key)

        # 补充文本步骤
        for r in results:
            if r.get("source") == "text":
                for step in r.get("steps", []):
                    step_key = re.sub(r'[\s\d]', '', step.lower())
                    if step_key not in seen:
                        all_steps.append(step)
                        seen.add(step_key)

        return all_steps[:20]  # 限制步骤数量

    def _merge_keywords(self, results: List[Dict]) -> List[str]:
        """关键词聚合：合并去重"""
        all_keywords = []
        seen = set()
        for r in results:
            for kw in r.get("keywords", []):
                kw_lower = kw.lower()
                if kw_lower not in seen:
                    all_keywords.append(kw)
                    seen.add(kw_lower)
        return all_keywords[:15]

    def _merge_urls(self, results: List[Dict]) -> str:
        """URL合并：优先使用URL来源的URL"""
        # 优先级：url > script > vision > text
        for source in ["url", "script", "vision", "text"]:
            for r in results:
                if r.get("source") == source and r.get("target_url"):
                    return r["target_url"]
        return ""

    def _merge_elements(self, results: List[Dict]) -> List[Dict]:
        """元素合并：按名称去重"""
        all_elements = []
        seen_names = set()
        for r in results:
            for elem in r.get("elements", []):
                name = elem.get("name", "")
                if name and name not in seen_names:
                    all_elements.append(elem)
                    seen_names.add(name)
        return all_elements[:30]

    def _merge_extras(self, results: List[Dict]) -> Dict:
        """额外信息合并"""
        extra = {}
        for r in results:
            for k, v in r.get("extra", {}).items():
                if k not in extra:
                    extra[k] = v
        return extra

    def _generate_unified_text(self, result: Dict) -> str:
        """生成统一需求文本"""
        parts = []

        # 意图
        intent = result.get("intent", "")
        if intent and intent != "unknown_test":
            intent_label = intent.replace("_", " ").title()
            parts.append(f"测试目标: {intent_label}")

        # 摘要
        summary = result.get("summary", "")
        if summary:
            parts.append(f"需求概述: {summary}")

        # URL
        target_url = result.get("target_url", "")
        if target_url:
            parts.append(f"目标页面: {target_url}")

        # 步骤
        steps = result.get("steps", [])
        if steps:
            parts.append("测试步骤:")
            for i, step in enumerate(steps, 1):
                parts.append(f"  {i}. {step}")

        # 元素
        elements = result.get("elements", [])
        if elements:
            parts.append("涉及元素:")
            for elem in elements[:10]:
                name = elem.get("name", "")
                etype = elem.get("type", "")
                action = elem.get("action", "")
                parts.append(f"  - {name}({etype}): {action}")

        return "\n".join(parts)

    def _calculate_confidence(self, results: List[Dict]) -> float:
        """计算融合置信度"""
        if not results:
            return 0.0

        # 基础置信度：成功解析的来源越多越可信
        success_count = sum(1 for r in results if r.get("success"))
        base_confidence = min(success_count / len(results), 1.0)

        # 来源多样性加分
        sources = set(r.get("source", "") for r in results)
        diversity_bonus = min(len(sources) * 0.1, 0.3)

        # 有意图加分
        has_intent = any(r.get("intent", "unknown_test") != "unknown_test" for r in results)
        intent_bonus = 0.1 if has_intent else 0

        # 有URL加分
        has_url = any(r.get("target_url") for r in results)
        url_bonus = 0.1 if has_url else 0

        return min(base_confidence * 0.5 + diversity_bonus + intent_bonus + url_bonus, 1.0)
