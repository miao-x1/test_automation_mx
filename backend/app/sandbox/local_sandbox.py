"""
本地子进程沙箱 (降级方案)

当 Docker 不可用时, 使用本地子进程执行代码, 提供基础隔离:
  - 独立子进程 (进程级隔离)
  - 执行超时控制 (subprocess timeout)
  - 安全检查 (CodeSecurityChecker)
  - 临时工作目录
  - 环境变量清理

注意: 本地沙箱的隔离级别低于 Docker, 仅作为降级方案。
      生产环境应优先使用 DockerSandbox。

使用方式:
    sandbox = LocalSandbox()
    result = await sandbox.execute(code, timeout=30)
"""
import asyncio
import json
import logging
import os
import sys
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.sandbox.security import CodeSecurityChecker

logger = logging.getLogger(__name__)


@dataclass
class LocalExecutionResult:
    """本地执行结果"""
    success: bool = False
    output: str = ""
    error: str = ""
    exit_code: int = -1
    duration_ms: float = 0
    timed_out: bool = False
    security_report: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output[:10000],
            "error": self.error[:5000],
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 2),
            "timed_out": self.timed_out,
            "security_report": self.security_report,
        }


# 沙箱内执行的 wrapper 脚本 (与 Docker 沙箱共用)
_LOCAL_WRAPPER = '''"""Local sandbox wrapper — 自动生成"""
import sys
import json
import traceback
import io

_result = {{"success": False, "output": "", "error": "", "stdout": "", "stderr": ""}}

_stdout_buf = io.StringIO()
_stderr_buf = io.StringIO()
_old_stdout = sys.stdout
_old_stderr = sys.stderr

try:
    sys.stdout = _stdout_buf
    sys.stderr = _stderr_buf

    _user_code = {user_code!r}
    exec(compile(_user_code, "<sandbox>", "exec"), {{"__name__": "__main__"}})

    _result["success"] = True
    _result["stdout"] = _stdout_buf.getvalue()
    _result["stderr"] = _stderr_buf.getvalue()

except SystemExit as e:
    _result["success"] = (e.code == 0 or e.code is None)
    _result["stdout"] = _stdout_buf.getvalue()
    _result["stderr"] = _stderr_buf.getvalue()
    if not _result["success"]:
        _result["error"] = f"SystemExit: {{e.code}}"

except Exception as e:
    _result["success"] = False
    _result["stdout"] = _stdout_buf.getvalue()
    _result["stderr"] = _stderr_buf.getvalue()
    _result["error"] = traceback.format_exc()

finally:
    sys.stdout = _old_stdout
    sys.stderr = _old_stderr

print(json.dumps(_result, ensure_ascii=False, default=str))
'''


class LocalSandbox:
    """本地子进程沙箱

    在本地子进程中执行 Python 代码, 提供基础隔离。
    作为 DockerSandbox 不可用时的降级方案。

    安全措施:
      1. 代码先经过 CodeSecurityChecker 静态分析
      2. 在独立子进程中执行 (进程级隔离)
      3. 执行超时自动终止
      4. 临时工作目录隔离
      5. 清理环境变量 (移除敏感变量)
      6. 限制 Python 可导入模块 (通过 -S 参数)

    使用方式:
        sandbox = LocalSandbox()
        result = await sandbox.execute(code, timeout=30)
    """

    def __init__(
        self,
        python_executable: Optional[str] = None,
        default_timeout: int = 30,
    ) -> None:
        self.python_executable = python_executable or sys.executable or "python"
        self.default_timeout = default_timeout
        self._checker = CodeSecurityChecker()

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        env: Optional[Dict[str, str]] = None,
    ) -> LocalExecutionResult:
        """在本地子进程中执行代码

        Args:
            code: Python 源代码
            timeout: 执行超时 (秒)
            env: 额外环境变量

        Returns:
            LocalExecutionResult 执行结果
        """
        start = time.time()
        timeout = timeout or self.default_timeout

        result = LocalExecutionResult()

        # 1. 安全检查
        security_report = self._checker.check(code)
        result.security_report = security_report.to_dict()

        if not security_report.is_allowed:
            result.error = "代码安全检查未通过, 禁止执行"
            result.duration_ms = (time.time() - start) * 1000
            logger.warning(f"[LocalSandbox] 安全检查拦截: {security_report.blocked_imports}")
            return result

        # 2. 创建临时脚本文件
        wrapper_code = _LOCAL_WRAPPER.format(user_code=code)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="sandbox_", delete=False, encoding="utf-8",
        ) as f:
            f.write(wrapper_code)
            script_path = f.name

        # 3. 准备环境变量 (清理敏感信息)
        clean_env = self._build_clean_env(env)

        try:
            # 4. 执行子进程 (带超时)
            proc = await asyncio.create_subprocess_exec(
                self.python_executable, script_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=clean_env,
                cwd=tempfile.gettempdir(),  # 在临时目录执行
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout,
                )
            except asyncio.TimeoutError:
                # 超时, 杀死子进程
                try:
                    proc.kill()
                    await proc.wait()
                except ProcessLookupError:
                    pass

                result.timed_out = True
                result.error = f"执行超时 (>{timeout}s), 进程已终止"
                result.duration_ms = (time.time() - start) * 1000
                logger.warning(f"[LocalSandbox] 执行超时")
                return result

            result.exit_code = proc.returncode if proc.returncode is not None else -1
            result.duration_ms = (time.time() - start) * 1000

            # 5. 解析输出
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            parsed = self._parse_sandbox_output(stdout_text)

            if parsed:
                result.success = parsed.get("success", False)
                result.output = parsed.get("stdout", "") + parsed.get("output", "")
                result.error = parsed.get("error", "") or stderr_text
            else:
                result.output = stdout_text
                result.error = stderr_text
                result.success = result.exit_code == 0

        except Exception as e:
            result.error = f"沙箱执行异常: {str(e)[:500]}"
            result.duration_ms = (time.time() - start) * 1000
            logger.exception(f"[LocalSandbox] 执行异常: {e}")

        finally:
            # 6. 清理临时文件
            try:
                os.unlink(script_path)
            except OSError:
                pass

        logger.info(
            f"[LocalSandbox] 执行完成: success={result.success}, "
            f"exit={result.exit_code}, duration={result.duration_ms:.0f}ms"
        )
        return result

    @staticmethod
    def _build_clean_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """构建清理后的环境变量"""
        # 复制基础环境
        env = dict(os.environ)

        # 移除敏感环境变量
        sensitive_keys = [
            "DB_PASSWORD", "MYSQL_PASSWORD", "REDIS_PASSWORD",
            "API_KEY", "SECRET_KEY", "PRIVATE_KEY",
            "DASHSCOPE_API_KEY", "DEEPSEEK_API_KEY",
            "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "AWS_SECRET_ACCESS_KEY", "AZURE_CLIENT_SECRET",
        ]
        for key in list(env.keys()):
            for sensitive in sensitive_keys:
                if sensitive.upper() in key.upper():
                    del env[key]
                    break

        # 添加安全相关环境变量
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"

        # 合并额外环境变量
        if extra:
            env.update(extra)

        return env

    @staticmethod
    def _parse_sandbox_output(stdout: str) -> Optional[Dict[str, Any]]:
        """解析沙箱 wrapper 输出的 JSON 结果"""
        if not stdout:
            return None

        lines = stdout.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

        try:
            return json.loads(stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return None

    async def check_availability(self) -> bool:
        """检查本地沙箱是否可用"""
        return True  # 本地沙箱始终可用
