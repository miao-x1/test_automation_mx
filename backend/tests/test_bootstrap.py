"""
Bootstrap 启动流程测试

测试覆盖:
1. ApplicationContainer 创建与状态查询
2. VisionService 初始化与共享 HTTP 客户端
3. MarkerService 模块预加载
4. ServiceInitializer 全量初始化 (启动时间测量)
5. ServiceInitializer 关闭流程
6. ElementAgent 从 Container 获取 Vision 配置
7. BaseAgent.call_llm 优先使用 Container Gateway
8. 启动时间对比: 预初始化 vs 懒加载
"""
import asyncio
import sys
import time
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# ===== Stub 3rd-party modules =====
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# pymilvus stub
_pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
if not hasattr(_pm, "DataType"):
    _pm.DataType = type("DataType", (), {"INT64": "int64", "VARCHAR": "varchar", "FLOAT_VECTOR": "float_vector", "BOOL": "bool"})
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
sys.modules["pymilvus"] = _pm

# pymysql stub
_pymysql = types.ModuleType("pymysql")
_pymysql.paramstyle = "format"
_pymysql.install_as_MySQLdb = lambda: None
_pymysql.connect = lambda *a, **kw: None
sys.modules["pymysql"] = _pymysql

# neo4j stub
_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.AsyncGraphDatabase = type("AsyncGraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.Driver = type("Driver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None, "__enter__": lambda self: self, "__exit__": lambda *a, **kw: None})
_neo.AsyncDriver = type("AsyncDriver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None, "__aenter__": lambda self: self, "__aexit__": lambda *a, **kw: None})
_neo.Session = type("Session", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None, "__enter__": lambda self: self, "__exit__": lambda *a, **kw: None})
_neo.AsyncSession = type("AsyncSession", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None, "__aenter__": lambda self: self, "__aexit__": lambda *a, **kw: None})
_neo.basic_auth = lambda *a, **kw: MagicMock()
_neo_graph = types.ModuleType("neo4j.graph")
_neo_graph.Node = type("Node", (), {"__init__": lambda self, *a, **kw: None})
_neo_graph.Relationship = type("Relationship", (), {"__init__": lambda self, *a, **kw: None})
_neo_graph.Path = type("Path", (), {"__init__": lambda self, *a, **kw: None})
sys.modules["neo4j.graph"] = _neo_graph
_neo_exceptions = types.ModuleType("neo4j.exceptions")
for _exc_name in ["ServiceUnavailable", "AuthError", "CypherSyntaxError", "ClientError", "DatabaseError"]:
    setattr(_neo_exceptions, _exc_name, type(_exc_name, (Exception,), {}))
sys.modules["neo4j.exceptions"] = _neo_exceptions
sys.modules["neo4j"] = _neo

# autogen_core stub
_ag = types.ModuleType("autogen_core")
def _make_class(name):
    return type(name, (), {"__init__": lambda self, *a, **kw: None})
_ag.RoutedAgent = _make_class("RoutedAgent")
_ag.message_handler = lambda *a, **kw: (lambda f: f)
_ag.MessageContext = _make_class("MessageContext")
_ag.AgentId = _make_class("AgentId")
_ag.AgentRuntime = _make_class("AgentRuntime")
_ag.CancellationToken = _make_class("CancellationToken")
_ag.DefaultTopicId = _make_class("DefaultTopicId")
_ag.SingleThreadedAgentRuntime = _make_class("SingleThreadedAgentRuntime")
_ag.ComponentBase = _make_class("ComponentBase")
_ag.default_subscription = lambda *a, **kw: (lambda f: f)
sys.modules["autogen_core"] = _ag

# autogen_agentchat stub
_aac = types.ModuleType("autogen_agentchat")
_aac_base = types.ModuleType("autogen_agentchat.base")
_aac_base.ChatAgent = _make_class("ChatAgent")
_aac_base.Response = _make_class("Response")
_aac_base.TaskResult = _make_class("TaskResult")
_aac_messages = types.ModuleType("autogen_agentchat.messages")
_aac_messages.TextMessage = _make_class("TextMessage")
_aac_messages.BaseChatMessage = _make_class("BaseChatMessage")
_aac_messages.BaseAgentEvent = _make_class("BaseAgentEvent")
_aac_teams = types.ModuleType("autogen_agentchat.teams")
_aac_teams.DiGraphBuilder = _make_class("DiGraphBuilder")
_aac_teams.GraphFlow = _make_class("GraphFlow")
_aac.base = _aac_base
_aac.messages = _aac_messages
_aac.teams = _aac_teams
sys.modules["autogen_agentchat"] = _aac
sys.modules["autogen_agentchat.base"] = _aac_base
sys.modules["autogen_agentchat.messages"] = _aac_messages
sys.modules["autogen_agentchat.teams"] = _aac_teams

# sse_starlette stub
_sse = types.ModuleType("sse_starlette")
_sse_sse = types.ModuleType("sse_starlette.sse")
_sse_sse.EventSourceResponse = type("EventSourceResponse", (), {"__init__": lambda *a, **kw: None})
sys.modules["sse_starlette"] = _sse
sys.modules["sse_starlette.sse"] = _sse_sse


# ===== 测试工具 =====
RESULTS = []

def record(name: str, ok: bool, detail: str = ""):
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"{status} {name}"
    if detail and not ok:
        msg += f" | {detail}"
    print(msg)
    RESULTS.append((name, ok))


# ================================================================== #
#  测试 1-3: ApplicationContainer                                      #
# ================================================================== #

def test_container_create():
    """测试 1: ApplicationContainer 创建与初始状态"""
    from app.bootstrap.container import ApplicationContainer
    container = ApplicationContainer()
    ok = container.is_initialized is False
    ok = ok and container.init_times == {}
    status = container.get_status()
    ok = ok and status["initialized"] is False
    ok = ok and all(v is False for v in status["services"].values())
    record("Container-创建与初始状态", ok)


def test_container_access_uninitialized():
    """测试 2: 未初始化时访问服务抛异常"""
    from app.bootstrap.container import ApplicationContainer
    container = ApplicationContainer()
    errors = []
    for prop in ["llm_gateway", "embedding_service", "vision_service", "marker_service"]:
        try:
            getattr(container, prop)
            errors.append(f"{prop} 未抛异常")
        except RuntimeError:
            pass
        except Exception as e:
            errors.append(f"{prop} 抛了非预期异常: {type(e).__name__}")
    ok = len(errors) == 0
    record("Container-未初始化时抛异常", ok, "; ".join(errors))


def test_container_singleton():
    """测试 3: get_container 返回单例"""
    from app.bootstrap.container import get_container, reset_container
    reset_container()
    c1 = get_container()
    c2 = get_container()
    ok = c1 is c2
    record("Container-单例模式", ok)


# ================================================================== #
#  测试 4-5: VisionService                                            #
# ================================================================== #

async def test_vision_service_init():
    """测试 4: VisionService 初始化与共享客户端"""
    from app.bootstrap.container import VisionService
    vs = VisionService(
        api_key="test-key",
        api_url="https://api.example.com/v1/chat",
        model="qwen-vl-plus",
    )
    await vs.initialize()
    ok = vs._initialized is True
    ok = ok and vs.client is not None  # httpx.AsyncClient 实例
    ok = ok and vs.api_key == "test-key"
    ok = ok and vs.model == "qwen-vl-plus"
    await vs.shutdown()
    ok = ok and vs._client is None
    record("VisionService-初始化与关闭", ok)


async def test_vision_service_client_not_initialized():
    """测试 5: 未初始化时访问 client 抛异常"""
    from app.bootstrap.container import VisionService
    vs = VisionService(api_key="", api_url="", model="")
    ok = False
    try:
        _ = vs.client
    except RuntimeError:
        ok = True
    record("VisionService-未初始化时抛异常", ok)


# ================================================================== #
#  测试 6-7: MarkerService                                           #
# ================================================================== #

def test_marker_service_init():
    """测试 6: MarkerService 模块预加载"""
    from app.bootstrap.container import MarkerService
    ms = MarkerService()
    ms.initialize()
    ok = ms._initialized is True
    ok = ok and "pdfplumber" in ms.loaded_modules
    ok = ok and "pymupdf" in ms.loaded_modules
    ok = ok and "python-docx" in ms.loaded_modules
    ms.shutdown()
    ok = ok and ms._loaded_modules == {}
    record("MarkerService-模块预加载", ok)


def test_marker_service_is_available():
    """测试 7: MarkerService 模块可用性检查"""
    from app.bootstrap.container import MarkerService
    ms = MarkerService()
    ms.initialize()
    # pdfplumber 应该已安装
    ok = ms.is_available("pdfplumber") is True
    # 不存在的模块应该返回 False
    ok = ok and ms.is_available("nonexistent_module") is False
    ms.shutdown()
    record("MarkerService-模块可用性", ok)


# ================================================================== #
#  测试 8-10: ServiceInitializer                                      #
# ================================================================== #

async def test_initializer_full():
    """测试 8: ServiceInitializer 全量初始化"""
    from app.bootstrap.container import ApplicationContainer
    from app.bootstrap.initializer import ServiceInitializer

    container = ApplicationContainer()
    initializer = ServiceInitializer(container=container)

    # Mock LLM Gateway
    mock_gateway = MagicMock()
    mock_gateway._factory.list_providers = MagicMock(return_value=[])

    # Mock embedding
    mock_embedding = MagicMock()
    mock_embedding.__class__.__name__ = "MockEmbedding"

    with patch("app.llm.get_gateway", return_value=mock_gateway), \
         patch("app.core.config.settings", MagicMock()), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = mock_embedding
        mock_ef.return_value = mock_factory

        await initializer.initialize_all()

    ok = container.is_initialized is True
    ok = ok and container._llm_gateway is mock_gateway
    ok = ok and container._embedding_service is mock_embedding
    ok = ok and container._vision_service is not None
    ok = ok and container._marker_service is not None

    # 检查初始化耗时记录
    times = container.init_times
    ok = ok and "llm_gateway" in times
    ok = ok and "embedding_service" in times
    ok = ok and "vision_service" in times
    ok = ok and "marker_service" in times
    ok = ok and "_total" in times
    ok = ok and all(isinstance(t, float) for t in times.values())

    await initializer.shutdown_all()
    ok = ok and container.is_initialized is False
    ok = ok and container._vision_service._client is None  # HTTP 客户端已关闭

    record("Initializer-全量初始化与关闭", ok)


async def test_initializer_partial_failure():
    """测试 9: 单个服务初始化失败不阻断整体"""
    from app.bootstrap.container import ApplicationContainer
    from app.bootstrap.initializer import ServiceInitializer

    container = ApplicationContainer()
    initializer = ServiceInitializer(container=container)

    # LLM Gateway 初始化失败, 其他服务正常
    with patch("app.llm.get_gateway", side_effect=Exception("模拟LLM初始化失败")), \
         patch("app.core.config.settings", MagicMock()), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = MagicMock()
        mock_ef.return_value = mock_factory

        await initializer.initialize_all()

    # LLM Gateway 失败, 但其他服务正常
    ok = container._llm_gateway is None
    ok = ok and container._embedding_service is not None
    ok = ok and container._vision_service is not None
    ok = ok and container._marker_service is not None
    # 整体仍然标记为初始化完成
    ok = ok and container.is_initialized is True

    await initializer.shutdown_all()
    record("Initializer-部分失败容错", ok)


async def test_initializer_status():
    """测试 10: 初始化后状态查询"""
    from app.bootstrap.container import ApplicationContainer
    from app.bootstrap.initializer import ServiceInitializer

    container = ApplicationContainer()
    initializer = ServiceInitializer(container=container)

    mock_gateway = MagicMock()
    mock_gateway._factory.list_providers = MagicMock(return_value=[])

    with patch("app.llm.get_gateway", return_value=mock_gateway), \
         patch("app.core.config.settings", MagicMock()), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = MagicMock()
        mock_ef.return_value = mock_factory

        await initializer.initialize_all()

    status = container.get_status()
    ok = status["initialized"] is True
    ok = ok and all(status["services"].values())
    ok = ok and "_total" in status["init_times_ms"]
    ok = ok and all(v >= 0 for v in status["init_times_ms"].values())

    await initializer.shutdown_all()
    record("Initializer-状态查询", ok)


# ================================================================== #
#  测试 11: ElementAgent 从 Container 获取 Vision 配置                  #
# ================================================================== #

async def test_element_agent_from_container():
    """测试 11: ElementAgent 优先从 Container 获取 Vision 配置"""
    from app.bootstrap.container import get_container, reset_container
    from app.bootstrap.initializer import ServiceInitializer

    # 使用全局单例, 确保 ElementAgent 内部 get_container() 能获取到
    reset_container()
    container = get_container()
    initializer = ServiceInitializer(container=container)

    # 初始化 Container, 包含 VisionService
    with patch("app.llm.get_gateway", return_value=MagicMock()), \
         patch("app.core.config.settings", MagicMock(
             QWEN_API_KEY="container-key",
             QWEN_API_URL="https://container.api/v1/chat",
             QWEN_MODEL="container-vl-model",
         )), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = MagicMock()
        mock_ef.return_value = mock_factory

        await initializer.initialize_all()

    # 创建 ElementAgent — 应从 Container 获取配置
    from app.agent.vision.element_agent import ElementAgent
    agent = ElementAgent()

    ok = agent.api_key == "container-key"
    ok = ok and agent.api_url == "https://container.api/v1/chat"
    ok = ok and agent.model == "container-vl-model"
    ok = ok and agent._vision_service is not None
    ok = ok and agent._vision_service is container.vision_service

    await initializer.shutdown_all()
    record("ElementAgent-从Container获取配置", ok)


# ================================================================== #
#  测试 12: ElementAgent 降级到 settings                              #
# ================================================================== #

async def test_element_agent_fallback():
    """测试 12: Container 未初始化时 ElementAgent 降级到 settings"""
    from app.bootstrap.container import ApplicationContainer, reset_container
    reset_container()

    from app.agent.vision.element_agent import ElementAgent
    agent = ElementAgent()

    # Container 未初始化, 应从 settings 读取
    ok = agent._vision_service is None
    ok = ok and agent.api_key is not None  # 从 settings 读取
    ok = ok and agent.model is not None
    record("ElementAgent-降级到settings", ok)


# ================================================================== #
#  测试 13: BaseAgent.call_llm 优先使用 Container Gateway              #
# ================================================================== #

async def test_base_agent_llm_from_container():
    """测试 13: BaseAgent.call_llm 优先使用 Container 中的 LLM Gateway"""
    from app.bootstrap.container import get_container, reset_container
    from app.bootstrap.initializer import ServiceInitializer

    # 使用全局单例
    reset_container()
    container = get_container()
    initializer = ServiceInitializer(container=container)

    # Mock LLM Gateway
    mock_gateway = MagicMock()
    mock_gateway.chat = AsyncMock(return_value="LLM响应内容")
    mock_gateway._factory = MagicMock()
    mock_gateway._factory.list_providers = MagicMock(return_value=[])

    with patch("app.llm.get_gateway", return_value=mock_gateway), \
         patch("app.core.config.settings", MagicMock()), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = MagicMock()
        mock_ef.return_value = mock_factory

        await initializer.initialize_all()

    # 创建 BaseAgent 并调用 call_llm
    from app.agent.core.base_agent import BaseAgent
    from app.agent.core.config import AgentConfig
    config = AgentConfig(agent_name="test_agent")
    agent = BaseAgent(config=config)
    result = await agent.call_llm("系统提示", "用户提示")

    ok = result == "LLM响应内容"
    # 确认使用了 Gateway 而非直接 HTTP
    ok = ok and mock_gateway.chat.called
    call_kwargs = mock_gateway.chat.call_args
    ok = ok and call_kwargs.kwargs.get("system_prompt") == "系统提示"
    ok = ok and call_kwargs.kwargs.get("user_prompt") == "用户提示"

    await initializer.shutdown_all()
    record("BaseAgent-优先使用Container Gateway", ok)


# ================================================================== #
#  测试 14: 启动时间对比 (核心指标)                                    #
# ================================================================== #

async def test_startup_time_comparison():
    """测试 14: 启动时间对比 — 预初始化 vs 懒加载"""

    print("\n" + "=" * 60)
    print("           启动时间对比: 预初始化 vs 懒加载")
    print("=" * 60)

    # ---- 方式 A: 懒加载 (模拟当前行为 — 每个服务首次访问时初始化) ----
    from app.bootstrap.container import ApplicationContainer, reset_container
    reset_container()
    lazy_container = ApplicationContainer()

    lazy_start = time.time()

    # 模拟懒加载: 逐个初始化 (模拟首次请求触发)
    t1 = time.time()
    mock_gw = MagicMock()
    mock_gw._factory = MagicMock()
    mock_gw._factory.list_providers = MagicMock(return_value=[])
    lazy_container._llm_gateway = mock_gw
    lazy_llm_time = (time.time() - t1) * 1000

    t2 = time.time()
    lazy_container._embedding_service = MagicMock()
    lazy_embed_time = (time.time() - t2) * 1000

    t3 = time.time()
    from app.bootstrap.container import VisionService
    vs = VisionService("key", "url", "model")
    await vs.initialize()
    await vs.shutdown()
    lazy_vision_time = (time.time() - t3) * 1000

    t4 = time.time()
    from app.bootstrap.container import MarkerService
    ms = MarkerService()
    ms.initialize()
    ms.shutdown()
    lazy_marker_time = (time.time() - t4) * 1000

    lazy_total = (time.time() - lazy_start) * 1000

    # ---- 方式 B: 预初始化 (ServiceInitializer.initialize_all 一次性完成) ----
    reset_container()
    from app.bootstrap.initializer import ServiceInitializer
    eager_container = ApplicationContainer()
    initializer = ServiceInitializer(container=eager_container)

    with patch("app.llm.get_gateway", return_value=mock_gw), \
         patch("app.core.config.settings", MagicMock()), \
         patch("app.rag.embedding.factory.get_embedding_factory") as mock_ef:
        mock_factory = MagicMock()
        mock_factory.get_embedding.return_value = MagicMock()
        mock_ef.return_value = mock_factory

        eager_start = time.time()
        await initializer.initialize_all()
        eager_total = (time.time() - eager_start) * 1000

    eager_times = dict(eager_container.init_times)

    await initializer.shutdown_all()

    # ---- 输出对比表 ----
    print()
    print("┌─────────────────────┬──────────────────┬──────────────────┬──────────┐")
    print("│ 服务                │ 懒加载 (ms)       │ 预初始化 (ms)    │ 差异     │")
    print("├─────────────────────┼──────────────────┼──────────────────┼──────────┤")
    services = [
        ("LLM Gateway", lazy_llm_time, eager_times.get("llm_gateway", 0)),
        ("Embedding Service", lazy_embed_time, eager_times.get("embedding_service", 0)),
        ("Vision Service", lazy_vision_time, eager_times.get("vision_service", 0)),
        ("Marker Service", lazy_marker_time, eager_times.get("marker_service", 0)),
    ]
    for name, lazy, eager in services:
        diff = eager - lazy
        sign = "+" if diff >= 0 else ""
        print(f"│ {name:<19s} │ {lazy:>14.2f}ms │ {eager:>14.2f}ms │ {sign}{diff:>6.2f}ms │")
    print("├─────────────────────┼──────────────────┼──────────────────┼──────────┤")
    print(f"│ {'合计':<19s} │ {lazy_total:>14.2f}ms │ {eager_total:>14.2f}ms │ {'':>8s} │")
    print("└─────────────────────┴──────────────────┴──────────────────┴──────────┘")

    # 预初始化的核心价值: 首次请求时不需要等待
    # 模拟首次请求获取服务的时间
    req_start = time.time()
    _ = eager_container.llm_gateway
    _ = eager_container.embedding_service
    _ = eager_container.vision_service
    _ = eager_container.marker_service
    request_time = (time.time() - req_start) * 1000

    print(f"\n  预初始化后首次请求获取服务: {request_time:.4f}ms (接近零延迟)")
    print(f"  懒加载首次请求需等待: {lazy_total:.2f}ms (全部初始化耗时)")
    print(f"  节省: {lazy_total - request_time:.2f}ms ({(1 - request_time/max(lazy_total,0.01))*100:.1f}%)")
    print("=" * 60)

    # 预初始化后请求时间应极小
    ok = request_time < 5.0  # 5ms 以内
    record("启动时间对比", ok)


# ================================================================== #
#  测试 15: 模块导入完整性                                             #
# ================================================================== #

def test_module_imports():
    """测试 15: 模块导入完整性"""
    errors = []
    try:
        from app.bootstrap import ApplicationContainer
        from app.bootstrap import VisionService
        from app.bootstrap import MarkerService
        from app.bootstrap import get_container
        from app.bootstrap import reset_container
        from app.bootstrap import ServiceInitializer
        from app.bootstrap import get_initializer
    except ImportError as e:
        errors.append(str(e))
    ok = len(errors) == 0
    record("模块导入完整性", ok, "; ".join(errors))


# ================================================================== #
#  主函数                                                              #
# ================================================================== #

async def main():
    print("=" * 60)
    print("Bootstrap 启动流程测试")
    print("=" * 60)

    test_container_create()
    test_container_access_uninitialized()
    test_container_singleton()

    await test_vision_service_init()
    await test_vision_service_client_not_initialized()

    test_marker_service_init()
    test_marker_service_is_available()

    await test_initializer_full()
    await test_initializer_partial_failure()
    await test_initializer_status()

    await test_element_agent_from_container()
    await test_element_agent_fallback()

    await test_base_agent_llm_from_container()

    await test_startup_time_comparison()

    test_module_imports()

    print("\n" + "=" * 60)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = sum(1 for _, ok in RESULTS if not ok)
    total = len(RESULTS)
    print(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    print("=" * 60)
    if failed == 0:
        print("全部测试通过!")
    else:
        for name, ok in RESULTS:
            if not ok:
                print(f"  失败: {name}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.exit(rc)
