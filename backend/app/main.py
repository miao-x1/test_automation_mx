"""
FastAPI应用入口
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.logger import log
from app.db.database import init_db, close_db
from app.api import api_router


def _cleanup_milvus_lock():
    """清理Milvus Lite残留锁文件"""
    from app.db.milvus_client import _cleanup_lock_file
    _cleanup_lock_file()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    log.info(f"应用启动中... | 环境: {settings.APP_ENV}")

    # 创建上传目录
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)

    # 清理Milvus残留锁文件（防止上次异常退出后锁文件残留）
    _cleanup_milvus_lock()

    # 架构合规检查：禁止 Agent 直接导入数据层
    from app.services.context_router.access_checker import RAGAccessChecker
    RAGAccessChecker.check_at_startup()

    # Agent 平台化：统一注册所有 Agent
    from app.agents.factory import AgentRegistry
    AgentRegistry.auto_register()

    # MessageBus 广播模式：注册默认订阅者（审计 + 错误检测 + 事件分发）
    from app.agent.core.event_router import register_default_subscribers
    register_default_subscribers()

    # Pipeline 事件驱动：注册 Pipeline 事件监听器
    from app.services.case.pipeline import CasePipeline
    CasePipeline.register_pipeline_events()

    # 初始化数据库
    init_db()

    # 初始化 Provider
    from app.core.providers import init_providers
    init_providers()
    log.info("Provider 初始化完成")

    # Milvus延迟初始化：不在启动时连接，等首次使用时自动建立
    # 这样避免多进程启动时抢锁
    log.info(f"{settings.APP_NAME} v{settings.APP_VERSION} 启动成功")

    # 启动定时任务调度器
    try:
        from app.agents.factory import AgentRegistry
        scheduler_agent = AgentRegistry.create("scheduler_agent")
        scheduler_agent.start()
    except Exception as e:
        log.warning(f"定时任务调度器启动失败: {e}")

    # 启动 TaskQueue（异步执行引擎）
    try:
        from app.core.task_queue import TaskQueue
        queue = TaskQueue()
        await queue.start(worker_count=3)
    except Exception as e:
        log.warning(f"TaskQueue 启动失败: {e}")

    # 启动 ExecutionQueue（接口测试执行引擎）
    try:
        from app.services.execution.redis_queue import get_execution_queue
        eq = get_execution_queue()
        await eq.start(worker_count=3)
    except Exception as e:
        log.warning(f"ExecutionQueue 启动失败: {e}")

    yield

    # 停止 TaskQueue
    try:
        from app.core.task_queue import TaskQueue
        queue = TaskQueue()
        await queue.stop()
    except Exception:
        pass

    # 停止 ExecutionQueue
    try:
        from app.services.execution.redis_queue import get_execution_queue
        eq = get_execution_queue()
        await eq.stop()
    except Exception:
        pass

    # 关闭时执行
    try:
        from app.agents.factory import AgentRegistry
        scheduler_agent = AgentRegistry.create("scheduler_agent")
        scheduler_agent.stop()
    except Exception:
        pass
    try:
        from app.db.milvus_client import _milvus_client, _cleanup_lock_file
        if _milvus_client is not None:
            _milvus_client.close()
        # 关闭时清理锁文件
        _cleanup_lock_file()
    except Exception:
        pass
    close_db()
    log.info("应用已关闭")


# 创建FastAPI应用实例
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI驱动的UI自动化测试平台",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# 注册路由
app.include_router(api_router)

# 注册MCP路由（SSE + Streamable HTTP）
from app.mcp import setup_mcp_routes
setup_mcp_routes(app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=True,
        reload_dirs=["app"],
        reload_excludes=["uploads/*", "reports/*", "scripts/*"],
    )
