"""
代码执行 API 路由

端点:
  代码执行:
    POST   /run              生成代码 + 安全检查 + 沙箱执行 (主流程)
    POST   /generate         仅生成代码 (不执行)
    POST   /execute          直接执行已有代码 (经过安全检查)
    POST   /check-security   仅检查代码安全性

  沙箱管理:
    GET    /sandbox/status   沙箱可用性检查
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.auth import require_auth
from app.models.user import User
from app.schemas.response import Response

logger = logging.getLogger(__name__)

router = APIRouter()


# ================================================================
# Pydantic Schemas
# ================================================================

class RunRequest(BaseModel):
    """代码生成 + 执行请求"""
    user_request: str = Field(..., description="用户自然语言需求")
    task_type: str = Field(
        default="execute_code",
        description="任务类型: analyze_excel/process_data/generate_stats/visualize/execute_code",
    )
    data: Optional[Any] = Field(default=None, description="输入数据")
    timeout: int = Field(default=30, ge=1, le=120, description="执行超时 (秒)")
    mode: str = Field(default="auto", description="执行模式: auto/docker/local")
    extra_packages: Optional[List[str]] = Field(default=None, description="额外 pip 包")


class GenerateRequest(BaseModel):
    """仅生成代码请求"""
    user_request: str = Field(..., description="用户自然语言需求")
    task_type: str = Field(default="execute_code", description="任务类型")
    data: Optional[Any] = Field(default=None, description="输入数据")


class ExecuteRequest(BaseModel):
    """直接执行代码请求"""
    code: str = Field(..., description="Python 源代码")
    timeout: int = Field(default=30, ge=1, le=120, description="执行超时 (秒)")
    mode: str = Field(default="auto", description="执行模式: auto/docker/local")
    extra_packages: Optional[List[str]] = Field(default=None, description="额外 pip 包")


class CheckSecurityRequest(BaseModel):
    """安全检查请求"""
    code: str = Field(..., description="Python 源代码")


# ================================================================
# 代码执行端点
# ================================================================

@router.post("/run", summary="生成代码并执行")
async def run_code(
    payload: RunRequest,
    user: User = Depends(require_auth),
):
    """主流程: 用户需求 → LLM 生成代码 → 安全检查 → 沙箱执行

    支持的任务类型:
      - analyze_excel:  分析 Excel 数据
      - process_data:   处理测试数据
      - generate_stats: 生成统计结果
      - visualize:      数据可视化
      - execute_code:   通用代码执行
    """
    try:
        from app.domains.code.agent import CodeAgent

        agent = CodeAgent()
        result = await agent.handle_run({
            "user_request": payload.user_request,
            "task_type": payload.task_type,
            "data": payload.data,
            "timeout": payload.timeout,
            "mode": payload.mode,
            "extra_packages": payload.extra_packages or [],
        })

        return Response(data=result)

    except Exception as e:
        logger.exception(f"[code/run] 执行失败: {e}")
        return Response(code=500, message=f"执行失败: {str(e)}")


@router.post("/generate", summary="仅生成代码")
async def generate_code(
    payload: GenerateRequest,
    user: User = Depends(require_auth),
):
    """仅生成代码, 不执行。返回代码和安全检查报告。"""
    try:
        from app.domains.code.agent import CodeAgent

        agent = CodeAgent()
        result = await agent.handle_generate_code({
            "user_request": payload.user_request,
            "task_type": payload.task_type,
            "data": payload.data,
        })

        return Response(data=result)

    except Exception as e:
        logger.exception(f"[code/generate] 生成失败: {e}")
        return Response(code=500, message=f"生成失败: {str(e)}")


@router.post("/execute", summary="直接执行已有代码")
async def execute_code(
    payload: ExecuteRequest,
    user: User = Depends(require_auth),
):
    """直接执行已有代码 (仍经过安全检查)"""
    try:
        from app.domains.code.agent import CodeAgent

        agent = CodeAgent()
        result = await agent.handle_execute({
            "code": payload.code,
            "timeout": payload.timeout,
            "mode": payload.mode,
            "extra_packages": payload.extra_packages or [],
        })

        return Response(data=result)

    except Exception as e:
        logger.exception(f"[code/execute] 执行失败: {e}")
        return Response(code=500, message=f"执行失败: {str(e)}")


@router.post("/check-security", summary="检查代码安全性")
async def check_security(
    payload: CheckSecurityRequest,
    user: User = Depends(require_auth),
):
    """检查代码安全性, 不执行代码。"""
    try:
        from app.domains.code.agent import CodeAgent

        agent = CodeAgent()
        result = await agent.handle_check_security({
            "code": payload.code,
        })

        return Response(data=result)

    except Exception as e:
        logger.exception(f"[code/check-security] 检查失败: {e}")
        return Response(code=500, message=f"检查失败: {str(e)}")


# ================================================================
# 沙箱管理端点
# ================================================================

@router.get("/sandbox/status", summary="沙箱可用性检查")
async def sandbox_status(
    user: User = Depends(require_auth),
):
    """检查沙箱执行环境的可用性"""
    try:
        from app.sandbox.executor import SandboxExecutor

        executor = SandboxExecutor()
        availability = await executor.check_availability()

        return Response(data={
            "docker_available": availability["docker"],
            "local_available": availability["local"],
            "recommended_mode": "docker" if availability["docker"] else "local",
            "security_policy": {
                "allowed_modules": list(sorted(_get_allowed_modules())),
                "blocked_modules": list(sorted(_get_blocked_modules())),
                "max_code_lines": 500,
                "max_code_chars": 50000,
                "timeout_default": 30,
                "memory_limit_default": "256m",
                "cpu_limit_default": "1.0",
            },
        })

    except Exception as e:
        logger.exception(f"[code/sandbox/status] 检查失败: {e}")
        return Response(code=500, message=f"检查失败: {str(e)}")


# ================================================================
# 辅助函数
# ================================================================

def _get_allowed_modules() -> set:
    """获取允许的模块列表"""
    try:
        from app.sandbox.security import SecurityPolicy
        return SecurityPolicy.ALLOWED_MODULES
    except ImportError:
        return set()


def _get_blocked_modules() -> set:
    """获取禁止的模块列表"""
    try:
        from app.sandbox.security import SecurityPolicy
        return SecurityPolicy.BLOCKED_MODULES
    except ImportError:
        return set()
