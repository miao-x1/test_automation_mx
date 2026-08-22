"""
app.bootstrap — 应用启动引导层

架构:
    FastAPI lifespan
        ↓
    ServiceInitializer.initialize_all()
        ↓
    ApplicationContainer (持有所有服务实例)
        ├── LLM Gateway (Provider 链已初始化)
        ├── Embedding Service (向量化实例已创建)
        ├── Vision Service (httpx 客户端已预建)
        └── Marker Service (解析器模块已预加载)
        ↓
    Agent 从 Container 获取服务 (禁止内部创建)

使用方式:
    # 启动时 (main.py lifespan)
    from app.bootstrap import get_initializer
    await get_initializer().initialize_all()

    # Agent 中获取服务
    from app.bootstrap import get_container
    container = get_container()
    gateway = container.llm_gateway
    embedding = container.embedding_service
    vision = container.vision_service
    marker = container.marker_service

    # 关闭时 (main.py lifespan)
    await get_initializer().shutdown_all()
"""
from app.bootstrap.container import (
    ApplicationContainer,
    MarkerService,
    VisionService,
    get_container,
    reset_container,
)
from app.bootstrap.initializer import (
    ServiceInitializer,
    get_initializer,
)

__all__ = [
    "ApplicationContainer",
    "VisionService",
    "MarkerService",
    "get_container",
    "reset_container",
    "ServiceInitializer",
    "get_initializer",
]
