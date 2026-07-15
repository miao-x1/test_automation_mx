"""
ScriptExecutor - 脚本执行器

支持执行 Playwright/Midscene/YAML/JSON 脚本
"""
import json
import os
import subprocess
import tempfile
import time as _time
from typing import Dict, Any, Optional
from app.core.logger import log
from app.core.config import settings
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ScriptExecutor(NewBaseAgent):
    """脚本执行器"""

    agent_name = "script_executor"
    display_name = "Script Executor"
    description = "脚本执行器 - 支持执行Playwright/Midscene/YAML/JSON脚本"
    capabilities = [AgentCapability.SCRIPT_EXECUTE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    def execute(
        self,
        content: str,
        script_type: str,
        language: str = "",
        task_id: int = None,
        timeout: int = 300,
    ) -> Dict[str, Any]:
        """
        执行脚本

        Returns:
            {
                success: bool,
                output: str,
                error: str,
                duration: int,
                exit_code: int,
            }
        """
        start_time = _time.time()

        try:
            if script_type == "playwright":
                result = self._execute_playwright(content, timeout)
            elif script_type == "midscene":
                result = self._execute_midscene(content, timeout)
            elif script_type in ("yaml", "json"):
                result = self._execute_config_script(content, script_type, timeout)
            else:
                result = {"success": False, "error": f"不支持的脚本类型: {script_type}", "output": "", "exit_code": -1}

        except subprocess.TimeoutExpired:
            result = {"success": False, "error": f"执行超时({timeout}秒)", "output": "", "exit_code": -1}
        except Exception as e:
            result = {"success": False, "error": str(e), "output": "", "exit_code": -1}

        duration = int(_time.time() - start_time)
        result["duration"] = duration

        # 记录执行结果到Task
        if task_id:
            self._update_task_result(task_id, result)

        return result

    def _execute_playwright(self, content: str, timeout: int) -> Dict:
        """执行Playwright Python脚本"""
        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(content)
            script_path = f.name

        try:
            log.info(f"执行Playwright脚本 | path={script_path}")
            proc = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=os.path.dirname(script_path),
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"},
            )

            return {
                "success": proc.returncode == 0,
                "output": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                "error": proc.stderr[-3000:] if proc.stderr else "",
                "exit_code": proc.returncode,
            }
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def _execute_midscene(self, content: str, timeout: int) -> Dict:
        """执行Midscene JavaScript脚本"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mjs', delete=False, encoding='utf-8') as f:
            f.write(content)
            script_path = f.name

        try:
            log.info(f"执行Midscene脚本 | path={script_path}")
            proc = subprocess.run(
                ["node", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            return {
                "success": proc.returncode == 0,
                "output": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                "error": proc.stderr[-3000:] if proc.stderr else "",
                "exit_code": proc.returncode,
            }
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def _execute_config_script(self, content: str, script_type: str, timeout: int) -> Dict:
        """执行YAML/JSON配置脚本（转换为Playwright执行）"""
        # 解析配置
        if script_type == "yaml":
            try:
                import yaml
                config = yaml.safe_load(content)
            except Exception as e:
                return {"success": False, "error": f"YAML解析失败: {e}", "output": "", "exit_code": -1}
        else:
            try:
                config = json.loads(content)
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"JSON解析失败: {e}", "output": "", "exit_code": -1}

        # 转换为Playwright脚本
        playwright_script = self._config_to_playwright(config)
        if not playwright_script:
            return {"success": False, "error": "配置转换失败", "output": "", "exit_code": -1}

        return self._execute_playwright(playwright_script, timeout)

    def _config_to_playwright(self, config: Dict) -> str:
        """将YAML/JSON配置转换为Playwright脚本"""
        if not isinstance(config, dict):
            return ""

        name = config.get("name", "config_test")
        target = config.get("target", config.get("url", "https://example.com"))
        steps = config.get("steps", [])

        lines = [
            "from playwright.sync_api import sync_playwright",
            "",
            f"def test_{name.replace(' ', '_').replace('-', '_')}():",
            "    with sync_playwright() as p:",
            "        browser = p.chromium.launch()",
            "        page = browser.new_page()",
            f'        page.goto("{target}")',
            "        page.wait_for_load_state('networkidle')",
        ]

        for step in steps:
            if not isinstance(step, dict):
                continue
            action = step.get("action", "")
            value = step.get("value", "")
            locator = step.get("locator", {})
            primary = locator.get("primary", "") if isinstance(locator, dict) else str(locator)
            fallback = locator.get("fallback", "") if isinstance(locator, dict) else ""
            retry = step.get("retry", 1)
            step_timeout = step.get("timeout", 5000)

            if action == "navigate":
                lines.append(f'        page.goto("{value or target}")')
                lines.append("        page.wait_for_load_state('networkidle')")
            elif action == "click":
                if primary:
                    loc_str = self._locator_to_playwright(primary)
                    if fallback:
                        fb_str = self._locator_to_playwright(fallback)
                        lines.append(f"        try:")
                        lines.append(f"            page.{loc_str}.click(timeout={step_timeout})")
                        lines.append(f"        except Exception:")
                        lines.append(f"            page.{fb_str}.click(timeout={step_timeout})")
                    else:
                        lines.append(f"        page.{loc_str}.click(timeout={step_timeout})")
            elif action in ("input", "fill", "type"):
                if primary:
                    loc_str = self._locator_to_playwright(primary)
                    lines.append(f'        page.{loc_str}.fill("{value}", timeout={step_timeout})')
            elif action == "wait":
                lines.append(f"        page.wait_for_timeout({step_timeout})")
            elif action == "assert":
                if primary:
                    lines.append(f"        # assert: {primary}")

        lines.extend([
            "        browser.close()",
            "",
            'if __name__ == "__main__":',
            f"    test_{name.replace(' ', '_').replace('-', '_')}()",
        ])

        return "\n".join(lines)

    def _locator_to_playwright(self, locator: str) -> str:
        """将定位器转换为Playwright locator调用"""
        if locator.startswith("data-testid="):
            val = locator.split("=", 1)[1].strip('"\'')
            return f'get_by_test_id("{val}")'
        if locator.startswith("#"):
            return f'locator("#{locator[1:]}")'
        if locator.startswith("name="):
            val = locator.split("=", 1)[1].strip('"\'')
            return f'locator(\'[name="{val}"]\')'
        if locator.startswith("xpath="):
            return f'locator("xpath={locator[6:]}")'
        if locator.startswith("text="):
            return f'get_by_text("{locator[5:]}")'
        return f'locator("{locator}")'

    def _update_task_result(self, task_id: int, result: Dict):
        """更新任务执行结果"""
        from app.services.context_router import get_context_router, ContextType
        from app.services.context_router.storage_router import get_storage_router
        from app.models.task import TaskStatus

        try:
            router = get_context_router()
            storage = get_storage_router()
            task = router.query_by_id(ContextType.TASK, record_id=task_id)
            if task:
                if result.get("success"):
                    storage.mysql_update("Task", record_id=task_id, data={"status": TaskStatus.COMPLETED})
                else:
                    storage.mysql_update("Task", record_id=task_id, data={"status": TaskStatus.FAILED})
        except Exception as e:
            log.warning(f"更新任务结果失败: {e}")
