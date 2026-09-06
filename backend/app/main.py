"""
FastAPI应用入口
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.core.exceptions import BusinessError
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
    from app.api.admin import apply_persisted_llm_settings
    apply_persisted_llm_settings()
    from app.core.security_checks import assert_production_secrets
    assert_production_secrets()
    log.info(
        f"启动就绪状态 | APP_READY=true | AI_READY={'true' if settings.ai_configured else 'false'}"
    )

    # 创建上传目录
    Path(settings.UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.REPORT_DIR).mkdir(parents=True, exist_ok=True)
    Path(settings.DATA_DIR).mkdir(parents=True, exist_ok=True)

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
    from app.core.bootstrap_admin import ensure_seed_admin
    ensure_seed_admin()

    # 初始化 Provider
    from app.core.providers import init_providers
    init_providers()
    log.info("Provider 初始化完成")

    # ApplicationContainer 初始化 — 预热重量级服务 (LLM/Embedding/Vision/Marker)
    # 将 "首次请求时初始化" 提前到 "应用启动时初始化"
    try:
        from app.bootstrap import get_initializer
        await get_initializer().initialize_all()
    except Exception as e:
        log.warning(f"ApplicationContainer 初始化失败 (非致命): {e}", exc_info=True)

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

    # 启动企业级 Agent Runtime (TaskDispatcher + WorkerPool + Collector + Scheduler)
    try:
        from app.runtime.enterprise import (
            get_task_dispatcher, get_worker_pool,
            get_response_collector, get_stream_publisher,
            get_task_scheduler, DispatcherMode,
        )
        # 初始化各组件
        dispatcher = get_task_dispatcher(mode=DispatcherMode.STANDALONE)
        pool = get_worker_pool(size=4)
        collector = get_response_collector()
        publisher = get_stream_publisher()
        scheduler = get_task_scheduler(dispatcher=dispatcher)

        # 注入依赖 (Dispatcher ↔ WorkerPool)
        dispatcher.set_worker_pool(pool)
        pool.set_dispatcher(dispatcher)
        # Collector → StreamPublisher
        collector.set_stream_publisher(publisher)

        # 启动
        await pool.start()
        await dispatcher.start()
        await scheduler.start()
        log.info("企业级 Agent Runtime 启动完成 (Dispatcher + WorkerPool + Collector + Scheduler)")
    except Exception as e:
        log.warning(f"企业级 Agent Runtime 启动失败: {e}", exc_info=True)

    # 启动 Runtime v2 (统一 Agent 运行时 — Dispatcher/Worker/Collector/SSE)
    try:
        from app.runtime.v2 import start_runtime
        await start_runtime(worker_count=4)
        log.info("Runtime v2 启动完成 (Dispatcher → WorkerPool → AgentWorker → Collector → SSE)")
    except Exception as e:
        log.warning(f"Runtime v2 启动失败: {e}", exc_info=True)

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

    # 停止企业级 Agent Runtime
    try:
        from app.runtime.enterprise import (
            get_task_dispatcher, get_worker_pool, get_task_scheduler,
        )
        scheduler = get_task_scheduler()
        await scheduler.stop()
        dispatcher = get_task_dispatcher()
        await dispatcher.stop()
        pool = get_worker_pool()
        await pool.stop()
        log.info("企业级 Agent Runtime 已停止")
    except Exception:
        pass

    # 停止 Runtime v2
    try:
        from app.runtime.v2 import stop_runtime
        await stop_runtime()
        log.info("Runtime v2 已停止")
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
    # 关闭 ApplicationContainer — 释放重量级服务资源
    try:
        from app.bootstrap import get_initializer
        await get_initializer().shutdown_all()
    except Exception as e:
        log.warning(f"ApplicationContainer 关闭失败: {e}")

    close_db()
    log.info("应用已关闭")


# 创建FastAPI应用实例
_docs_url = "/docs" if settings.docs_enabled else None
_redoc_url = "/redoc" if settings.docs_enabled else None
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="AI驱动的UI自动化测试平台",
    lifespan=lifespan,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
)

# 操作日志 / 鉴权 / 限流 / CORS
# Starlette 后注册的中间件先执行，CORS 必须在最外层以放行 OPTIONS
from app.core.operation_log_middleware import OperationLogMiddleware
from app.core.auth_gate import AuthGateMiddleware
from app.core.rate_limit import RateLimitMiddleware
app.add_middleware(OperationLogMiddleware)
app.add_middleware(AuthGateMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(api_router)

_fixture_dir = Path(__file__).resolve().parents[1] / "test-fixtures" / "basic-web-app"
if _fixture_dir.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/fixtures/basic-web-app", StaticFiles(directory=str(_fixture_dir), html=True), name="basic_web_app")

# 注册MCP路由（SSE + Streamable HTTP）；生产默认关闭
if settings.mcp_enabled:
    from app.mcp import setup_mcp_routes
    setup_mcp_routes(app)
else:
    log.info("MCP 路由未注册（ENABLE_MCP=false 或生产默认关闭）")


# ============================================================
# 全局业务异常处理器
# ============================================================
# 将 BusinessError 子类 (NotFoundError / ConflictError / StateError / ValidationError
# 及各模块专用异常) 转为标准 Response 结构, 避免 500 Internal Server Error。

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """兜底异常处理器: 未预期异常统一转为 500"""
    from fastapi.responses import JSONResponse
    log.error(f"未处理异常: {type(exc).__name__}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "code": 500,
            "message": f"服务器内部错误: {type(exc).__name__}",
            "data": {"error_code": "INTERNAL_ERROR"},
        },
    )


@app.exception_handler(BusinessError)
async def business_error_handler(request, exc: BusinessError):
    """统一业务异常处理器

    把 BusinessError 子类转为标准 Response 结构
    """
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.message,
            "data": {
                "error_code": exc.code,
                "details": exc.details,
            },
        },
    )


if __name__ == "__main__":
    import uvicorn
    # PyCharm 调试模式: 默认关闭 reload，避免断点失效
    # 需要 hot-reload 时设置环境变量 UVICORN_RELOAD=true
    reload_flag = os.getenv("UVICORN_RELOAD", "false").lower() == "true"
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=reload_flag,
        reload_dirs=["app"] if reload_flag else None,
        reload_excludes=["uploads/*", "reports/*", "scripts/*"] if reload_flag else None,
    )
