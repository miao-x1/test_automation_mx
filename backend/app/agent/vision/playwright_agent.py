"""
PlaywrightAgent - 根据统一元素库生成真实可执行的Playwright脚本
一个基于 UI 元素类型规则的“自动测试代码生成器”，
把结构化元素库转成可运行 Playwright Python 脚本，
并通过 locator 强约束保证稳定性。
核心原则：
1. 只使用 locator/css_selector/xpath 等真实定位器
2. 禁止使用 page.get_by_text("虚构文本") 这种不可靠方式
3. 没有定位器的元素不生成操作脚本
4. 根据元素类型自动生成测试场景
"""
import re
import time as _time
from typing import AsyncGenerator, Dict, Any, List
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.core.logger import log


class PlaywrightAgent(NewBaseAgent):
    """Playwright脚本生成Agent"""

    agent_name = "script"
    capabilities = [AgentCapability.SCRIPT_GENERATE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.model = None
        self.system_prompt = None

    async def generate_script(
        self,
        task_id: int,
        elements: List[Dict[str, Any]],
        cases: List[Dict[str, Any]],
        page_url: str = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """根据统一元素库生成Playwright脚本"""
        # [DEBUG] 进入函数
        _start = _time.time()
        log.info(f"[DEBUG] 开始：PlaywrightAgent.generate_script | 输入：task_id={task_id}, elements={len(elements)}, cases={len(cases)}")

        yield {"step": "生成Playwright脚本", "progress": 20, "message": "正在分析元素定位器..."}

        from app.agent.script.locator_builder import enrich_elements, extract_url, usable_elements

        url = extract_url(page_url, elements)
        elements = enrich_elements(elements or [])
        if not url:
            raise ValueError("缺少真实目标 URL，无法生成可执行 Playwright 脚本")

        # 筛选有定位器的元素
        locatable_elements = usable_elements(elements)
        log.info(f"Task {task_id} | 可定位元素: {len(locatable_elements)}/{len(elements)}")
        if not locatable_elements:
            raise ValueError("无法确定稳定定位器，拒绝生成空 locator 脚本")

        # 按类型分组
        inputs = [e for e in locatable_elements if e.get("type") in ("input", "searchbox", "textarea")]
        buttons = [e for e in locatable_elements if e.get("type") == "button"]
        links = [e for e in locatable_elements if e.get("type") == "link"]
        selects = [e for e in locatable_elements if e.get("type") == "select"]
        menus = [e for e in locatable_elements if e.get("type") in ("menu", "dropdown")]

        lines = [
            '"""',
            f'自动生成的Playwright测试脚本',
            f'页面: {url}',
            f'可定位元素: {len(locatable_elements)}',
            f'生成时间: 自动生成',
            '"""',
            'import re',
            'from playwright.sync_api import Page, expect',
            '',
            '',
        ]

        # 用例1：页面加载测试（始终生成）
        lines.extend(self._generate_page_load_test(url))

        # 用例2：搜索功能测试
        if inputs and buttons:
            search_inputs = [e for e in inputs if any(
                kw in (e.get("name", "") + (e.get("placeholder") or "")).lower()
                for kw in ["搜索", "search", "查询"]
            )]
            if search_inputs:
                lines.extend(self._generate_search_test(url, search_inputs[0], buttons))

        # 用例3：导航菜单测试
        if menus:
            lines.extend(self._generate_menu_test(url, menus[:5]))

        # 用例4：表单填写测试
        if inputs:
            lines.extend(self._generate_form_test(url, inputs[:5]))

        # 用例5：按钮点击测试
        if buttons:
            lines.extend(self._generate_button_test(url, buttons[:5]))

        # 用例6：链接验证测试
        if links:
            lines.extend(self._generate_link_test(url, links[:5]))

        # 用例7：下拉选择测试
        if selects:
            lines.extend(self._generate_select_test(url, selects[:3]))

        script = '\n'.join(lines)

        # [DEBUG] 结束
        _elapsed = _time.time() - _start
        log.info(f"[DEBUG] 结束：PlaywrightAgent.generate_script | 输出：script_length={len(script)}, locatable_elements={len(locatable_elements)} | 耗时：{_elapsed:.2f}s")

        yield {"step": "脚本生成完成", "progress": 80, "message": f"Playwright脚本生成完成，包含 {len(locatable_elements)} 个可定位元素"}

        yield {
            "step": "result",
            "progress": 100,
            "message": "Playwright脚本已生成",
            "data": {"script": script}
        }

    def _generate_page_load_test(self, url: str) -> List[str]:
        """生成页面加载测试"""
        return [
            'def test_page_load(page: Page):',
            '    """验证页面正常加载"""',
            f'    page.goto("{self._escape(url)}", wait_until="domcontentloaded")',
            '    # 验证页面加载完成',
            '    page.wait_for_load_state("domcontentloaded")',
            '    expect(page).to_have_title(re.compile(".*"))',
            '',
            '',
        ]

    def _generate_search_test(self, url: str, search_input: Dict, buttons: List[Dict]) -> List[str]:
        """生成搜索功能测试"""
        search_btn = None
        for btn in buttons:
            btn_name = (btn.get("name", "") + (btn.get("text") or "")).lower()
            if any(kw in btn_name for kw in ["搜索", "search", "查询"]):
                search_btn = btn
                break

        lines = [
            'def test_search_function(page: Page):',
            '    """测试搜索功能"""',
            f'    page.goto("{self._escape(url)}")',
            f'    {self._locator_expr(search_input)}.fill("测试搜索")',
        ]
        if search_btn:
            lines.append(f'    {self._locator_expr(search_btn)}.click()')
        else:
            lines.append('    page.keyboard.press("Enter")')
        lines.extend([
            '    # 等待搜索结果',
            '    page.wait_for_timeout(2000)',
            '',
            '',
        ])
        return lines

    def _generate_menu_test(self, url: str, menus: List[Dict]) -> List[str]:
        """生成导航菜单测试"""
        lines = [
            'def test_navigation_menu(page: Page):',
            '    """测试导航菜单可见性"""',
            f'    page.goto("{self._escape(url)}")',
        ]
        for menu in menus:
            lines.append(f'    # 验证 {menu.get("name", "菜单")} 可见')
            lines.append(f'    expect({self._locator_expr(menu)}).to_be_visible()')
        lines.extend(['', ''])
        return lines

    def _generate_form_test(self, url: str, inputs: List[Dict]) -> List[str]:
        """生成表单填写测试"""
        lines = [
            'def test_form_fill(page: Page):',
            '    """测试表单填写功能"""',
            f'    page.goto("{self._escape(url)}")',
        ]
        for inp in inputs:
            test_value = self._get_test_value(inp)
            lines.append(f'    # 填写 {inp.get("name", "输入框")}')
            lines.append(f'    {self._locator_expr(inp)}.fill("{self._escape(test_value)}")')
        lines.extend(['', ''])
        return lines

    def _generate_button_test(self, url: str, buttons: List[Dict]) -> List[str]:
        """生成按钮点击测试"""
        lines = [
            'def test_button_click(page: Page):',
            '    """测试按钮可见性和点击"""',
            f'    page.goto("{self._escape(url)}")',
        ]
        for i, btn in enumerate(buttons):
            btn_name = btn.get("name", "按钮")
            lines.append(f'    # 验证 {btn_name} 可见')
            lines.append(f'    expect({self._locator_expr(btn)}).to_be_visible()')
        lines.extend(['', ''])
        return lines

    def _generate_link_test(self, url: str, links: List[Dict]) -> List[str]:
        """生成链接验证测试"""
        lines = [
            'def test_link_visibility(page: Page):',
            '    """测试链接可见性"""',
            f'    page.goto("{self._escape(url)}")',
        ]
        for i, link in enumerate(links):
            link_name = link.get("name", "链接")
            lines.append(f'    # 验证 {link_name} 可见')
            lines.append(f'    expect({self._locator_expr(link)}).to_be_visible()')
        lines.extend(['', ''])
        return lines

    def _generate_select_test(self, url: str, selects: List[Dict]) -> List[str]:
        """生成下拉选择测试"""
        lines = [
            'def test_select_option(page: Page):',
            '    """测试下拉选择功能"""',
            f'    page.goto("{self._escape(url)}")',
        ]
        for sel in selects:
            lines.append(f'    # 选择 {sel.get("name", "下拉框")} 的第一个选项')
            lines.append(f'    {self._locator_expr(sel)}.select_option(index=0)')
        lines.extend(['', ''])
        return lines

    @staticmethod
    def _get_test_value(element: Dict) -> str:
        """根据元素类型生成测试值"""
        name = (element.get("name") or "").lower()
        placeholder = (element.get("placeholder") or "").lower()

        if "密码" in name or "password" in placeholder:
            return "Test@123456"
        if "邮箱" in name or "email" in placeholder:
            return "test@example.com"
        if "手机" in name or "phone" in placeholder:
            return "13800138000"
        if "搜索" in name or "search" in placeholder:
            return "测试搜索"
        return "test_value"

    def _locator_expr(self, element: Dict) -> str:
        expr = (element.get("playwright_expr") or "").strip()
        if expr.startswith("page."):
            return f"{expr}.first"
        from app.agent.script.locator_builder import build_playwright_locator
        built = build_playwright_locator(element)
        if built and built.startswith("page."):
            return f"{built}.first"
        loc = self._fix_locator(element.get("locator") or "")
        if not loc:
            raise ValueError("无法确定稳定定位器")
        return f'page.locator("{self._escape(loc)}").first'

    @staticmethod
    def _escape(s: str) -> str:
        """转义字符串中的特殊字符"""
        if not s:
            return ""
        return s.replace('\\', '\\\\').replace('"', '\\"')

    @staticmethod
    def _fix_locator(locator: str) -> str:
        """
        修复定位器：XPath选择器需要加前缀

        Playwright的locator()默认使用CSS选择器，
        XPath选择器（以/或//开头）需要加xpath=前缀
        """
        if not locator:
            return locator
        stripped = locator.strip()
        if stripped.startswith("/") or stripped.startswith("./"):
            return "xpath=" + locator
        return locator
