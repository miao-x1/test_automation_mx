"""Playwright 工具 - 脚本执行"""
import asyncio
import logging
import os
import tempfile
from typing import Any, Dict
from app.tools.base import BaseTool, ToolResult, ToolContext

logger = logging.getLogger(__name__)


class PlaywrightTool(BaseTool):
    """Playwright 脚本执行工具

    执行 Playwright 测试脚本，收集执行结果。
    """

    def __init__(self):
        super().__init__(name="playwright", description="Playwright脚本执行，支持pytest和直接运行")

    async def execute(self, ctx: ToolContext, **kwargs) -> ToolResult:
        action = kwargs.get("action", "run")

        if action == "run":
            return await self._run_script(ctx, **kwargs)
        elif action == "validate":
            return await self._validate_script(ctx, **kwargs)
        else:
            return ToolResult(success=False, error=f"Unknown action: {action}")

    async def _run_script(self, ctx: ToolContext, **kwargs) -> ToolResult:
        script_content = kwargs.get("script_content", "")
        script_path = kwargs.get("script_path", "")
        browser = kwargs.get("browser", "chromium")
        headless = kwargs.get("headless", True)
        timeout = kwargs.get("timeout", 300)

        if not script_content and not script_path:
            return ToolResult(success=False, error="script_content或script_path不能为空")

        # 如果提供了脚本内容，写入临时文件
        if script_content:
            tmp = tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False, encoding="utf-8"
            )
            tmp.write(script_content)
            tmp.close()
            script_path = tmp.name

        # 检测 pytest-playwright 插件是否可用
        use_pytest = False
        try:
            import pytest_playwright  # noqa: F401
            use_pytest = True
        except ImportError:
            use_pytest = False

        try:
            if use_pytest:
                # 有 pytest-playwright 插件，用 pytest --browser 执行
                cmd = [
                    "python", "-m", "pytest", script_path,
                    "--browser", browser,
                    "--headed" if not headless else "",
                    "-v",
                ]
                cmd = [c for c in cmd if c]
            else:
                # 无 pytest-playwright，生成 wrapper 用 playwright 直接执行
                runner_path = script_path.replace(".py", "_runner.py")
                runner_code = self._build_runner(script_path, browser, headless)
                with open(runner_path, "w", encoding="utf-8") as f:
                    f.write(runner_code)
                cmd = ["python", runner_path]

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            output = stdout.decode("utf-8", errors="replace")
            error_output = stderr.decode("utf-8", errors="replace")
            combined = output + ("\n" + error_output if error_output else "")

            # 解析 runner 输出统计（结果行格式："PASS test_xxx" / "FAIL test_xxx" / "ERROR test_xxx"）
            passed = combined.count("PASS test_")
            failed = combined.count("FAIL test_") + combined.count("ERROR test_")

            return ToolResult(
                success=proc.returncode == 0,
                data={
                    "return_code": proc.returncode,
                    "stdout": output[-2000:] if len(output) > 2000 else output,
                    "stderr": error_output[-2000:] if len(error_output) > 2000 else error_output,
                    "script_path": script_path,
                    "passed": passed,
                    "failed": failed,
                },
                error=error_output if proc.returncode != 0 else "",
            )

        except asyncio.TimeoutError:
            return ToolResult(success=False, error=f"脚本执行超时（{timeout}s）")
        except Exception as e:
            logger.error(f"[PlaywrightTool] 执行失败: {e}")
            return ToolResult(success=False, error=str(e))
        finally:
            # 清理临时文件
            if script_content and os.path.exists(script_path):
                try:
                    os.unlink(script_path)
                except Exception:
                    pass
            runner_path = (script_path or "").replace(".py", "_runner.py")
            if os.path.exists(runner_path):
                try:
                    os.unlink(runner_path)
                except Exception:
                    pass

    def _build_runner(self, script_path: str, browser: str, headless: bool) -> str:
        """生成独立运行脚本（不依赖 pytest-playwright，用 playwright sync_api 直接执行）"""
        return f'''import sys, traceback
from playwright.sync_api import sync_playwright

with open(r"{script_path}", encoding="utf-8") as f:
    _user_code = f.read()

ns = {{"__name__": "_user_test"}}
try:
    exec(_user_code, ns)
except Exception as e:
    print(f"SCRIPT ERROR: {{e}}")
    traceback.print_exc()
    sys.exit(2)

results = []
try:
    with sync_playwright() as p:
        launch_fn = getattr(p, "{browser}", p.chromium)
        br = launch_fn.launch(headless={headless})
        page = br.new_page()
        for name, obj in list(ns.items()):
            if isinstance(obj, type) and name.startswith("Test"):
                instance = obj()
                for method in sorted(dir(instance)):
                    if method.startswith("test_"):
                        try:
                            getattr(instance, method)(page)
                            results.append((method, "PASS", ""))
                        except AssertionError as e:
                            results.append((method, "FAIL", str(e) or "assert failed"))
                        except Exception as e:
                            results.append((method, "ERROR", f"{{type(e).__name__}}: {{e}}"))
        br.close()
except Exception as e:
    print(f"BROWSER ERROR: {{e}}")
    traceback.print_exc()
    sys.exit(3)

passed = sum(1 for _, s, _ in results if s == "PASS")
failed = sum(1 for _, s, _ in results if s != "PASS")
for m, s, e in results:
    print(f"{{s}} {{m}}" + (f" - {{e}}" if e else ""))
print(f"\\n=== {{passed}} passed, {{failed}} failed ===")
sys.exit(1 if failed > 0 else 0)
'''

    async def _validate_script(self, ctx: ToolContext, **kwargs) -> ToolResult:
        script_content = kwargs.get("script_content", "")

        if not script_content:
            return ToolResult(success=False, error="script_content不能为空")

        # 基本语法检查
        try:
            compile(script_content, "<script>", "exec")
            return ToolResult(success=True, data={"valid": True, "message": "语法检查通过"})
        except SyntaxError as e:
            return ToolResult(
                success=False,
                data={"valid": False},
                error=f"语法错误: {e}",
            )
