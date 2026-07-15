"""
CasePrompt - 测试用例生成Prompt模板

职责：根据需求解析结果 + RAG召回的元素/用例，生成标准测试用例
"""
from typing import List, Dict, Any


class CasePrompt:
    """测试用例生成提示词模板"""

    SYSTEM_PROMPT = """你是一个专业的测试用例设计师，擅长根据需求和页面元素生成详细的测试用例。你需要：
1. 结合RAG召回的历史用例和元素信息
2. 生成可执行的、步骤清晰的测试用例
3. 为每个步骤指定合理的操作类型和定位器
4. 包含充分的断言验证"""

    @staticmethod
    def build_elements_context(elements: List[Dict[str, Any]]) -> str:
        """构建RAG召回元素的上下文信息"""
        if not elements:
            return "（暂无相关页面元素信息）"

        lines = []
        for i, elem in enumerate(elements[:15], 1):
            name = elem.get("element_name", "")
            etype = elem.get("element_type", "")
            locator = elem.get("locator", "")
            xpath = elem.get("xpath", "")
            css_selector = elem.get("css_selector", "")
            page = elem.get("page_name", "")
            score = elem.get("score", 0)
            lines.append(
                f"{i}. 元素: {name} | 类型: {etype} | 定位器: {locator} | "
                f"XPath: {xpath} | CSS: {css_selector} | 页面: {page} | 相似度: {score}"
            )

        return "\n".join(lines)

    @staticmethod
    def build_cases_context(cases: List[Dict[str, Any]]) -> str:
        """构建RAG召回历史用例的上下文信息"""
        if not cases:
            return "（暂无相关历史用例）"

        lines = []
        for i, case in enumerate(cases[:5], 1):
            name = case.get("case_name", "")
            desc = case.get("description", "")
            steps = case.get("steps", [])
            score = case.get("score", 0)
            steps_str = ""
            if steps:
                if isinstance(steps, list):
                    step_descs = []
                    for s in steps[:5]:
                        if isinstance(s, dict):
                            step_descs.append(s.get("step", s.get("description", "")))
                        else:
                            step_descs.append(str(s))
                    steps_str = " → ".join(step_descs)
                else:
                    steps_str = str(steps)[:200]
            lines.append(f"{i}. 用例: {name} | 描述: {desc} | 步骤: {steps_str} | 相似度: {score}")

        return "\n".join(lines)

    @staticmethod
    def build_graph_context(graph_elements: List[Dict[str, Any]], graph_business_flow: List[Dict[str, Any]]) -> str:
        """构建Graph推理结果的上下文信息"""
        if not graph_elements and not graph_business_flow:
            return "（暂无Graph推理结果）"

        lines = []
        if graph_elements:
            lines.append("=== Graph推理页面元素 ===")
            for i, elem in enumerate(graph_elements[:15], 1):
                name = elem.get("name", "")
                etype = elem.get("type", "")
                locator = elem.get("locator", "")
                xpath = elem.get("xpath", "")
                css_selector = elem.get("css_selector", "")
                page_title = elem.get("page_title", "")
                lines.append(
                    f"{i}. 元素: {name} | 类型: {etype} | 定位器: {locator} | "
                    f"XPath: {xpath} | CSS: {css_selector} | 页面: {page_title}"
                )

        if graph_business_flow:
            lines.append("\n=== Graph推理业务流 ===")
            for i, flow in enumerate(graph_business_flow[:5], 1):
                page_title = flow.get("page_title", "")
                page_url = flow.get("page_url", "")
                flow_elements = flow.get("elements", [])
                nav_targets = flow.get("navigation_targets", [])
                lines.append(f"{i}. 页面: {page_title} ({page_url})")
                if flow_elements:
                    elem_names = [e.get("name", "") for e in flow_elements[:10] if e.get("name")]
                    lines.append(f"   操作元素: {' → '.join(elem_names)}")
                if nav_targets:
                    for nt in nav_targets[:3]:
                        lines.append(f"   导航: 点击[{nt.get('trigger_element', '')}] → {nt.get('target_page_title', '')}")

        return "\n".join(lines)

    @staticmethod
    def build(
        requirement: str,
        intent: str,
        steps: List[str],
        elements: List[Dict[str, Any]],
        cases: List[Dict[str, Any]] = None,
        graph_elements: List[Dict[str, Any]] = None,
        graph_business_flow: List[Dict[str, Any]] = None,
    ) -> str:
        """
        构建用例生成的提示词

        Args:
            requirement: 原始需求
            intent: 需求意图
            steps: 需求拆解的步骤
            elements: RAG召回的页面元素
            cases: RAG召回的历史用例

        Returns:
            完整的提示词
        """
        elements_ctx = CasePrompt.build_elements_context(elements)
        cases_ctx = CasePrompt.build_cases_context(cases or [])
        graph_ctx = CasePrompt.build_graph_context(graph_elements or [], graph_business_flow or [])
        steps_str = "\n".join(f"- {s}" for s in steps)

        return f"""请根据以下信息生成详细的测试用例。

需求：{requirement}
意图：{intent}
测试步骤：
{steps_str}

相关页面元素（来自RAG检索）：
{elements_ctx}

历史相似用例（来自RAG检索，可参考其步骤和断言设计）：
{cases_ctx}

Graph推理结果（来自图数据库的页面路径和业务流）：
{graph_ctx}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "case_name": "用例名称",
    "description": "用例描述",
    "preconditions": ["前置条件1", "前置条件2"],
    "steps": [
        {{
            "step": "步骤描述",
            "action": "操作类型（goto/fill/click/verify_visible/verify_text/select_option/wait）",
            "locator": "定位器（优先从上面元素中选取，优先使用CSS选择器或XPath）",
            "value": "操作值",
            "description": "步骤说明"
        }}
    ],
    "assertions": [
        {{
            "type": "断言类型（visible/text/url/title）",
            "locator": "定位器",
            "expected": "期望值",
            "description": "断言说明"
        }}
    ]
}}

要求：
1. steps要覆盖完整的测试流程
2. 优先使用上面提供的页面元素和定位器，特别是CSS选择器和XPath
3. 如果没有合适的定位器，locator字段留空，后续会由脚本生成器处理
4. 参考历史相似用例的步骤设计，但不要照搬
5. action类型只能是: goto, fill, click, verify_visible, verify_text, select_option, wait
6. assertions至少包含1个验证步骤
7. 只输出JSON，不要输出其他内容"""
