"""
统一 Playwright 浏览器启动工具

所有需要启动浏览器的地方通过此模块获取 launch_kwargs，
实现集中管理 executable_path / headless / args 等配置。

用法:
    from app.utils.browser_launcher import get_launch_kwargs

    with sync_playwright() as p:
        browser = p.chromium.launch(**get_launch_kwargs())

配置优先级:
    1. 环境变量 PLAYWRIGHT_CHROME_PATH  — 指定 Chrome 可执行文件路径
    2. 环境变量 PLAYWRIGHT_HEADLESS     — 无头模式（默认 True）
    3. 未设置则使用 Playwright 内置 Chromium（Docker 兼容）
"""
import os

from app.core.config import settings

# 反自动化检测参数（所有启动方式共用）
_BROWSER_ARGS = [
    '--disable-blink-features=AutomationControlled',
    '--no-sandbox',
    '--disable-dev-shm-usage',
]


def get_chrome_path() -> str | None:
    """获取 Chrome 可执行文件路径

    Returns:
        Chrome 路径，未配置返回 None（使用 Playwright 内置浏览器）
    """
    return settings.PLAYWRIGHT_CHROME_PATH or None


def get_launch_kwargs() -> dict:
    """获取 chromium.launch() 的 kwargs

    自动读取配置，注入 executable_path（如果配置了本机 Chrome）。

    Returns:
        launch() 关键字参数字典
    """
    kwargs: dict = {
        "headless": settings.PLAYWRIGHT_HEADLESS,
        "args": list(_BROWSER_ARGS),
    }
    chrome_path = get_chrome_path()
    if chrome_path:
        kwargs["executable_path"] = chrome_path
    return kwargs


def get_launch_code_snippet(playwright_var: str = "pw") -> str:
    """生成注入到测试脚本中的浏览器启动代码片段

    用于 execution_agent / script_executor 等需要将浏览器配置
    注入到动态生成的测试脚本中的场景。

    Args:
        playwright_var: Playwright 实例变量名（默认为 pw）

    Returns:
        Python 代码字符串
    """
    chrome_path = get_chrome_path()
    headless = settings.PLAYWRIGHT_HEADLESS
    args_repr = repr(_BROWSER_ARGS)

    if chrome_path:
        return (
            f"browser = {playwright_var}.chromium.launch(\n"
            f"    headless={headless},\n"
            f"    executable_path={chrome_path!r},\n"
            f"    args={args_repr},\n"
            f")"
        )
    else:
        return (
            f"browser = {playwright_var}.chromium.launch(\n"
            f"    headless={headless},\n"
            f"    args={args_repr},\n"
            f")"
        )
