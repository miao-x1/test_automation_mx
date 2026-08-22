"""
Docker 隔离执行沙箱

在 Docker 容器中隔离执行 Python 代码, 提供操作系统级隔离:
  - 文件系统隔离: 只读 root + 临时可写目录
  - 网络隔离: --network none (禁止网络访问)
  - 用户隔离: 非 root 用户运行
  - 资源限制: CPU / 内存 / PID 上限
  - 时间限制: 执行超时自动终止并清理容器
  - 自动清理: 执行完毕后自动删除容器

使用 docker CLI (通过 subprocess) 而非 docker SDK, 避免额外依赖。

使用方式:
    sandbox = DockerSandbox()
    result = await sandbox.execute(code, timeout=30, memory_limit="256m")
"""
import asyncio
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.sandbox.security import CodeSecurityChecker, SecurityReport

logger = logging.getLogger(__name__)


@dataclass
class DockerExecutionResult:
    """Docker 执行结果"""
    success: bool = False
    output: str = ""
    error: str = ""
    exit_code: int = -1
    duration_ms: float = 0
    timed_out: bool = False
    container_id: str = ""
    security_report: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output[:10000],  # 限制输出长度
            "error": self.error[:5000],
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 2),
            "timed_out": self.timed_out,
            "container_id": self.container_id[:12] if self.container_id else "",
            "security_report": self.security_report,
        }


# 沙箱内执行的 wrapper 脚本
# 捕获 stdout/stderr, 以 JSON 格式输出结果
_SANDBOX_WRAPPER = '''"""Sandbox wrapper — 自动生成, 请勿修改"""
import sys
import json
import traceback
import io

_result = {{"success": False, "output": "", "error": "", "stdout": "", "stderr": ""}}

# 捕获 stdout/stderr
_stdout_buf = io.StringIO()
_stderr_buf = io.StringIO()
_old_stdout = sys.stdout
_old_stderr = sys.stderr

try:
    sys.stdout = _stdout_buf
    sys.stderr = _stderr_buf

    # 执行用户代码
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

# 输出结果到 stdout (JSON)
print(json.dumps(_result, ensure_ascii=False, default=str))
'''


class DockerSandbox:
    """Docker 容器隔离沙箱

    在 Docker 容器中执行 Python 代码, 提供完整隔离。

    安全措施:
      1. 代码先经过 CodeSecurityChecker 静态分析
      2. 容器以非 root 用户运行 (--user 65534:65534)
      3. 文件系统只读 (--read-only) + 临时可写 tmpfs
      4. 网络禁用 (--network none)
      5. 资源限制 (--cpus / --memory / --pids-limit)
      6. 执行超时自动终止 (--timeout + asyncio 超时)
      7. 禁止特权 (--security-opt no-new-privileges)
      8. 容器自动删除 (--rm)

    使用方式:
        sandbox = DockerSandbox(image="python:3.11-slim")
        result = await sandbox.execute(code, timeout=30)
    """

    def __init__(
        self,
        image: str = "python:3.11-slim",
        default_timeout: int = 30,
        default_memory: str = "256m",
        default_cpus: str = "1.0",
    ) -> None:
        self.image = image
        self.default_timeout = default_timeout
        self.default_memory = default_memory
        self.default_cpus = default_cpus
        self._checker = CodeSecurityChecker()

    async def execute(
        self,
        code: str,
        timeout: Optional[int] = None,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[str] = None,
        extra_packages: Optional[List[str]] = None,
    ) -> DockerExecutionResult:
        """在 Docker 容器中执行代码

        Args:
            code: Python 源代码
            timeout: 执行超时 (秒)
            memory_limit: 内存限制 (如 "256m", "1g")
            cpu_limit: CPU 限制 (如 "0.5", "1.0")
            extra_packages: 需要安装的额外 pip 包

        Returns:
            DockerExecutionResult 执行结果
        """
        import time
        start = time.time()

        timeout = timeout or self.default_timeout
        memory_limit = memory_limit or self.default_memory
        cpu_limit = cpu_limit or self.default_cpus

        result = DockerExecutionResult()

        # 1. 安全检查
        security_report = self._checker.check(code)
        result.security_report = security_report.to_dict()

        if not security_report.is_allowed:
            result.error = "代码安全检查未通过, 禁止执行"
            result.duration_ms = (time.time() - start) * 1000
            logger.warning(f"[DockerSandbox] 安全检查拦截: {security_report.blocked_imports}")
            return result

        # 2. 检查 Docker 是否可用
        if not await self._is_docker_available():
            result.error = "Docker 不可用, 请降级使用 LocalSandbox"
            result.duration_ms = (time.time() - start) * 1000
            return result

        # 3. 创建临时脚本文件
        wrapper_code = _SANDBOX_WRAPPER.format(user_code=code)

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="sandbox_", delete=False, encoding="utf-8",
        ) as f:
            f.write(wrapper_code)
            script_path = f.name

        container_name = f"sandbox-{uuid.uuid4().hex[:8]}"

        try:
            # 4. 构建 docker run 命令
            cmd = self._build_docker_command(
                script_path=script_path,
                container_name=container_name,
                timeout=timeout,
                memory_limit=memory_limit,
                cpu_limit=cpu_limit,
                extra_packages=extra_packages,
            )

            # 5. 执行 (带超时)
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout + 10,  # 额外10秒给容器启动
                )
            except asyncio.TimeoutError:
                # 超时, 杀死容器
                await self._kill_container(container_name)
                result.timed_out = True
                result.error = f"执行超时 (>{timeout}s), 容器已终止"
                result.duration_ms = (time.time() - start) * 1000
                logger.warning(f"[DockerSandbox] 执行超时: {container_name}")
                return result

            result.exit_code = proc.returncode if proc.returncode is not None else -1
            result.duration_ms = (time.time() - start) * 1000

            # 6. 解析输出
            stdout_text = stdout.decode("utf-8", errors="replace") if stdout else ""
            stderr_text = stderr.decode("utf-8", errors="replace") if stderr else ""

            # 尝试从 stdout 解析 JSON 结果
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
            logger.exception(f"[DockerSandbox] 执行异常: {e}")

        finally:
            # 7. 清理临时文件
            try:
                os.unlink(script_path)
            except OSError:
                pass

        logger.info(
            f"[DockerSandbox] 执行完成: success={result.success}, "
            f"exit={result.exit_code}, duration={result.duration_ms:.0f}ms"
        )
        return result

    def _build_docker_command(
        self,
        script_path: str,
        container_name: str,
        timeout: int,
        memory_limit: str,
        cpu_limit: str,
        extra_packages: Optional[List[str]],
    ) -> List[str]:
        """构建 docker run 命令"""
        cmd = [
            "docker", "run",
            "--rm",                          # 执行后自动删除容器
            "--name", container_name,
            "--network", "none",             # 禁止网络访问
            "--read-only",                   # 只读文件系统
            "--tmpfs", "/tmp:rw,size=64m",   # 临时可写目录
            "--user", "65534:65534",         # 非 root 用户 (nobody)
            "--security-opt", "no-new-privileges",  # 禁止提权
            "--memory", memory_limit,        # 内存限制
            "--cpus", cpu_limit,             # CPU 限制
            "--pids-limit", "64",            # 进程数限制
            # --storage-opt 不在所有 Docker 版本可用, 用 tmpfs 替代
        ]

        # 挂载脚本文件 (只读)
        container_script = "/tmp/sandbox_script.py"
        cmd.extend(["-v", f"{script_path}:{container_script}:ro"])

        # 环境变量
        cmd.extend(["-e", "PYTHONUNBUFFERED=1"])
        cmd.extend(["-e", "PYTHONDONTWRITEBYTECODE=1"])

        # 镜像
        cmd.append(self.image)

        # 执行命令
        if extra_packages:
            # 需要安装额外包
            pip_install = " ".join(extra_packages)
            cmd.extend([
                "sh", "-c",
                f"pip install --quiet {pip_install} 2>/dev/null; "
                f"python {container_script}",
            ])
        else:
            cmd.extend(["python", container_script])

        return cmd

    async def _is_docker_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "info",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
            return proc.returncode == 0
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            return False

    async def _kill_container(self, container_name: str) -> None:
        """强制终止容器"""
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "kill", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.communicate(), timeout=5)
        except (asyncio.TimeoutError, FileNotFoundError, OSError):
            pass

    @staticmethod
    def _parse_sandbox_output(stdout: str) -> Optional[Dict[str, Any]]:
        """解析沙箱 wrapper 输出的 JSON 结果"""
        if not stdout:
            return None

        # wrapper 在最后一行输出 JSON
        lines = stdout.strip().split("\n")
        for line in reversed(lines):
            line = line.strip()
            if line.startswith("{"):
                try:
                    import json
                    return json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue

        # 尝试解析整个输出
        try:
            import json
            return json.loads(stdout.strip())
        except (json.JSONDecodeError, ValueError):
            return None

    async def check_availability(self) -> bool:
        """检查 Docker 沙箱是否可用 (公开接口)"""
        return await self._is_docker_available()
