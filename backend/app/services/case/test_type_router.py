"""
TestTypeRouter - 测试类型自动推断

根据用例内容自动推断测试类型：
- 包含HTTP method/url → API
- 包含selector/元素定位 → UI
- 包含web flow/页面操作 → WEB
- 包含android/activity → ANDROID
- 默认 → API
"""
import json
from typing import Dict, List, Optional
from app.core.logger import log


class TestTypeRouter:
    """测试类型路由器"""

    # UI测试关键词
    UI_KEYWORDS = [
        "selector", "click", "input", "xpath", "css_selector",
        "element", "button", "input_field", "dropdown", "checkbox",
        "等待元素", "点击", "输入", "选择", "勾选",
    ]

    # Web测试关键词
    WEB_KEYWORDS = [
        "navigate", "page", "browser", "url_visit", "screenshot",
        "cookie", "session", "window", "iframe", "alert",
        "打开页面", "浏览器", "截图", "切换窗口",
    ]

    # Android测试关键词
    ANDROID_KEYWORDS = [
        "activity", "intent", "package", "adb", "uiautomator",
        "appium", "tap", "swipe", "scroll", "device",
        "启动应用", "滑动", "设备",
    ]

    @staticmethod
    def route(case_data: Dict) -> str:
        """
        根据用例内容推断测试类型

        Args:
            case_data: 用例数据（包含steps/assertions/fields等）

        Returns:
            "API" | "UI" | "WEB" | "ANDROID"
        """
        # 1. 如果显式指定了test_type，直接返回
        if case_data.get("test_type"):
            return case_data["test_type"].upper()

        # 2. 如果有method/url字段，优先判定为API
        method = case_data.get("method", "")
        url = case_data.get("url", "")
        if method and method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
            return "API"

        # 3. 检查steps中的action
        steps = case_data.get("steps", [])
        if steps and isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                action = step.get("action", "")
                # HTTP方法 → API
                if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    return "API"
                # UI操作
                if action.lower() in ("click", "input", "select", "hover", "scroll", "wait"):
                    return "UI"
                if any(kw in action.lower() for kw in TestTypeRouter.UI_KEYWORDS):
                    return "UI"
                if any(kw in action.lower() for kw in TestTypeRouter.WEB_KEYWORDS):
                    return "WEB"
                if any(kw in action.lower() for kw in TestTypeRouter.ANDROID_KEYWORDS):
                    return "ANDROID"

        # 4. 检查steps的文本内容
        steps_text = json.dumps(steps, ensure_ascii=False).lower()
        if any(kw.lower() in steps_text for kw in TestTypeRouter.ANDROID_KEYWORDS):
            return "ANDROID"
        if any(kw.lower() in steps_text for kw in TestTypeRouter.UI_KEYWORDS):
            return "UI"
        if any(kw.lower() in steps_text for kw in TestTypeRouter.WEB_KEYWORDS):
            return "WEB"

        # 5. 检查precondition
        precondition = str(case_data.get("precondition", "")).lower()
        if any(kw.lower() in precondition for kw in TestTypeRouter.ANDROID_KEYWORDS):
            return "ANDROID"
        if any(kw.lower() in precondition for kw in TestTypeRouter.UI_KEYWORDS):
            return "UI"
        if any(kw.lower() in precondition for kw in TestTypeRouter.WEB_KEYWORDS):
            return "WEB"

        # 6. 默认API
        return "API"

    @staticmethod
    def route_batch(cases: List[Dict]) -> Dict[str, str]:
        """批量推断测试类型，返回 {case_index: test_type}"""
        result = {}
        for i, case in enumerate(cases):
            result[str(i)] = TestTypeRouter.route(case)
        return result
