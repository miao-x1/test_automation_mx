"""
Sandbox - 代码沙箱执行模块

提供安全的代码执行环境, 支持两种隔离模式:
  1. Docker 隔离执行 (推荐) — 完全容器化隔离
  2. 本地子进程沙箱 (降级) — 资源限制 + 超时控制

安全策略:
  - 代码静态分析 (AST 解析) 拦截危险操作
  - 禁止直接执行用户代码, 必须经过安全检查
  - 限制权限: 非root用户、只读文件系统、网络隔离
  - 限制时间: 执行超时自动终止
  - 限制资源: CPU/内存上限

架构:
  security.py       — 代码安全检查器 (AST 静态分析)
  docker_sandbox.py — Docker 容器隔离执行
  local_sandbox.py  — 本地子进程沙箱 (降级)
  executor.py       — 统一执行器 (自动选择 Docker/本地)
"""
from app.sandbox.security import (
    CodeSecurityChecker,
    SecurityReport,
    SecurityLevel,
    SecurityPolicy,
)
from app.sandbox.docker_sandbox import DockerSandbox
from app.sandbox.local_sandbox import LocalSandbox
from app.sandbox.executor import (
    SandboxExecutor,
    ExecutionResult,
    ExecutionConfig,
)

__all__ = [
    "CodeSecurityChecker",
    "SecurityReport",
    "SecurityLevel",
    "SecurityPolicy",
    "DockerSandbox",
    "LocalSandbox",
    "SandboxExecutor",
    "ExecutionResult",
    "ExecutionConfig",
]
