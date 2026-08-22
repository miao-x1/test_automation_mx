"""
ServiceInitializer — 服务启动初始化器

在 FastAPI lifespan 启动阶段调用, 预先初始化所有重量级服务,
将 "首次请求时初始化" 提前到 "应用启动时初始化"。

启动顺序 (依赖优先):
    1. LLM Gateway     — 初始化 Provider 链 (Qwen/DeepSeek/OpenAI/Ollama/Mock)
    2. Embedding Service — 创建 DashScope/Mock 向量化实例
    3. Vision Service   — 预建 httpx.AsyncClient 共享客户端
    4. Marker Service    — 预加载 pdfplumber / PyMuPDF / python-docx 模块

关闭顺序 (逆序释放):
    4. Marker Service     — 清理缓存
    3. Vision Service     — 关闭 httpx 客户端
    2. Embedding Service  — 无需显式关闭
    1. LLM Gateway        — 无需显式关闭

使用方式:
    # main.py lifespan 启动
    initializer = get_initializer()
    await initializer.initialize_all()

    # main.py lifespan 关闭
    await initializer.shutdown_all()
"""
import logging
import time
from typing import Optional

from app.bootstrap.container import (
    ApplicationContainer,
    MarkerService,
    VisionService,
    get_container,
)

logger = logging.getLogger(__name__)


class ServiceInitializer:
    """服务初始化器

    负责 ApplicationContainer 中各服务的预初始化和关闭。
    每个服务初始化独立 try/except, 单个服务失败不阻断整体启动。
    """

    def __init__(self, container: Optional[ApplicationContainer] = None) -> None:
        self._container = container or get_container()

    async def initialize_all(self) -> ApplicationContainer:
        """初始化所有服务 (启动时调用)

        Returns:
            初始化完成的 ApplicationContainer
        """
        container = self._container
        logger.info("=" * 60)
        logger.info("[Bootstrap] ApplicationContainer 初始化开始")
        logger.info("=" * 60)

        total_start = time.time()

        # 1. LLM Gateway (Provider 链)
        await self._init_llm_gateway()

        # 2. Embedding Service
        await self._init_embedding_service()

        # 3. Vision Service (httpx 客户端)
        await self._init_vision_service()

        # 4. Marker Service (解析器模块预加载)
        self._init_marker_service()

        container._initialized = True
        total_ms = round((time.time() - total_start) * 1000, 2)
        container._init_times["_total"] = total_ms

        logger.info("-" * 60)
        logger.info(f"[Bootstrap] ApplicationContainer 初始化完成 | 总耗时: {total_ms}ms")
        for svc, elapsed in container.init_times.items():
            if svc != "_total":
                status = "OK" if _is_service_ready(container, svc) else "FAIL"
                logger.info(f"  {svc:25s} {elapsed:>8.2f}ms  [{status}]")
        logger.info("=" * 60)

        return container

    async def _init_llm_gateway(self) -> None:
        """初始化 LLM Gateway — 加载 Provider 链"""
        start = time.time()
        try:
            from app.llm import get_gateway
            from app.core.config import settings

            gateway = get_gateway()
            gateway.initialize(settings, force=True)
            self._container._llm_gateway = gateway
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["llm_gateway"] = elapsed
            logger.info(f"  [OK] LLM Gateway      | {elapsed:>8.2f}ms | providers: {len(gateway._factory.list_providers(include_disabled=True))}")
        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["llm_gateway"] = elapsed
            logger.error(f"  [FAIL] LLM Gateway    | {elapsed:>8.2f}ms | {e}", exc_info=True)

    async def _init_embedding_service(self) -> None:
        """初始化 Embedding Service — 创建向量化实例"""
        start = time.time()
        try:
            from app.rag.embedding.factory import get_embedding_factory

            factory = get_embedding_factory()
            embedding = factory.get_embedding()  # 触发实例创建
            self._container._embedding_service = embedding
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["embedding_service"] = elapsed
            logger.info(f"  [OK] Embedding Service| {elapsed:>8.2f}ms | type: {type(embedding).__name__}")
        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["embedding_service"] = elapsed
            logger.error(f"  [FAIL] Embedding     | {elapsed:>8.2f}ms | {e}", exc_info=True)

    async def _init_vision_service(self) -> None:
        """初始化 Vision Service — 预建共享 httpx 客户端"""
        start = time.time()
        try:
            from app.core.config import settings

            vision = VisionService(
                api_key=settings.QWEN_API_KEY,
                api_url=settings.QWEN_API_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                model=settings.QWEN_MODEL or "qwen-vl-plus",
            )
            await vision.initialize()
            self._container._vision_service = vision
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["vision_service"] = elapsed
            logger.info(f"  [OK] Vision Service  | {elapsed:>8.2f}ms | model: {vision.model}")
        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["vision_service"] = elapsed
            logger.error(f"  [FAIL] Vision Service| {elapsed:>8.2f}ms | {e}", exc_info=True)

    def _init_marker_service(self) -> None:
        """初始化 Marker Service — 预加载解析器模块"""
        start = time.time()
        try:
            marker = MarkerService()
            marker.initialize()
            self._container._marker_service = marker
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["marker_service"] = elapsed
            loaded = ", ".join(f"{k}={v}" for k, v in marker.loaded_modules.items())
            logger.info(f"  [OK] Marker Service  | {elapsed:>8.2f}ms | {loaded}")
        except Exception as e:
            elapsed = round((time.time() - start) * 1000, 2)
            self._container._init_times["marker_service"] = elapsed
            logger.error(f"  [FAIL] Marker Service| {elapsed:>8.2f}ms | {e}", exc_info=True)

    async def shutdown_all(self) -> None:
        """关闭所有服务 (应用关闭时调用)"""
        container = self._container
        logger.info("=" * 60)
        logger.info("[Bootstrap] ApplicationContainer 关闭开始")
        logger.info("=" * 60)

        # 逆序关闭
        # 4. Marker Service
        if container._marker_service is not None:
            try:
                container._marker_service.shutdown()
            except Exception as e:
                logger.warning(f"Marker Service shutdown error: {e}")

        # 3. Vision Service
        if container._vision_service is not None:
            try:
                await container._vision_service.shutdown()
            except Exception as e:
                logger.warning(f"Vision Service shutdown error: {e}")

        # 2. Embedding Service — 无需显式关闭
        # 1. LLM Gateway — 无需显式关闭

        container._initialized = False
        logger.info("[Bootstrap] ApplicationContainer 关闭完成")


def _is_service_ready(container: ApplicationContainer, service_name: str) -> bool:
    """检查服务是否初始化成功"""
    mapping = {
        "llm_gateway": container._llm_gateway,
        "embedding_service": container._embedding_service,
        "vision_service": container._vision_service,
        "marker_service": container._marker_service,
    }
    return mapping.get(service_name) is not None


# ------------------------------------------------------------------ #
#  单例                                                               #
# ------------------------------------------------------------------ #

_initializer: Optional[ServiceInitializer] = None


def get_initializer() -> ServiceInitializer:
    """获取全局 ServiceInitializer 单例"""
    global _initializer
    if _initializer is None:
        _initializer = ServiceInitializer()
    return _initializer
