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

        try:
            cmd = [
                "python", "-m", "pytest", script_path,
                "--browser", browser,
                "--headed" if not headless else "",
                "-v",
            ]
            cmd = [c for c in cmd if c]  # 移除空字符串

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

            return ToolResult(
                success=proc.returncode == 0,
                data={
                    "return_code": proc.returncode,
                    "stdout": output[-2000:] if len(output) > 2000 else output,
                    "stderr": error_output[-2000:] if len(error_output) > 2000 else error_output,
                    "script_path": script_path,
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
