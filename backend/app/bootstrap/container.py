"""
ApplicationContainer — 应用级服务容器

统一管理所有重量级服务的生命周期:
    - llm_gateway:      LLM 统一网关 (Provider 链 + ModelRouter)
    - embedding_service: 向量化服务 (DashScope/Mock)
    - vision_service:    视觉模型服务 (共享 httpx 客户端)
    - marker_service:    文档标记/解析服务 (预加载解析器模块)

设计原则:
    1. 应用启动时初始化 (lifespan startup)
    2. Agent 从 Container 获取服务，禁止内部创建
    3. 应用关闭时统一释放资源 (lifespan shutdown)
    4. 单例模式，全局唯一 Container 实例

使用方式:
    from app.bootstrap import get_container
    container = get_container()
    gateway = container.llm_gateway          # LLMGateway 实例
    embedding = container.embedding_service  # BaseEmbedding 实例
    vision = container.vision_service        # VisionService 实例
    marker = container.marker_service        # MarkerService 实例
"""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class VisionService:
    """视觉模型服务 — 封装 Vision API 调用配置和共享 HTTP 客户端

    旧实现: ElementAgent.__init__ 每次从 settings 读取配置,
            每次调用创建新 httpx.AsyncClient。

    新实现: 启动时创建一次 VisionService, 共享 httpx.AsyncClient,
            ElementAgent 从 Container 获取配置和客户端。
    """

    def __init__(self, api_key: str, api_url: str, model: str) -> None:
        self.api_key = api_key
        self.api_url = api_url
        self.model = model
        self._client: Optional[Any] = None  # httpx.AsyncClient
        self._initialized = False

    async def initialize(self) -> None:
        """初始化共享 HTTP 客户端"""
        import httpx
        self._client = httpx.AsyncClient(timeout=120.0)
        self._initialized = True
        logger.info(f"VisionService initialized | model: {self.model}, url: {self.api_url[:50]}...")

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("VisionService not initialized, call initialize() first")
        return self._client

    async def shutdown(self) -> None:
        """释放 HTTP 客户端"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._initialized = False
        logger.info("VisionService shutdown")


class MarkerService:
    """文档标记/解析服务 — 预加载解析器模块和配置

    启动时预导入 pdfplumber / PyMuPDF, 避免首次请求时模块加载延迟。
    同时缓存解析器配置, 供 PDFParserAgent / DocumentParserAgent 使用。
    """

    def __init__(self) -> None:
        self._loaded_modules: Dict[str, str] = {}
        self._initialized = False

    def initialize(self) -> None:
        """预加载解析器模块"""
        # 预导入 pdfplumber
        try:
            import pdfplumber
            self._loaded_modules["pdfplumber"] = getattr(pdfplumber, "__version__", "unknown")
        except ImportError:
            self._loaded_modules["pdfplumber"] = "not_installed"

        # 预导入 PyMuPDF (fitz)
        try:
            import fitz  # noqa: F401
            self._loaded_modules["pymupdf"] = getattr(fitz, "__version__", "unknown")
        except ImportError:
            self._loaded_modules["pymupdf"] = "not_installed"

        # 预导入 python-docx
        try:
            import docx  # noqa: F401
            self._loaded_modules["python-docx"] = "loaded"
        except ImportError:
            self._loaded_modules["python-docx"] = "not_installed"

        self._initialized = True
        loaded_summary = ", ".join(f"{k}={v}" for k, v in self._loaded_modules.items())
        logger.info(f"MarkerService initialized | modules: {loaded_summary}")

    @property
    def loaded_modules(self) -> Dict[str, str]:
        return dict(self._loaded_modules)

    def is_available(self, module_name: str) -> bool:
        """检查模块是否已加载且可用"""
        return self._loaded_modules.get(module_name, "not_installed") != "not_installed"

    def shutdown(self) -> None:
        self._loaded_modules.clear()
        self._initialized = False
        logger.info("MarkerService shutdown")


class ApplicationContainer:
    """应用级服务容器 (单例)

    管理所有重量级服务的生命周期。

    属性:
        llm_gateway:       LLMGateway 实例 (Provider 链已初始化)
        embedding_service:  BaseEmbedding 实例 (已连接 DashScope)
        vision_service:     VisionService 实例 (共享 httpx 客户端)
        marker_service:     MarkerService 实例 (解析器已预加载)
    """

    def __init__(self) -> None:
        self._llm_gateway: Optional[Any] = None
        self._embedding_service: Optional[Any] = None
        self._vision_service: Optional[VisionService] = None
        self._marker_service: Optional[MarkerService] = None
        self._initialized = False
        self._init_times: Dict[str, float] = {}

    # ------------------------------------------------------------------ #
    #  服务访问 (属性方式 — 未初始化时抛异常)                              #
    # ------------------------------------------------------------------ #

    @property
    def llm_gateway(self) -> Any:
        if self._llm_gateway is None:
            raise RuntimeError(
                "LLM Gateway not initialized. "
                "Call ServiceInitializer.initialize_all() at startup."
            )
        return self._llm_gateway

    @property
    def embedding_service(self) -> Any:
        if self._embedding_service is None:
            raise RuntimeError(
                "Embedding Service not initialized. "
                "Call ServiceInitializer.initialize_all() at startup."
            )
        return self._embedding_service

    @property
    def vision_service(self) -> VisionService:
        if self._vision_service is None:
            raise RuntimeError(
                "Vision Service not initialized. "
                "Call ServiceInitializer.initialize_all() at startup."
            )
        return self._vision_service

    @property
    def marker_service(self) -> MarkerService:
        if self._marker_service is None:
            raise RuntimeError(
                "Marker Service not initialized. "
                "Call ServiceInitializer.initialize_all() at startup."
            )
        return self._marker_service

    # ------------------------------------------------------------------ #
    #  状态查询                                                           #
    # ------------------------------------------------------------------ #

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def init_times(self) -> Dict[str, float]:
        """各服务初始化耗时 (ms)"""
        return dict(self._init_times)

    def get_status(self) -> Dict[str, Any]:
        """获取容器状态摘要"""
        return {
            "initialized": self._initialized,
            "services": {
                "llm_gateway": self._llm_gateway is not None,
                "embedding_service": self._embedding_service is not None,
                "vision_service": self._vision_service is not None,
                "marker_service": self._marker_service is not None,
            },
            "init_times_ms": self._init_times,
        }

    def __repr__(self) -> str:
        return f"ApplicationContainer(initialized={self._initialized})"


# ------------------------------------------------------------------ #
#  单例                                                               #
# ------------------------------------------------------------------ #

_container: Optional[ApplicationContainer] = None


def get_container() -> ApplicationContainer:
    """获取全局 ApplicationContainer 单例"""
    global _container
    if _container is None:
        _container = ApplicationContainer()
    return _container


def reset_container() -> None:
    """重置容器 (仅用于测试)"""
    global _container
    _container = None
