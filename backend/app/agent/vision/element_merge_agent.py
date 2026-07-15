"""
ElementMergeAgent - 融合Vision元素与DOM元素

输入：
  - Vision识别结果（语义描述 + 可交互标记）
  - DOM抓取结果（定位信息 + locator）

输出：
  - 统一元素库（语义 + 定位 = 可靠的测试元素）

融合策略：
  1. 类型必须匹配（强制条件）
  2. 文本相似度匹配
  3. 属性辅助匹配（name/aria-label/placeholder）
  4. 匹配阈值：50分以上才允许融合
"""
from typing import AsyncGenerator, Dict, Any, List
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.core.logger import log


class ElementMergeAgent(NewBaseAgent):
    """元素融合Agent"""

    agent_name = "merge"
    capabilities = [AgentCapability.MERGE]

    # Vision类型到DOM标签的映射
    TYPE_TAG_MAP = {
        "button": {"button", "input", "[role=button]"},
        "input": {"input", "textarea"},
        "searchbox": {"input", "[role=search]"},
        "textarea": {"textarea"},
        "checkbox": {"input"},
        "radio": {"input"},
        "select": {"select"},
        "dropdown": {"select", "[role=listbox]"},
        "menu": {"nav", "ul", "ol", "li", "[role=menu]", "[role=menubar]", "[role=navigation]"},
        "tab": {"[role=tab]"},
        "link": {"a", "[role=link]"},
        "form": {"form"},
        "dialog": {"[role=dialog]", "[role=alertdialog]"},
        "modal": {"[role=dialog]"},
        "popup": {"[role=tooltip]", "[role=popup]"},
        "pagination": {"nav", "[role=navigation]"},
        "table": {"table"},
        "img": {"img"},
    }

    # 匹配阈值：低于此分数不融合
    MERGE_THRESHOLD = 50

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def merge_elements(
        self,
        task_id: int,
        vision_elements: List[Dict[str, Any]],
        dom_elements: List[Dict[str, Any]]
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """融合Vision和DOM元素"""
        yield {
            "step": "开始融合元素",
            "progress": 10,
            "message": f"开始融合 {len(vision_elements)} 个Vision元素和 {len(dom_elements)} 个DOM元素"
        }

        merged = []
        matched_dom_indices = set()

        # 步骤1：为每个Vision元素找DOM匹配
        yield {"step": "文本匹配", "progress": 30, "message": "正在进行文本+类型匹配..."}

        for v_el in vision_elements:
            best_match = self._find_best_match(v_el, dom_elements, matched_dom_indices)
            if best_match is not None:
                matched_dom_indices.add(best_match)
                dom_el = dom_elements[best_match]
                merged.append(self._create_merged_element(v_el, dom_el))
                log.info(f"Task {task_id} | 融合匹配: Vision[{v_el.get('name')}] <-> DOM[{dom_el.get('element_text') or dom_el.get('tag_name')}]")
            else:
                merged.append(self._create_vision_element(v_el))

        # 步骤2：添加未匹配的DOM元素
        yield {"step": "补充DOM元素", "progress": 60, "message": "补充未匹配的DOM元素..."}

        for i, dom_el in enumerate(dom_elements):
            if i not in matched_dom_indices:
                merged.append(self._create_dom_element(dom_el))

        # 统计
        merge_count = len([e for e in merged if e["source"] == "merge"])
        vision_only = len([e for e in merged if e["source"] == "vision"])
        dom_only = len([e for e in merged if e["source"] == "dom"])

        log.info(
            f"Task {task_id} | 融合完成: merge={merge_count}, vision={vision_only}, dom={dom_only}, total={len(merged)}"
        )

        yield {
            "step": "融合完成",
            "progress": 90,
            "message": f"融合完成：{merge_count}个融合, {vision_only}个纯Vision, {dom_only}个纯DOM"
        }

        yield {
            "step": "result",
            "progress": 100,
            "message": "元素融合结果已生成",
            "data": {
                "elements": merged,
                "merge_count": merge_count,
                "vision_only_count": vision_only,
                "dom_only_count": dom_only,
                "total_count": len(merged)
            }
        }

    def _find_best_match(self, vision_el: Dict, dom_elements: List[Dict], matched: set) -> int | None:
        """为Vision元素找到最佳DOM匹配"""
        v_text = (vision_el.get("text") or "").strip().lower()
        v_name = (vision_el.get("name") or "").strip().lower()
        v_type = vision_el.get("type", "")

        best_idx = None
        best_score = 0

        for i, dom_el in enumerate(dom_elements):
            if i in matched:
                continue

            score = 0

            # 类型匹配（强制条件，权重最高）
            type_match = self._type_matches(v_type, dom_el)
            if type_match:
                score += 40
            else:
                # 类型不匹配，大幅降分
                score -= 30

            # 文本匹配
            d_text = (dom_el.get("element_text") or "").strip().lower()
            text_score = self._text_similarity(v_text or v_name, d_text)
            score += text_score

            # name属性匹配
            d_name = (dom_el.get("element_name") or "").lower()
            if v_text and d_name:
                name_score = self._text_similarity(v_text, d_name)
                score += name_score * 0.5

            # aria-label匹配
            d_aria = (dom_el.get("aria_label") or "").lower()
            if v_text and d_aria:
                aria_score = self._text_similarity(v_text, d_aria)
                score += aria_score * 0.6

            # placeholder匹配
            d_placeholder = (dom_el.get("placeholder") or "").lower()
            if v_text and d_placeholder:
                ph_score = self._text_similarity(v_text, d_placeholder)
                score += ph_score * 0.4

            # 优先匹配有定位器的DOM元素
            if dom_el.get("locator"):
                score += 5

            if score > best_score and score >= self.MERGE_THRESHOLD:
                best_score = score
                best_idx = i

        return best_idx

    def _text_similarity(self, text1: str, text2: str) -> float:
        """
        计算两个文本的相似度分数（0-40分）
        - 精确匹配：40分
        - 包含匹配：25分
        - 关键词重叠：按比例得分
        """
        if not text1 or not text2:
            return 0

        # 去除常见后缀词
        suffixes = ["按钮", "输入框", "链接", "文本框", "下拉框", "复选框", "选项卡"]
        clean1 = text1
        clean2 = text2
        for s in suffixes:
            clean1 = clean1.replace(s, "")
            clean2 = clean2.replace(s, "")

        # 精确匹配
        if clean1 == clean2:
            return 40

        # 包含匹配
        if clean1 in clean2 or clean2 in clean1:
            return 25

        # 关键词重叠
        keywords1 = set(clean1.split()) | set(text1.replace("按钮", "").replace("输入框", "").split())
        keywords2 = set(clean2.split())
        common = keywords1 & keywords2
        if common:
            ratio = len(common) / max(len(keywords1), len(keywords2), 1)
            return ratio * 20

        return 0

    def _type_matches(self, vision_type: str, dom_el: Dict) -> bool:
        """检查Vision类型与DOM元素是否匹配"""
        tag = dom_el.get("tag_name", "")
        role = dom_el.get("role", "")

        matching_set = self.TYPE_TAG_MAP.get(vision_type, set())
        if not matching_set:
            return False

        for pattern in matching_set:
            if pattern.startswith("["):
                if "role=" in pattern:
                    expected_role = pattern.split("=")[1].rstrip("]")
                    if role == expected_role:
                        return True
            else:
                if tag == pattern:
                    return True

        return False

    def _create_merged_element(self, vision_el: Dict, dom_el: Dict) -> Dict[str, Any]:
        """创建融合元素"""
        v_confidence = (vision_el.get("confidence") or 50) / 100
        d_priority = dom_el.get("locator_priority", 50) / 100
        merge_confidence = min(0.5 * v_confidence + 0.5 * d_priority, 1.0)

        return {
            "name": vision_el.get("name") or dom_el.get("element_text") or dom_el.get("tag_name", ""),
            "type": self._normalize_type(vision_el.get("type", ""), dom_el.get("tag_name", "")),
            "text": vision_el.get("text") or dom_el.get("element_text"),
            "source": "merge",
            "locator": dom_el.get("locator") or self._best_locator(dom_el),
            "xpath": dom_el.get("xpath"),
            "css_selector": dom_el.get("css_selector"),
            "element_id": dom_el.get("element_id"),
            "element_class": dom_el.get("element_class"),
            "element_name": dom_el.get("element_name"),
            "placeholder": dom_el.get("placeholder"),
            "href": dom_el.get("href"),
            "aria_label": dom_el.get("aria_label"),
            "role": dom_el.get("role"),
            "data_testid": dom_el.get("data_testid"),
            "page_url": dom_el.get("page_url"),
            "confidence": round(merge_confidence, 2),
        }

    def _create_vision_element(self, vision_el: Dict) -> Dict[str, Any]:
        """创建纯Vision元素（无DOM匹配）"""
        return {
            "name": vision_el.get("name", ""),
            "type": vision_el.get("type", "unknown"),
            "text": vision_el.get("text"),
            "source": "vision",
            "locator": None,
            "xpath": None,
            "css_selector": None,
            "element_id": None,
            "element_class": None,
            "element_name": None,
            "placeholder": None,
            "href": None,
            "aria_label": None,
            "role": None,
            "data_testid": None,
            "page_url": None,
            "confidence": round((vision_el.get("confidence") or 50) / 100, 2),
        }

    def _create_dom_element(self, dom_el: Dict) -> Dict[str, Any]:
        """创建纯DOM元素（无Vision匹配）"""
        return {
            "name": dom_el.get("element_text") or dom_el.get("aria_label") or dom_el.get("element_name") or dom_el.get("tag_name", ""),
            "type": self._dom_tag_to_type(dom_el.get("tag_name", "")),
            "text": dom_el.get("element_text"),
            "source": "dom",
            "locator": dom_el.get("locator") or self._best_locator(dom_el),
            "xpath": dom_el.get("xpath"),
            "css_selector": dom_el.get("css_selector"),
            "element_id": dom_el.get("element_id"),
            "element_class": dom_el.get("element_class"),
            "element_name": dom_el.get("element_name"),
            "placeholder": dom_el.get("placeholder"),
            "href": dom_el.get("href"),
            "aria_label": dom_el.get("aria_label"),
            "role": dom_el.get("role"),
            "data_testid": dom_el.get("data_testid"),
            "page_url": dom_el.get("page_url"),
            "confidence": round((dom_el.get("locator_priority") or 50) / 100, 2),
        }

    @staticmethod
    def _best_locator(el: Dict) -> str | None:
        """选择最佳定位策略：id > data-testid > aria-label > role > name > css > xpath"""
        if el.get("element_id"):
            return f'#{el["element_id"]}'
        if el.get("data_testid"):
            return f'[data-testid="{el["data_testid"]}"]'
        if el.get("aria_label"):
            return f'[aria-label="{el["aria_label"]}"]'
        if el.get("role"):
            return f'[role="{el["role"]}"]'
        if el.get("element_name"):
            return f'[name="{el["element_name"]}"]'
        if el.get("placeholder"):
            return f'[placeholder="{el["placeholder"]}"]'
        if el.get("css_selector"):
            return el["css_selector"]
        if el.get("xpath"):
            return el["xpath"]
        return None

    @staticmethod
    def _normalize_type(vision_type: str, dom_tag: str) -> str:
        """统一元素类型"""
        valid_types = {"button", "input", "searchbox", "textarea", "checkbox", "radio",
                       "select", "dropdown", "menu", "tab", "link", "form", "dialog",
                       "modal", "popup", "pagination", "table", "img"}
        if vision_type in valid_types:
            return vision_type
        tag_map = {
            "button": "button", "input": "input", "textarea": "textarea",
            "select": "select", "a": "link", "img": "img",
            "form": "form", "table": "table",
        }
        return tag_map.get(dom_tag, dom_tag)

    @staticmethod
    def _dom_tag_to_type(tag: str) -> str:
        """DOM标签转类型"""
        tag_type_map = {
            "button": "button", "input": "input", "textarea": "textarea",
            "select": "select", "a": "link", "img": "img",
            "form": "form", "table": "table",
            "nav": "menu", "ul": "menu", "ol": "menu",
            "label": "text", "option": "option",
        }
        return tag_type_map.get(tag, tag)
