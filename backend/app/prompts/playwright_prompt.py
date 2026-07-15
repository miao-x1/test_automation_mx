"""
PlaywrightPrompt - Playwright脚本生成Prompt模板

职责：根据测试用例 + RAG召回的元素 + 历史脚本，生成可执行的Playwright脚本
"""
from typing import List, Dict, Any


class PlaywrightPrompt:
    """Playwright脚本生成提示词模板"""

    SYSTEM_PROMPT = """你是一个专业的Playwright测试脚本工程师，擅长根据测试用例和页面元素生成高质量的自动化测试脚本。你需要：
1. 优先使用提供的真实定位器（CSS选择器、XPath），禁止使用虚假定位器
2. 生成完整可执行的脚本
3. 添加适当的等待和错误处理
4. 参考历史脚本的代码风格和模式"""

    @staticmethod
    def build_elements_context(elements: List[Dict[str, Any]]) -> str:
        """构建RAG召回元素的上下文信息"""
        if not elements:
            return "（暂无相关页面元素信息）"

        lines = []
        for i, elem in enumerate(elements[:20], 1):
            name = elem.get("element_name", "")
            etype = elem.get("element_type", "")
            locator = elem.get("locator", "")
            xpath = elem.get("xpath", "")
            css_selector = elem.get("css_selector", "")
            page = elem.get("page_name", "")
            lines.append(
                f"{i}. {name} | 类型: {etype} | 定位器: {locator} | "
                f"XPath: {xpath} | CSS: {css_selector} | 页面: {page}"
            )

        return "\n".join(lines)

    @staticmethod
    def build_history_script_context(scripts: List[Dict[str, Any]]) -> str:
        """构建历史脚本的上下文信息"""
        if not scripts:
            return "（暂无相关历史脚本）"

        lines = []
        for i, script in enumerate(scripts[:2], 1):
            name = script.get("script_name", "")
            content = script.get("script_content", "")
            score = script.get("score", 0)
            # 截取脚本前500字符作为参考
            preview = content[:500] if content else ""
            lines.append(f"--- 历史脚本 {i}: {name} (相似度: {score}) ---\n{preview}\n---")

        return "\n\n".join(lines)

    @staticmethod
    def build_graph_flow_context(graph_business_flow: List[Dict[str, Any]]) -> str:
        """构建Graph推理业务流的上下文信息"""
        if not graph_business_flow:
            return "（暂无Graph推理业务流）"

        lines = []
        for i, flow in enumerate(graph_business_flow[:5], 1):
            page_title = flow.get("page_title", "")
            page_url = flow.get("page_url", "")
            flow_elements = flow.get("elements", [])
            nav_targets = flow.get("navigation_targets", [])
            lines.append(f"--- 业务流 {i}: 页面 {page_title} ({page_url}) ---")
            if flow_elements:
                for j, elem in enumerate(flow_elements[:10], 1):
                    ename = elem.get("name", "")
                    etype = elem.get("type", "")
                    elocator = elem.get("locator", "")
                    next_name = elem.get("next_name", "")
                    suffix = f" → {next_name}" if next_name else ""
                    lines.append(f"  {j}. {ename} ({etype}) locator={elocator}{suffix}")
            if nav_targets:
                for nt in nav_targets[:3]:
                    lines.append(f"  导航: 点击[{nt.get('trigger_element', '')}] → 跳转 {nt.get('target_page_title', '')} ({nt.get('target_page_url', '')})")

        return "\n".join(lines)

    @staticmethod
    def build(
        case_data: Dict[str, Any],
        elements: List[Dict[str, Any]],
        target_url: str = "",
        history_scripts: List[Dict[str, Any]] = None,
        graph_business_flow: List[Dict[str, Any]] = None,
        feedback_context: str = "",
    ) -> str:
        """
        构建Playwright脚本生成的提示词

        Args:
            case_data: 测试用例数据
            elements: RAG召回的页面元素
            target_url: 目标URL
            history_scripts: RAG召回的历史脚本
            graph_business_flow: Graph推理业务流
            feedback_context: 用户反馈上下文（用于指导重新生成）

        Returns:
            完整的提示词
        """
        import json

        elements_ctx = PlaywrightPrompt.build_elements_context(elements)
        history_ctx = PlaywrightPrompt.build_history_script_context(history_scripts or [])
        graph_flow_ctx = PlaywrightPrompt.build_graph_flow_context(graph_business_flow or [])

        case_name = case_data.get("case_name", "unnamed_test")
        description = case_data.get("description", "")
        steps = case_data.get("steps", [])
        assertions = case_data.get("assertions", [])
        preconditions = case_data.get("preconditions", [])

        steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
        assertions_json = json.dumps(assertions, ensure_ascii=False, indent=2)
        preconditions_str = "、".join(preconditions) if preconditions else "无"

        default_url = target_url if target_url else "https://TODO_REPLACE_WITH_REAL_URL"

        # 构建反馈上下文部分
        if feedback_context:
            feedback_section = f"""⚠️ 用户反馈与修复要求（这是重新生成，请优先修复以下问题）:
{feedback_context}"""
        else:
            feedback_section = ""

        return f"""请根据以下测试用例和页面元素信息，生成完整的Playwright Python测试脚本。

目标URL: {default_url}
用例名称: {case_name}
用例描述: {description}
前置条件: {preconditions_str}

测试步骤:
{steps_json}

断言:
{assertions_json}

相关页面元素（来自RAG检索，必须优先使用这些定位器）:
{elements_ctx}

历史相似脚本（可参考其代码风格和模式）:
{history_ctx}

Graph推理业务流（来自图数据库的页面路径和导航关系）:
{graph_flow_ctx}
{feedback_section}

请生成一个完整的Playwright测试脚本，要求：
1. 使用 playwright.sync_api，函数签名: def test_xxx(page: Page):
2. 脚本开头导入: import re 和 from playwright.sync_api import Page, expect
3. 必须优先使用上面提供的页面元素定位器（CSS选择器 > XPath > 其他）
4. 禁止使用 page.get_by_text("xxx") 这种虚假定位器，除非没有提供任何定位器
5. 如果有CSS选择器，使用 page.locator("css=xxx") 或 page.locator("xxx")
6. 如果有XPath，使用 page.locator("xpath=xxx")
7. 每个操作步骤都要有中文注释
8. 包含所有断言验证
9. 添加适当的等待（page.wait_for_load_state 或 wait_for_timeout）
10. 对于输入操作（如用户名密码），使用合理的测试数据
11. 参考历史脚本的代码风格，但不要照搬
12. 只输出Python脚本代码，不要输出其他内容
13. 不要用markdown代码块包裹，直接输出脚本内容
14. 禁止使用example.com作为URL，必须使用上面提供的目标URL；如果目标URL是TODO_REPLACE_WITH_REAL_URL，则在脚本中用注释标注"# TODO: 请替换为真实URL"
"""
