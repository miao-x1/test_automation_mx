"""
统一沙箱执行器

自动选择 Docker 隔离执行或本地子进程沙箱:
  1. 检测 Docker 是否可用 → 优先使用 DockerSandbox (最高隔离级别)
  2. Docker 不可用 → 降级使用 LocalSandbox (进程级隔离)
  3. 两者都不可用 → 返回错误

统一接口:
  executor = SandboxExecutor()
  result = await executor.execute(code, timeout=30)

安全流程 (所有路径都执行):
  代码 → CodeSecurityChecker 静态分析 → 通过 → Sandbox 执行 → 返回结果
                                      → 拒绝 → 返回安全报告 (不执行)
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from app.sandbox.security import CodeSecurityChecker, SecurityReport, SecurityLevel
from app.sandbox.docker_sandbox import DockerSandbox, DockerExecutionResult
from app.sandbox.local_sandbox import LocalSandbox, LocalExecutionResult

logger = logging.getLogger(__name__)


class ExecutionMode(str, Enum):
    """执行模式"""
    DOCKER = "docker"
    LOCAL = "local"
    AUTO = "auto"  # 自动选择


@dataclass
class ExecutionConfig:
    """执行配置"""
    mode: ExecutionMode = ExecutionMode.AUTO
    timeout: int = 30
    memory_limit: str = "256m"
    cpu_limit: str = "1.0"
    # Docker 镜像
    docker_image: str = "python:3.11-slim"
    # 额外 pip 包
    extra_packages: Optional[List[str]] = None
    # Python 可执行文件 (本地沙箱)
    python_executable: Optional[str] = None
    # 额外环境变量
    env: Optional[Dict[str, str]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "timeout": self.timeout,
            "memory_limit": self.memory_limit,
            "cpu_limit": self.cpu_limit,
            "docker_image": self.docker_image,
            "extra_packages": self.extra_packages or [],
        }


@dataclass
class ExecutionResult:
    """统一执行结果"""
    success: bool = False
    output: str = ""
    error: str = ""
    exit_code: int = -1
    duration_ms: float = 0
    timed_out: bool = False
    # 实际使用的执行模式
    execution_mode: str = ""
    # 安全检查报告
    security_report: Optional[Dict[str, Any]] = None
    # 代码是否被安全检查拦截
    security_blocked: bool = False
    # 生成的代码 (CodeAgent 场景)
    generated_code: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output[:10000],
            "error": self.error[:5000],
            "exit_code": self.exit_code,
            "duration_ms": round(self.duration_ms, 2),
            "timed_out": self.timed_out,
            "execution_mode": self.execution_mode,
            "security_blocked": self.security_blocked,
            "security_report": self.security_report,
            "generated_code": self.generated_code[:5000],
        }


class SandboxExecutor:
    """统一沙箱执行器

    自动选择 Docker 或本地沙箱执行代码。

    安全保证:
      1. 所有代码执行前必须通过 CodeSecurityChecker 静态分析
      2. 禁止直接执行未经安全检查的代码
      3. Docker 模式: 容器隔离 + 网络禁用 + 非 root 用户 + 资源限制
      4. 本地模式: 进程隔离 + 超时控制 + 环境变量清理
      5. 两种模式都有执行超时自动终止

    使用方式:
        # 自动选择模式
        executor = SandboxExecutor()
        result = await executor.execute(code, timeout=30)

        # 强制 Docker 模式
        executor = SandboxExecutor(mode=ExecutionMode.DOCKER)

        # 强制本地模式
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
    """

    def __init__(
        self,
        mode: ExecutionMode = ExecutionMode.AUTO,
        config: Optional[ExecutionConfig] = None,
    ) -> None:
        self.mode = mode
        self.config = config or ExecutionConfig(mode=mode)
        self._checker = CodeSecurityChecker()
        self._docker_sandbox: Optional[DockerSandbox] = None
        self._local_sandbox: Optional[LocalSandbox] = None
        self._docker_available: Optional[bool] = None  # 缓存 Docker 可用性

    async def execute(
        self,
        code: str,
        config: Optional[ExecutionConfig] = None,
    ) -> ExecutionResult:
        """执行代码 (统一入口)

        流程:
          1. 安全检查 (AST 静态分析)
          2. 选择执行模式 (Docker / Local)
          3. 执行代码
          4. 返回统一结果

        Args:
            code: Python 源代码
            config: 执行配置 (覆盖默认配置)

        Returns:
            ExecutionResult 统一执行结果
        """
        start = time.time()
        effective_config = config or self.config
        result = ExecutionResult()

        # ---- 1. 安全检查 ----
        security_report = self._checker.check(code)
        result.security_report = security_report.to_dict()

        if not security_report.is_allowed:
            result.security_blocked = True
            result.error = "代码安全检查未通过, 禁止执行"
            result.duration_ms = (time.time() - start) * 1000
            logger.warning(
                f"[SandboxExecutor] 安全检查拦截: "
                f"level={security_report.level}, "
                f"blocked={security_report.blocked_imports}"
            )
            return result

        # ---- 2. 选择执行模式 ----
        execution_mode = await self._select_mode(effective_config)
        result.execution_mode = execution_mode

        # ---- 3. 执行代码 ----
        if execution_mode == "docker":
            docker_result = await self._get_docker_sandbox(effective_config).execute(
                code=code,
                timeout=effective_config.timeout,
                memory_limit=effective_config.memory_limit,
                cpu_limit=effective_config.cpu_limit,
                extra_packages=effective_config.extra_packages,
            )
            result.success = docker_result.success
            result.output = docker_result.output
            result.error = docker_result.error
            result.exit_code = docker_result.exit_code
            result.timed_out = docker_result.timed_out

        elif execution_mode == "local":
            local_result = await self._get_local_sandbox(effective_config).execute(
                code=code,
                timeout=effective_config.timeout,
                env=effective_config.env,
            )
            result.success = local_result.success
            result.output = local_result.output
            result.error = local_result.error
            result.exit_code = local_result.exit_code
            result.timed_out = local_result.timed_out

        else:
            result.error = "无可用的沙箱执行环境 (Docker 和本地沙箱均不可用)"
            result.duration_ms = (time.time() - start) * 1000
            return result

        result.duration_ms = (time.time() - start) * 1000
        logger.info(
            f"[SandboxExecutor] 执行完成: mode={execution_mode}, "
            f"success={result.success}, duration={result.duration_ms:.0f}ms"
        )
        return result

    async def execute_with_security_report(
        self,
        code: str,
        config: Optional[ExecutionConfig] = None,
    ) -> tuple:
        """执行代码并返回完整安全报告

        Returns:
            (ExecutionResult, SecurityReport)
        """
        result = await self.execute(code, config)
        security_report = self._checker.check(code)
        return result, security_report

    async def check_security(self, code: str) -> SecurityReport:
        """仅执行安全检查, 不执行代码"""
        return self._checker.check(code)

    async def check_availability(self) -> Dict[str, bool]:
        """检查各执行模式的可用性"""
        docker_ok = await self._check_docker()
        return {
            "docker": docker_ok,
            "local": True,  # 本地沙箱始终可用
            "auto": docker_ok or True,
        }

    # ================================================================
    # 内部方法
    # ================================================================

    async def _select_mode(self, config: ExecutionConfig) -> str:
        """选择执行模式"""
        if config.mode == ExecutionMode.DOCKER:
            if await self._check_docker():
                return "docker"
            logger.warning("[SandboxExecutor] Docker 不可用, 降级到本地沙箱")
            return "local"

        if config.mode == ExecutionMode.LOCAL:
            return "local"

        # AUTO: 优先 Docker
        if await self._check_docker():
            return "docker"
        return "local"

    async def _check_docker(self) -> bool:
        """检查 Docker 是否可用 (带缓存)"""
        if self._docker_available is not None:
            return self._docker_available

        sandbox = self._get_docker_sandbox(self.config)
        self._docker_available = await sandbox.check_availability()
        return self._docker_available

    def _get_docker_sandbox(self, config: ExecutionConfig) -> DockerSandbox:
        """获取 Docker 沙箱实例"""
        if self._docker_sandbox is None:
            self._docker_sandbox = DockerSandbox(
                image=config.docker_image,
                default_timeout=config.timeout,
                default_memory=config.memory_limit,
                default_cpus=config.cpu_limit,
            )
        return self._docker_sandbox

    def _get_local_sandbox(self, config: ExecutionConfig) -> LocalSandbox:
        """获取本地沙箱实例"""
        if self._local_sandbox is None:
            self._local_sandbox = LocalSandbox(
                python_executable=config.python_executable,
                default_timeout=config.timeout,
            )
        return self._local_sandbox
