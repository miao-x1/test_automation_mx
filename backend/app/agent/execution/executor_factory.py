"""
ExecutorFactory - 执行器工厂

根据task_type自动选择对应的执行器：
- WEB → PlaywrightExecutor
- API → APIExecutor
- ANDROID → AppiumExecutor
- PERFORMANCE → PerformanceExecutor
"""
from typing import Dict, Any, Optional
from app.core.logger import log
from app.agent.requirement.type_classifier import TestType


class ExecutorFactory:
    """执行器工厂"""

    @staticmethod
    def create(task_type: str) -> "BaseExecutor":
        """根据task_type创建执行器"""
        executors = {
            TestType.WEB.value: PlaywrightExecutor,
            TestType.API.value: APIExecutor,
            TestType.ANDROID.value: AppiumExecutor,
            TestType.PERFORMANCE.value: PerformanceExecutor,
        }

        executor_class = executors.get(task_type, PlaywrightExecutor)
        log.info(f"ExecutorFactory创建执行器 | task_type={task_type}, executor={executor_class.__name__}")
        return executor_class()


class BaseExecutor:
    """执行器基类"""

    def execute(self, script_content: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        执行脚本

        Returns:
            {success: bool, output: str, error: str, duration: int, exit_code: int}
        """
        raise NotImplementedError

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """校验执行配置"""
        return True


class PlaywrightExecutor(BaseExecutor):
    """Web测试执行器 - 使用Playwright"""

    def execute(self, script_content: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行Playwright脚本"""
        import subprocess
        import tempfile
        import os
        import time as _time

        config = config or {}
        timeout = config.get("timeout", 300)

        # 写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            script_path = f.name

        start = _time.time()
        try:
            proc = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
                env={
                    **os.environ,
                    "PLAYWRIGHT_BROWSERS_PATH": "0",
                    "PLAYWRIGHT_CHROME_PATH": os.environ.get("PLAYWRIGHT_CHROME_PATH", ""),
                    "PLAYWRIGHT_HEADLESS": os.environ.get("PLAYWRIGHT_HEADLESS", "True"),
                },
            )
            duration = int(_time.time() - start)
            return {
                "success": proc.returncode == 0,
                "output": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                "error": proc.stderr[-3000:] if proc.stderr else "",
                "duration": duration,
                "exit_code": proc.returncode,
                "executor": "playwright",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"执行超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "playwright"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "playwright"}
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass


class APIExecutor(BaseExecutor):
    """API测试执行器"""

    def execute(self, script_content: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行API测试脚本（Python requests/httpx）"""
        import subprocess
        import tempfile
        import os
        import time as _time

        config = config or {}
        timeout = config.get("timeout", 300)

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            script_path = f.name

        start = _time.time()
        try:
            proc = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = int(_time.time() - start)
            return {
                "success": proc.returncode == 0,
                "output": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                "error": proc.stderr[-3000:] if proc.stderr else "",
                "duration": duration,
                "exit_code": proc.returncode,
                "executor": "api",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"执行超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "api"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "api"}
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass


class AppiumExecutor(BaseExecutor):
    """Android测试执行器 - 使用Appium"""

    def execute(self, script_content: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行Appium脚本"""
        import subprocess
        import tempfile
        import os
        import time as _time

        config = config or {}
        timeout = config.get("timeout", 600)  # Appium需要更长超时

        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(script_content)
            script_path = f.name

        start = _time.time()
        try:
            proc = subprocess.run(
                ["python", script_path],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = int(_time.time() - start)
            return {
                "success": proc.returncode == 0,
                "output": proc.stdout[-5000:] if len(proc.stdout) > 5000 else proc.stdout,
                "error": proc.stderr[-3000:] if proc.stderr else "",
                "duration": duration,
                "exit_code": proc.returncode,
                "executor": "appium",
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"执行超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "appium"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "appium"}
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

    def validate_config(self, config: Dict[str, Any]) -> bool:
        """校验Appium配置"""
        return bool(config.get("app_path") or config.get("app_package"))


class PerformanceExecutor(BaseExecutor):
    """性能测试执行器"""

    def execute(self, script_content: str, config: Dict[str, Any] = None) -> Dict[str, Any]:
        """执行性能测试脚本"""
        import subprocess
        import tempfile
        import os
        import time as _time

        config = config or {}
        timeout = config.get("timeout", 600)  # 性能测试需要更长超时

        # 检测脚本类型
        content_lower = script_content.lower()
        if "locust" in content_lower:
            return self._execute_locust(script_content, config, timeout)
        elif "k6" in content_lower:
            return self._execute_k6(script_content, config, timeout)
        else:
            # 默认Python执行
            return self._execute_python(script_content, config, timeout)

    def _execute_python(self, content: str, config: Dict, timeout: int) -> Dict:
        import subprocess, tempfile, os, time as _time
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
            f.write(content)
            path = f.name
        start = _time.time()
        try:
            proc = subprocess.run(["python", path], capture_output=True, text=True, timeout=timeout)
            return {"success": proc.returncode == 0, "output": proc.stdout[-5000:], "error": proc.stderr[-3000:], "duration": int(_time.time() - start), "exit_code": proc.returncode, "executor": "performance"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "performance"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "performance"}
        finally:
            try: os.unlink(path)
            except Exception: pass

    def _execute_locust(self, content: str, config: Dict, timeout: int) -> Dict:
        """执行Locust脚本"""
        import subprocess, tempfile, os, time as _time
        with tempfile.NamedTemporaryFile(mode='w', suffix='_locust.py', delete=False, encoding='utf-8') as f:
            f.write(content)
            path = f.name
        start = _time.time()
        try:
            proc = subprocess.run(
                ["locust", "-f", path, "--headless", "-u", "10", "-r", "2", "-t", "30s", "--host", config.get("target_url", "http://localhost")],
                capture_output=True, text=True, timeout=timeout,
            )
            return {"success": proc.returncode == 0, "output": proc.stdout[-5000:], "error": proc.stderr[-3000:], "duration": int(_time.time() - start), "exit_code": proc.returncode, "executor": "performance_locust"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "performance_locust"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "performance_locust"}
        finally:
            try: os.unlink(path)
            except Exception: pass

    def _execute_k6(self, content: str, config: Dict, timeout: int) -> Dict:
        """执行k6脚本"""
        import subprocess, tempfile, os, time as _time
        with tempfile.NamedTemporaryFile(mode='w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(content)
            path = f.name
        start = _time.time()
        try:
            proc = subprocess.run(["k6", "run", path], capture_output=True, text=True, timeout=timeout)
            return {"success": proc.returncode == 0, "output": proc.stdout[-5000:], "error": proc.stderr[-3000:], "duration": int(_time.time() - start), "exit_code": proc.returncode, "executor": "performance_k6"}
        except subprocess.TimeoutExpired:
            return {"success": False, "error": f"超时({timeout}秒)", "output": "", "duration": timeout, "exit_code": -1, "executor": "performance_k6"}
        except Exception as e:
            return {"success": False, "error": str(e), "output": "", "duration": 0, "exit_code": -1, "executor": "performance_k6"}
        finally:
            try: os.unlink(path)
            except Exception: pass
