"""
FlowScriptGenerator - 跨页面业务流Playwright脚本生成器

职责：根据FlowGraph生成跨页面的Playwright测试脚本

支持：
- 跨页面流转（自动处理页面跳转）
- 页面状态保存与恢复
- 变量传递（提取→注入）
- 等待策略（页面加载、元素可见、网络空闲）
- 错误处理与截图

输入：FlowGraph + RAG元素 + Graph推理结果
输出：可执行的Playwright Python脚本
"""
import json
from typing import Any, Dict, List, Optional
from app.agent.requirement.flow_parser import FlowGraph, PageNode, PageTransition
from app.agent.vision.page_state_manager import PageStateManager, VariableContext
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class FlowScriptGenerator(NewBaseAgent):
    """
    跨页面业务流Playwright脚本生成器

    生成流程：
    1. 初始化（browser, context, page, 状态字典, 变量字典）
    2. 遍历FlowGraph的页面序列
    3. 对每个页面：goto → 操作 → 提取变量 → 保存状态
    4. 页面跳转：触发跳转 → 等待新页面 → 恢复状态
    5. 断言验证
    6. 清理
    """

    agent_name = "flow_script_generator"
    display_name = "Flow Script Generator"
    description = "跨页面业务流Playwright脚本生成器"
    capabilities = [AgentCapability.FLOW_SCRIPT]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_name = "flow_script_generator"
        self.state_mgr = PageStateManager()
        self.var_ctx = VariableContext()

    def generate(
        self,
        flow_graph: FlowGraph,
        elements: List[Dict[str, Any]] = None,
        case_data: Dict[str, Any] = None,
        requirement: str = "",
    ) -> str:
        """
        生成跨页面Playwright脚本

        Args:
            flow_graph: 页面流转图
            elements: RAG召回的元素列表
            case_data: 用例数据
            requirement: 原始需求

        Returns:
            Playwright Python脚本
        """
        elements = elements or []
        case_data = case_data or {}

        log.info(
            f"FlowScriptGenerator | 开始生成 | "
            f"pages={len(flow_graph.pages)}, transitions={len(flow_graph.transitions)}"
        )

        # 构建元素映射（page_id -> elements）
        elem_map = self._build_element_map(elements)

        # 初始化变量上下文
        for var_name, var_value in flow_graph.variables.items():
            self.var_ctx.set_global(var_name, var_value)

        lines = []

        # 1. 文件头
        lines.extend(self._generate_header(flow_graph, requirement))

        # 2. 主测试函数
        lines.extend(self._generate_test_function_start(flow_graph))

        # 3. 遍历页面
        for i, page in enumerate(flow_graph.pages):
            transitions = flow_graph.get_transitions_from(page.page_id)

            # 页面注释
            lines.append(f'    # ===== 页面 {i + 1}/{len(flow_graph.pages)}: {page.title} =====')
            lines.append('')

            # 3.1 导航到页面
            lines.extend(self._generate_page_navigation(page, flow_graph, i))

            # 3.2 等待页面加载
            lines.extend(self._generate_page_wait(page))

            # 3.3 执行页面操作
            lines.extend(self._generate_page_actions(page, elem_map))

            # 3.4 提取变量
            extract_rules = self.var_ctx.get_extract_rules(page.page_id)
            if extract_rules:
                lines.extend(self._generate_variable_extractions(page, extract_rules))

            # 3.5 自动提取常见变量
            lines.extend(self._generate_auto_extractions(page, elem_map))

            # 3.6 保存页面状态
            lines.extend(self.state_mgr.generate_save_code(page.page_id, ["cookies", "local_storage", "url"]))
            lines.append('')

            # 3.7 页面跳转
            if transitions:
                transition = transitions[0]  # 取第一个跳转
                lines.extend(self._generate_page_transition(transition, flow_graph, elem_map))
                lines.append('')

        # 4. 最终断言
        lines.extend(self._generate_final_assertions(flow_graph, case_data))

        # 5. 截图
        lines.extend(self._generate_screenshot())

        # 6. 函数结尾
        lines.extend([
            '',
            '    print("业务流测试完成")',
            '',
        ])

        script = '\n'.join(lines)

        log.info(f"FlowScriptGenerator | 生成完成 | script_length={len(script)}")

        return script

    def _build_element_map(self, elements: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """构建 page_id -> elements 映射"""
        elem_map: Dict[str, List[Dict[str, Any]]] = {}
        for elem in elements:
            page_id = elem.get("page_id", "unknown")
            if page_id not in elem_map:
                elem_map[page_id] = []
            elem_map[page_id].append(elem)
        return elem_map

    def _generate_header(self, flow_graph: FlowGraph, requirement: str) -> List[str]:
        """生成文件头"""
        page_titles = " → ".join(p.title for p in flow_graph.pages)
        return [
            '"""',
            f'跨页面业务流自动测试脚本',
            f'需求: {requirement[:100]}',
            f'页面流: {page_titles}',
            f'页面数: {len(flow_graph.pages)}',
            f'跳转数: {len(flow_graph.transitions)}',
            '',
            f'支持: 跨页面流转 | 页面状态保存 | 变量传递',
            '"""',
            'import re',
            'from playwright.sync_api import Page, BrowserContext, expect',
            '',
            '',
        ]

    def _generate_test_function_start(self, flow_graph: FlowGraph) -> List[str]:
        """生成测试函数开头"""
        lines = [
            'def test_business_flow(page: Page):',
            '    """跨页面业务流测试"""',
            '    context = page.context',
            '',
            '    # 状态字典（跨页面保存）',
            '    _state = {}',
            '',
            '    # 变量字典（跨页面传递）',
            '    _vars = {',
        ]

        # 初始化全局变量
        for var_name, var_value in flow_graph.variables.items():
            default_val = var_value.replace("${", "").replace("}", "")
            lines.append(f'        "{var_name}": "{default_val}",')

        lines.extend([
            '    }',
            '',
        ])

        return lines

    def _generate_page_navigation(self, page: PageNode, flow_graph: FlowGraph, page_index: int) -> List[str]:
        """生成页面导航代码"""
        lines = []

        if page_index == 0:
            # 第一个页面：直接goto
            url = page.url or flow_graph.entry_url or ""
            if not url or "TODO_REPLACE" in url:
                raise ValueError("缺少真实目标 URL，无法生成跨页面脚本")
            lines.append(f'    # 导航到首页: {page.title}')
            lines.append(f'    page.goto("{self._escape(url)}", wait_until="domcontentloaded")')
        else:
            # 后续页面：通过点击/跳转到达
            lines.append(f'    # 页面跳转到达: {page.title}')
            # 如果有URL则验证，否则等待URL变化
            if page.url:
                lines.append(f'    # 验证到达目标页面')
                lines.append(f'    page.wait_for_url("**{self._escape(page.url)}**", timeout=10000)')

        return lines

    def _generate_page_wait(self, page: PageNode) -> List[str]:
        """生成页面等待代码"""
        return [
            '    # 等待页面加载完成',
            '    page.wait_for_load_state("domcontentloaded")',
            '    page.wait_for_timeout(1000)  # 额外等待动态内容',
        ]

    def _generate_page_actions(self, page: PageNode, elem_map: Dict[str, List[Dict]]) -> List[str]:
        """生成页面操作代码"""
        lines = [f'    # --- {page.title} 操作 ---']

        for action in page.actions:
            action_type = action.get("action", "click")
            description = action.get("description", "")
            locator = action.get("locator", "")
            value = action.get("value", "")

            lines.append(f'    # {description}')

            if action_type == "goto":
                url = value or page.url or ""
                if url:
                    lines.append(f'    page.goto("{self._escape(url)}", wait_until="domcontentloaded")')

            elif action_type == "fill":
                if locator:
                    fill_value = self._resolve_variable(value)
                    lines.append(f'    page.locator("{self._escape(locator)}").first.fill({fill_value})')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 fill 步骤: {description}')

            elif action_type == "click":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.click()')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 click 步骤: {description}')

            elif action_type == "login":
                # 登录特殊处理
                lines.extend(self._generate_login_actions(page, elem_map))

            elif action_type == "search":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.fill({self._resolve_variable(value or "搜索关键词")})')
                    lines.append('    page.keyboard.press("Enter")')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 search 步骤: {description}')

            elif action_type == "add":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.click()')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 add 步骤: {description}')

            elif action_type == "select":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.select_option(index=0)')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 select 步骤: {description}')

            elif action_type == "navigate":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.click()')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 navigate 步骤: {description}')

            elif action_type == "verify":
                if locator:
                    lines.append(f'    expect(page.locator("{self._escape(locator)}").first).to_be_visible()')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空 verify 步骤: {description}')

            elif action_type == "submit":
                if locator:
                    lines.append(f'    page.locator("{self._escape(locator)}").first.click()')
                else:
                    lines.append('    page.keyboard.press("Enter")')

            else:
                lines.append(f'    # 未知操作类型: {action_type} - {description}')

            lines.append('    page.wait_for_timeout(500)')

        return lines

    def _generate_login_actions(self, page: PageNode, elem_map: Dict[str, List[Dict]]) -> List[str]:
        """生成登录操作代码"""
        lines = []

        # 查找登录页面的输入框和按钮
        page_elements = elem_map.get(page.page_id, [])
        inputs = [e for e in page_elements if e.get("type") in ("input", "searchbox", "textarea")]
        buttons = [e for e in page_elements if e.get("type") == "button"]

        username_input = None
        password_input = None
        login_button = None

        for inp in inputs:
            name = (inp.get("name", "") + (inp.get("placeholder") or "")).lower()
            if any(kw in name for kw in ["用户名", "账号", "邮箱", "手机", "username", "email"]):
                username_input = inp
            elif any(kw in name for kw in ["密码", "password"]):
                password_input = inp

        for btn in buttons:
            name = (btn.get("name", "") + (btn.get("text") or "")).lower()
            if any(kw in name for kw in ["登录", "login", "提交", "submit"]):
                login_button = btn

        # 生成登录代码
        if username_input and username_input.get("locator"):
            lines.append(f'    page.locator("{self._escape(username_input["locator"])}").first.fill(_vars.get("username", "test_user"))')
        else:
            lines.append('    page.locator("input[type=\\"text\\"], input[name=\\"username\\"]").first.fill(_vars.get("username", "test_user"))')

        if password_input and password_input.get("locator"):
            lines.append(f'    page.locator("{self._escape(password_input["locator"])}").first.fill(_vars.get("password", "Test@123456"))')
        else:
            lines.append('    page.locator("input[type=\\"password\\"]").first.fill(_vars.get("password", "Test@123456"))')

        if login_button and login_button.get("locator"):
            lines.append(f'    page.locator("{self._escape(login_button["locator"])}").first.click()')
        else:
            lines.append('    page.locator("button[type=\\"submit\\"], button:has-text(\\"登录\\")").first.click()')

        lines.append('    page.wait_for_load_state("networkidle")')

        return lines

    def _generate_auto_extractions(self, page: PageNode, elem_map: Dict[str, List[Dict]]) -> List[str]:
        """自动提取常见变量"""
        lines = []
        page_type = page.page_type

        if page_type == "product":
            # 商品页：提取商品名称和价格
            lines.extend([
                '    # 自动提取商品信息',
                '    try:',
                '        _vars["product_name"] = page.locator("h1, .product-name, .item-title").first.text_content() or ""',
                '    except Exception:',
                '        _vars["product_name"] = ""',
                '    try:',
                '        _vars["price"] = page.locator(".price, .product-price, [class*=price]").first.text_content() or ""',
                '    except Exception:',
                '        _vars["price"] = ""',
            ])
        elif page_type == "cart":
            # 购物车：提取商品数量和总价
            lines.extend([
                '    # 自动提取购物车信息',
                '    try:',
                '        _vars["cart_count"] = str(page.locator(".cart-count, .cart-num, [class*=count]").first.text_content() or "0").strip()',
                '    except Exception:',
                '        _vars["cart_count"] = "0"',
            ])
        elif page_type == "order":
            # 订单页：提取订单号
            lines.extend([
                '    # 自动提取订单信息',
                '    try:',
                '        _vars["order_id"] = page.locator(".order-id, .order-no, [class*=order]").first.text_content() or ""',
                '    except Exception:',
                '        _vars["order_id"] = ""',
            ])

        return lines

    def _generate_variable_extractions(self, page: PageNode, rules: List[Dict]) -> List[str]:
        """生成变量提取代码"""
        lines = ['    # 变量提取']
        for rule in rules:
            lines.extend(
                self.state_mgr.generate_variable_extract_code(
                    var_name=rule["var_name"],
                    locator=rule["locator"],
                    extract_type=rule.get("extract_type", "text"),
                )
            )
        return lines

    def _generate_page_transition(self, transition: PageTransition, flow_graph: FlowGraph, elem_map: Dict[str, List[Dict]]) -> List[str]:
        """生成页面跳转代码"""
        lines = [
            f'    # ===== 页面跳转: {transition.from_page} → {transition.to_page} =====',
        ]

        # 触发跳转
        if transition.trigger_locator:
            lines.append(f'    # 点击: {transition.trigger}')
            lines.append(f'    page.locator("{self._escape(transition.trigger_locator)}").first.click()')
        elif transition.trigger:
            lines.append(f'    # 触发跳转: {transition.trigger}')
            raise ValueError(f'无法确定稳定定位器，拒绝生成空页面跳转: {transition.trigger}')

        # 等待新页面
        to_page = flow_graph.get_page(transition.to_page)
        if to_page and to_page.url:
            lines.append(f'    page.wait_for_url("**{self._escape(to_page.url)}**", timeout=15000)')
        else:
            lines.append('    page.wait_for_load_state("domcontentloaded")')

        lines.append('    page.wait_for_timeout(2000)  # 等待页面稳定')

        # 传递变量
        if transition.variables_out:
            lines.append('    # 传递变量到下一页面')
            for var_name in transition.variables_out:
                lines.append(f'    # {var_name} = _vars.get("{var_name}", "")')

        return lines

    def _generate_final_assertions(self, flow_graph: FlowGraph, case_data: Dict[str, Any]) -> List[str]:
        """生成最终断言"""
        lines = [
            '    # ===== 最终验证 =====',
        ]

        assertions = case_data.get("assertions", [])
        if assertions:
            for assertion in assertions[:5]:
                atype = assertion.get("type", "visible")
                expected = assertion.get("expected", "")
                locator = assertion.get("locator", "")
                desc = assertion.get("description", "")

                lines.append(f'    # {desc}')
                if locator:
                    if atype == "visible":
                        lines.append(f'    expect(page.locator("{self._escape(locator)}").first).to_be_visible()')
                    elif atype == "text":
                        lines.append(f'    expect(page.locator("{self._escape(locator)}").first).to_contain_text("{self._escape(expected)}")')
                    elif atype == "url":
                        lines.append(f'    expect(page).to_have_url(re.compile(r"{self._escape(expected)}"))')
                else:
                    raise ValueError(f'无法确定稳定定位器，拒绝生成空断言: {desc}')
        else:
            # 默认断言：最后一个页面不为空
            last_page = flow_graph.pages[-1] if flow_graph.pages else None
            if last_page:
                lines.append(f'    # 验证最终页面: {last_page.title}')
                lines.append('    expect(page).to_have_url(re.compile(r".*"))')
                lines.append('    assert page.title() != ""')

        return lines

    def _generate_screenshot(self) -> List[str]:
        """生成截图代码"""
        return [
            '    # 截图保存',
            '    page.screenshot(path="flow_test_result.png", full_page=True)',
        ]

    def _resolve_variable(self, value: str) -> str:
        """解析变量引用，返回Python表达式"""
        if not value:
            return '""'

        # 如果包含 ${var} 格式，替换为 _vars.get()
        import re
        has_var = bool(re.search(r'\$\{(\w+)\}', value))
        if has_var:
            # 构建f-string
            result = value
            for match in re.finditer(r'\$\{(\w+)\}', value):
                var_name = match.group(1)
                result = result.replace(match.group(0), f'" + _vars.get("{var_name}", "") + "')
            return f'f"{result}"'

        return f'"{self._escape(value)}"'

    @staticmethod
    def _escape(s: str) -> str:
        """转义字符串"""
        if not s:
            return ""
        return s.replace('\\', '\\\\').replace('"', '\\"')
