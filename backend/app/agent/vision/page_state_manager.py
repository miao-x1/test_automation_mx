"""
PageStateManager - 页面状态保存与恢复
VariableContext - 跨页面变量传递

支持：
- 保存页面状态（cookies, localStorage, sessionStorage）
- 在页面跳转间恢复状态
- 变量提取与传递（如：从登录页提取用户名，在订单页使用）
- 变量作用域管理（全局/页面级）
"""
import json
from typing import Any, Dict, List, Optional
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class VariableContext:
    """
    跨页面变量上下文

    管理变量在页面间的传递，支持：
    - 全局变量：所有页面可访问
    - 页面级变量：仅当前页面和后续页面可访问
    - 变量提取：从页面元素中提取值
    - 变量注入：将变量值注入到操作中
    """

    def __init__(self):
        self._global_vars: Dict[str, str] = {}
        self._page_vars: Dict[str, Dict[str, str]] = {}  # page_id -> {var_name: value}
        self._extract_rules: List[Dict[str, Any]] = []  # 变量提取规则

    def set_global(self, name: str, value: str) -> None:
        """设置全局变量"""
        self._global_vars[name] = value

    def get_global(self, name: str, default: str = "") -> str:
        """获取全局变量"""
        return self._global_vars.get(name, default)

    def set_page_var(self, page_id: str, name: str, value: str) -> None:
        """设置页面级变量"""
        if page_id not in self._page_vars:
            self._page_vars[page_id] = {}
        self._page_vars[page_id][name] = value

    def get_page_var(self, page_id: str, name: str, default: str = "") -> str:
        """获取页面级变量（当前页面 + 之前页面的变量）"""
        # 先查当前页面
        if page_id in self._page_vars and name in self._page_vars[page_id]:
            return self._page_vars[page_id][name]
        # 再查全局
        return self._global_vars.get(name, default)

    def resolve(self, page_id: str, template: str) -> str:
        """
        解析变量模板

        将 ${variable_name} 替换为实际值

        Args:
            page_id: 当前页面ID
            template: 包含变量引用的字符串，如 "欢迎 ${username}"

        Returns:
            解析后的字符串
        """
        import re
        result = template

        # 替换 ${var} 格式
        for match in re.finditer(r'\$\{(\w+)\}', template):
            var_name = match.group(1)
            value = self.get_page_var(page_id, var_name, match.group(0))
            result = result.replace(match.group(0), value)

        return result

    def add_extract_rule(self, page_id: str, var_name: str, locator: str, extract_type: str = "text") -> None:
        """
        添加变量提取规则

        Args:
            page_id: 在哪个页面提取
            var_name: 变量名
            locator: 元素定位器
            extract_type: 提取类型 text/attribute/value
        """
        self._extract_rules.append({
            "page_id": page_id,
            "var_name": var_name,
            "locator": locator,
            "extract_type": extract_type,
        })

    def get_extract_rules(self, page_id: str) -> List[Dict[str, Any]]:
        """获取指定页面的变量提取规则"""
        return [r for r in self._extract_rules if r["page_id"] == page_id]

    def all_globals(self) -> Dict[str, str]:
        """获取所有全局变量"""
        return dict(self._global_vars)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "global_vars": self._global_vars,
            "page_vars": self._page_vars,
            "extract_rules": self._extract_rules,
        }


class PageStateManager(NewBaseAgent):
    """
    页面状态管理器

    在Playwright脚本中生成状态保存和恢复的代码。

    支持：
    - 保存cookies
    - 保存localStorage
    - 保存sessionStorage
    - 页面URL快照
    - 表单数据快照
    """

    agent_name = "page_state_manager"
    display_name = "Page State Manager"
    description = "页面状态保存与恢复管理器"
    capabilities = [AgentCapability.PAGE_STATE]

    # 状态保存代码模板
    SAVE_COOKIES_TEMPLATE = '    # 保存cookies\n    _state["cookies"] = context.cookies()'
    RESTORE_COOKIES_TEMPLATE = '    # 恢复cookies\n    if "cookies" in _state:\n        context.add_cookies(_state["cookies"])'

    SAVE_STORAGE_TEMPLATE = '    # 保存localStorage\n    _state["local_storage"] = page.evaluate("() => Object.assign({}, window.localStorage)")'
    RESTORE_STORAGE_TEMPLATE = '    # 恢复localStorage\n    if "local_storage" in _state:\n        for key, value in _state["local_storage"].items():\n            page.evaluate(f"window.localStorage.setItem(\'{key}\', \'{value}\')")'

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self._saved_states: Dict[str, Dict[str, Any]] = {}

    def generate_save_code(self, page_id: str, save_items: List[str] = None) -> List[str]:
        """
        生成页面状态保存代码

        Args:
            page_id: 页面标识
            save_items: 要保存的项目 ["cookies", "local_storage", "url"]

        Returns:
            Python代码行列表
        """
        if save_items is None:
            save_items = ["cookies", "local_storage", "url"]

        lines = [
            f'    # ===== 保存页面状态: {page_id} =====',
            f'    _state["{page_id}"] = {{}}',
        ]

        if "cookies" in save_items:
            lines.extend([
                '    try:',
                '        _state["{}"]["cookies"] = context.cookies()'.format(page_id),
                '    except Exception:',
                '        pass',
            ])

        if "local_storage" in save_items:
            lines.extend([
                '    try:',
                '        _state["{}"]["local_storage"] = page.evaluate("() => Object.assign({{}}, window.localStorage)")'.format(page_id),
                '    except Exception:',
                '        pass',
            ])

        if "url" in save_items:
            lines.append('    _state["{}"]["url"] = page.url'.format(page_id))

        return lines

    def generate_restore_code(self, page_id: str, restore_items: List[str] = None) -> List[str]:
        """
        生成页面状态恢复代码

        Args:
            page_id: 页面标识
            restore_items: 要恢复的项目

        Returns:
            Python代码行列表
        """
        if restore_items is None:
            restore_items = ["cookies"]

        lines = [
            f'    # ===== 恢复页面状态: {page_id} =====',
        ]

        if "cookies" in restore_items:
            lines.extend([
                '    try:',
                '        if "cookies" in _state.get("{}", {{}}):'.format(page_id),
                '            context.add_cookies(_state["{}"]["cookies"])'.format(page_id),
                '    except Exception:',
                '        pass',
            ])

        return lines

    def generate_variable_extract_code(self, var_name: str, locator: str, extract_type: str = "text") -> List[str]:
        """
        生成变量提取代码

        Args:
            var_name: 变量名
            locator: 元素定位器
            extract_type: 提取类型 text/attribute/value

        Returns:
            Python代码行列表
        """
        lines = [
            f'    # 提取变量: {var_name}',
            '    try:',
        ]

        if extract_type == "text":
            lines.append(f'        {var_name} = page.locator("{locator}").first.text_content() or ""')
        elif extract_type == "attribute":
            lines.append(f'        {var_name} = page.locator("{locator}").first.get_attribute("value") or ""')
        elif extract_type == "value":
            lines.append(f'        {var_name} = page.locator("{locator}").first.input_value() or ""')

        lines.extend([
            f'        _vars["{var_name}"] = {var_name}',
            '    except Exception:',
            f'        _vars["{var_name}"] = ""',
        ])

        return lines

    def generate_variable_inject_code(self, var_name: str, locator: str, action: str = "fill") -> List[str]:
        """
        生成变量注入代码

        Args:
            var_name: 变量名
            locator: 目标元素定位器
            action: 注入动作 fill/select_option/click

        Returns:
            Python代码行列表
        """
        lines = [
            f'    # 注入变量: {var_name}',
            '    try:',
        ]

        if action == "fill":
            lines.append(f'        page.locator("{locator}").first.fill(_vars.get("{var_name}", ""))')
        elif action == "select_option":
            lines.append(f'        page.locator("{locator}").first.select_option(value=_vars.get("{var_name}", ""))')

        lines.append('    except Exception as e:')
        lines.append(f'        print(f"变量注入失败: {var_name}, {{e}}")')

        return lines
