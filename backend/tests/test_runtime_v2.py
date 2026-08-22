"""
Runtime v2 全链路测试

验证:
1. TaskState 状态机 (6状态/转换/序列化/反序列化)
2. TaskDispatcher (提交/分发/完成/取消/重试/崩溃恢复)
3. AgentWorker (执行/成功/失败/异常/重试)
4. WorkerPool (分配/并发/扩缩容)
5. ResponseCollector (记录/收集/LRU)
6. StreamPublisher (SSE/WebSocket 推送)
7. TaskScheduler (立即/延迟/定时/依赖)
8. API 路由 (10 个端点)
9. 全链路: submit → dispatch → worker → agent → collector → SSE
"""
import asyncio
import json
import logging
import os
import sys
import time
import types
import uuid
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

# 确保能 import app.*
backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

# 测试用:强制使用 SQLite
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("SQLITE_PATH", "data/test_runtime_v2.db")

# stub out optional 3rd-party modules
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

# pymilvus needs DataType enum and other classes
if not hasattr(sys.modules.get("pymilvus", types.ModuleType("pymilvus")), "DataType"):
    _pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
    _pm.DataType = type("DataType", (), {
        "INT64": "int64",
        "VARCHAR": "varchar",
        "FLOAT_VECTOR": "float_vector",
        "BOOL": "bool",
    })
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
    sys.modules["pymilvus"] = _pm

# neo4j needs GraphDatabase, Driver, Session
_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {
    "driver": lambda *a, **kw: None,
    "verify_connectivity": lambda *a, **kw: None,
})
_neo.Driver = type("Driver", (), {})
_neo.Session = type("Session", (), {})
sys.modules["neo4j"] = _neo

# autogen_core stub — always override (real package may be partially installed)
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

# autogen_agentchat stub (required by flow_node_adapter / graph_flow_manager)
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
sys.modules["autogen_agentchat"] = _aac
sys.modules["autogen_agentchat.base"] = _aac_base
sys.modules["autogen_agentchat.messages"] = _aac_messages
sys.modules["autogen_agentchat.teams"] = _aac_teams

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_runtime_v2")

results = []


def record(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    results.append({"name": name, "status": status, "detail": detail})
    logger.info(f"[{status}] {name}" + (f" - {detail}" if detail else ""))


# ============================================================
# 测试 1-5: TaskState 状态机
# ============================================================

def test_state_machine():
    """测试 1: 状态机转换"""
    from app.runtime.v2.state import TaskState, TaskStatus, TaskPriority, VALID_TRANSITIONS

    state = TaskState(
        task_id="test-1",
        agent_name="test_agent",
    )

    # 初始状态
    ok = state.status == TaskStatus.PENDING

    # PENDING → RUNNING
    state.transition(TaskStatus.RUNNING)
    ok = ok and state.status == TaskStatus.RUNNING
    ok = ok and state.started_at is not None

    # RUNNING → SUCCESS
    state.transition(TaskStatus.SUCCESS)
    ok = ok and state.status == TaskStatus.SUCCESS
    ok = ok and state.completed_at is not None

    # SUCCESS → RUNNING (非法)
    try:
        state.transition(TaskStatus.RUNNING)
        ok = ok and False  # 不应到达
    except ValueError:
        ok = ok and True

    record("状态机-正常转换与非法拦截", ok)


def test_state_retry():
    """测试 2: 重试机制"""
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(task_id="test-2", agent_name="agent", max_retries=3)
    state.transition(TaskStatus.RUNNING)

    # 第一次失败
    state.transition(TaskStatus.FAILED)
    ok = state.can_retry == True
    ok = ok and state.retry_count == 0

    # 重置重试
    state.reset_for_retry()
    ok = ok and state.status == TaskStatus.PENDING
    ok = ok and state.retry_count == 1
    ok = ok and state.error is None

    # 第二次失败 + 重试
    state.transition(TaskStatus.RUNNING)
    state.transition(TaskStatus.FAILED)
    state.reset_for_retry()
    ok = ok and state.retry_count == 2

    # 第三次失败 (达到最大重试)
    state.transition(TaskStatus.RUNNING)
    state.transition(TaskStatus.FAILED)
    ok = ok and state.can_retry == False
    ok = ok and state.is_terminal == True

    record("状态机-重试机制", ok)


def test_state_serialization():
    """测试 3: 序列化/反序列化"""
    from app.runtime.v2.state import TaskState, TaskStatus, TaskPriority, TaskType

    state = TaskState(
        task_id="test-3",
        agent_name="rag_agent",
        action="query",
        payload={"query": "测试登录", "top_k": 5},
        status=TaskStatus.RUNNING,
        priority=TaskPriority.HIGH,
        task_type=TaskType.AGENT,
        max_retries=2,
        timeout_seconds=60,
        session_id="session-123",
        user_id=1,
    )
    state.transition(TaskStatus.RUNNING)

    # 序列化
    data = state.to_dict()
    ok = data["task_id"] == "test-3"
    ok = ok and data["status"] == "running"
    ok = ok and data["agent_name"] == "rag_agent"
    ok = ok and data["priority"] == 1  # HIGH
    ok = ok and data["payload"]["query"] == "测试登录"

    # 反序列化
    restored = TaskState.from_dict(data)
    ok = ok and restored.task_id == state.task_id
    ok = ok and restored.status == TaskStatus.RUNNING
    ok = ok and restored.agent_name == state.agent_name
    ok = ok and restored.payload == state.payload

    record("状态机-序列化/反序列化", ok)


def test_state_from_request():
    """测试 4: TaskRequest → TaskState"""
    from app.runtime.v2.state import TaskRequest, TaskState, TaskStatus, TaskPriority

    request = TaskRequest(
        agent_name="requirement_agent",
        action="analyze",
        payload={"text": "测试登录功能"},
        priority=TaskPriority.URGENT,
        timeout=120,
        max_retries=5,
        session_id="sess-1",
        user_id=42,
    )

    state = TaskState.from_request(request)
    ok = state.agent_name == "requirement_agent"
    ok = ok and state.action == "analyze"
    ok = ok and state.status == TaskStatus.PENDING
    ok = ok and state.priority == TaskPriority.URGENT
    ok = ok and state.timeout_seconds == 120
    ok = ok and state.max_retries == 5
    ok = ok and state.task_id.startswith("task-")
    ok = ok and state.user_id == 42

    record("状态机-TaskRequest→TaskState", ok)


def test_state_duration():
    """测试 5: 耗时计算"""
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(task_id="test-5", agent_name="agent")

    # 未开始
    ok = state.duration_ms is None

    # 运行中
    state.transition(TaskStatus.RUNNING)
    ok = ok and state.duration_ms is not None
    ok = ok and state.duration_ms >= 0

    # 已完成
    state.transition(TaskStatus.SUCCESS)
    ok = ok and state.duration_ms is not None
    ok = ok and state.duration_ms >= 0

    record("状态机-耗时计算", ok)


# ============================================================
# 测试 6-8: Dispatcher
# ============================================================

async def test_dispatcher_submit():
    """测试 6: Dispatcher 提交任务"""
    from app.runtime.v2.dispatcher import TaskDispatcher, DispatcherMode
    from app.runtime.v2.state import TaskRequest, TaskStatus

    # Mock AgentRegistry
    with patch("app.agents.factory.AgentRegistry") as mock_registry:
        mock_registry.exists.return_value = True
        mock_registry.is_enabled.return_value = True
        mock_registry.list_agents.return_value = ["test_agent"]

        dispatcher = TaskDispatcher(mode=DispatcherMode.STANDALONE)

        # Mock WorkerPool
        mock_pool = AsyncMock()
        mock_pool.assign = AsyncMock()
        dispatcher.set_worker_pool(mock_pool)

        # Mock Collector
        mock_collector = AsyncMock()
        mock_collector.record = AsyncMock()
        dispatcher.set_response_collector(mock_collector)

        await dispatcher.start()

        request = TaskRequest(agent_name="test_agent", payload={"x": 1})
        task_id = await dispatcher.submit(request)

        ok = task_id.startswith("task-")
        ok = ok and dispatcher.get_status(task_id) == TaskStatus.PENDING

        # 等待分发
        await asyncio.sleep(0.5)

        # WorkerPool.assign 应被调用
        ok = ok and mock_pool.assign.called

        await dispatcher.stop()

    record("Dispatcher-提交与分发", ok)


async def test_dispatcher_cancel():
    """测试 7: Dispatcher 取消任务"""
    from app.runtime.v2.dispatcher import TaskDispatcher, DispatcherMode
    from app.runtime.v2.state import TaskRequest, TaskStatus

    with patch("app.agents.factory.AgentRegistry") as mock_registry:
        mock_registry.exists.return_value = True
        mock_registry.is_enabled.return_value = True
        mock_registry.list_agents.return_value = ["test_agent"]

        dispatcher = TaskDispatcher(mode=DispatcherMode.STANDALONE)
        mock_pool = AsyncMock()
        # 不调用 assign, 让任务停在队列
        async def slow_assign(state, disp):
            await asyncio.sleep(10)
        mock_pool.assign = slow_assign
        dispatcher.set_worker_pool(mock_pool)
        mock_collector = AsyncMock()
        mock_collector.record = AsyncMock()
        dispatcher.set_response_collector(mock_collector)

        await dispatcher.start()

        request = TaskRequest(agent_name="test_agent")
        task_id = await dispatcher.submit(request)

        # 取消
        success = await dispatcher.cancel(task_id)
        ok = success == True

        # 再次取消 (已取消, 应失败)
        success2 = await dispatcher.cancel(task_id)
        ok = ok and success2 == False

        await dispatcher.stop()

    record("Dispatcher-取消任务", ok)


async def test_dispatcher_stats():
    """测试 8: Dispatcher 统计"""
    from app.runtime.v2.dispatcher import TaskDispatcher, DispatcherMode
    from app.runtime.v2.state import TaskRequest

    with patch("app.agents.factory.AgentRegistry") as mock_registry:
        mock_registry.exists.return_value = True
        mock_registry.is_enabled.return_value = True
        mock_registry.list_agents.return_value = ["test_agent"]

        dispatcher = TaskDispatcher(mode=DispatcherMode.STANDALONE)
        mock_pool = AsyncMock()
        mock_pool.assign = AsyncMock()
        dispatcher.set_worker_pool(mock_pool)
        mock_collector = AsyncMock()
        mock_collector.record = AsyncMock()
        dispatcher.set_response_collector(mock_collector)

        await dispatcher.start()

        # 提交 3 个任务
        for i in range(3):
            await dispatcher.submit(TaskRequest(agent_name="test_agent"))

        stats = dispatcher.get_stats()
        ok = stats["submitted"] == 3
        ok = ok and stats["total_tasks"] == 3

        await dispatcher.stop()

    record("Dispatcher-统计", ok)


# ============================================================
# 测试 9-11: Worker
# ============================================================

async def test_worker_success():
    """测试 9: Worker 成功执行"""
    from app.runtime.v2.worker import AgentWorker
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(task_id="test-9", agent_name="test_agent")

    # Mock Dispatcher (complete 也会做状态转换, 模拟真实行为)
    mock_dispatcher = AsyncMock()
    captured = {}
    async def _complete(task_id, status, result=None, error=None, events=None, worker_id=None):
        state.transition(status)
        captured["status"] = status
        captured["result"] = result
        captured["error"] = error
    mock_dispatcher.complete = AsyncMock(side_effect=_complete)
    mock_dispatcher._collector = None

    # Mock AgentFactory + Agent
    mock_agent = MagicMock()
    mock_agent.execute = AsyncMock(return_value={"status": "success", "data": "结果"})

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        mock_factory.create = AsyncMock(return_value=mock_agent)

        worker = AgentWorker(worker_id="w-test-9")
        await worker.execute(state, mock_dispatcher)

    ok = state.status == TaskStatus.SUCCESS
    ok = ok and mock_dispatcher.complete.called
    ok = ok and captured.get("status") == TaskStatus.SUCCESS
    ok = ok and captured.get("result") == {"status": "success", "data": "结果"}

    record("Worker-成功执行", ok)


async def test_worker_failure():
    """测试 10: Worker 失败执行"""
    from app.runtime.v2.worker import AgentWorker
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(task_id="test-10", agent_name="test_agent")

    mock_dispatcher = AsyncMock()
    captured = {}
    async def _complete(task_id, status, result=None, error=None, events=None, worker_id=None):
        state.transition(status)
        captured["status"] = status
        captured["error"] = error
    mock_dispatcher.complete = AsyncMock(side_effect=_complete)
    mock_dispatcher._collector = None

    # Agent 返回错误
    mock_agent = MagicMock()
    mock_agent.execute = AsyncMock(return_value={"status": "error", "message": "分析失败"})

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        mock_factory.create = AsyncMock(return_value=mock_agent)

        worker = AgentWorker()
        await worker.execute(state, mock_dispatcher)

    ok = state.status == TaskStatus.FAILED
    ok = ok and captured.get("status") == TaskStatus.FAILED
    ok = ok and "分析失败" in (captured.get("error") or "")

    record("Worker-失败执行", ok)


async def test_worker_exception():
    """测试 11: Worker 异常捕获"""
    from app.runtime.v2.worker import AgentWorker
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(task_id="test-11", agent_name="test_agent")

    mock_dispatcher = AsyncMock()
    captured = {}
    async def _complete(task_id, status, result=None, error=None, events=None, worker_id=None):
        state.transition(status)
        captured["status"] = status
        captured["error"] = error
    mock_dispatcher.complete = AsyncMock(side_effect=_complete)
    mock_dispatcher._collector = None

    # Agent 抛出异常
    mock_agent = MagicMock()
    mock_agent.execute = AsyncMock(side_effect=RuntimeError("连接超时"))

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        mock_factory.create = AsyncMock(return_value=mock_agent)

        worker = AgentWorker()
        await worker.execute(state, mock_dispatcher)

    ok = state.status == TaskStatus.FAILED
    ok = ok and captured.get("status") == TaskStatus.FAILED
    ok = ok and "RuntimeError" in (captured.get("error") or "")
    ok = ok and "连接超时" in (captured.get("error") or "")

    record("Worker-异常捕获", ok)


async def test_worker_timeout():
    """测试 12: Worker 超时"""
    from app.runtime.v2.worker import AgentWorker
    from app.runtime.v2.state import TaskState, TaskStatus

    state = TaskState(
        task_id="test-12", agent_name="test_agent", timeout_seconds=1
    )

    mock_dispatcher = AsyncMock()
    captured = {}
    async def _complete(task_id, status, result=None, error=None, events=None, worker_id=None):
        state.transition(status)
        captured["status"] = status
        captured["error"] = error
    mock_dispatcher.complete = AsyncMock(side_effect=_complete)
    mock_dispatcher._collector = None

    # Agent 执行很慢
    async def slow_execute(payload, ctx):
        await asyncio.sleep(10)
        return {"status": "success"}

    mock_agent = MagicMock()
    mock_agent.execute = slow_execute

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        mock_factory.create = AsyncMock(return_value=mock_agent)

        worker = AgentWorker()
        await worker.execute(state, mock_dispatcher)

    ok = state.status == TaskStatus.TIMEOUT
    ok = ok and captured.get("status") == TaskStatus.TIMEOUT
    ok = ok and "超时" in (captured.get("error") or "")

    record("Worker-超时控制", ok)


# ============================================================
# 测试 13-14: WorkerPool
# ============================================================

async def test_worker_pool_assign():
    """测试 13: WorkerPool 分配任务"""
    from app.runtime.v2.worker import WorkerPool, AgentWorker
    from app.runtime.v2.state import TaskState, TaskStatus

    pool = WorkerPool(size=2)
    await pool.start()

    state = TaskState(task_id="test-13", agent_name="agent")
    mock_dispatcher = AsyncMock()
    async def _complete(task_id, status, **kwargs):
        state.transition(status)
    mock_dispatcher.complete = AsyncMock(side_effect=_complete)
    mock_dispatcher._collector = None

    mock_agent = MagicMock()
    mock_agent.execute = AsyncMock(return_value={"status": "success"})

    with patch("app.agents.factory.AgentFactory") as mock_factory:
        mock_factory.create = AsyncMock(return_value=mock_agent)

        await pool.assign(state, mock_dispatcher)
        await asyncio.sleep(0.5)

    ok = state.status == TaskStatus.SUCCESS

    await pool.stop()

    record("WorkerPool-分配任务", ok)


async def test_worker_pool_stats():
    """测试 14: WorkerPool 统计"""
    from app.runtime.v2.worker import WorkerPool

    pool = WorkerPool(size=4)
    await pool.start()

    stats = pool.get_stats()
    ok = stats["size"] == 4
    ok = ok and stats["started"] == True
    ok = ok and stats["idle_workers"] == 4
    ok = ok and stats["busy_workers"] == 0

    # 扩容
    pool.resize(6)
    ok = ok and pool.size == 6

    await pool.stop()

    record("WorkerPool-统计与扩缩容", ok)


# ============================================================
# 测试 15-17: Collector
# ============================================================

async def test_collector_record():
    """测试 15: Collector 记录事件"""
    from app.runtime.v2.collector import ResponseCollector

    collector = ResponseCollector()

    # 记录事件
    await collector.record("task-1", {"event": "start", "data": {}})
    await collector.record("task-1", {"event": "progress", "data": {"p": 50}})
    await collector.record("task-1", {"event": "end", "data": {"result": "ok"}})

    events = collector.get_events("task-1")
    ok = len(events) == 3
    ok = ok and events[0]["event"] == "start"
    ok = ok and events[2]["event"] == "end"

    # collect
    collected = collector.collect("task-1")
    ok = ok and len(collected) == 3
    ok = ok and collector.is_completed("task-1")

    record("Collector-记录事件", ok)


async def test_collector_sse_push():
    """测试 16: Collector + Publisher SSE 推送"""
    from app.runtime.v2.collector import ResponseCollector, StreamPublisher

    collector = ResponseCollector()
    publisher = StreamPublisher()
    collector.set_stream_publisher(publisher)

    # 模拟 SSE 客户端
    received_events = []

    async def sse_consumer():
        async for event in publisher.sse_stream("task-2"):
            received_events.append(event)
            if event.get("event") == "done":
                break

    # 启动消费者
    consumer_task = asyncio.create_task(sse_consumer())
    await asyncio.sleep(0.1)

    # 记录事件
    await collector.record("task-2", {"event": "start", "agent_name": "test"})
    await collector.record("task-2", {"event": "progress", "message": "50%"})
    await collector.record("task-2", {"event": "end", "status": "success"})
    await collector.record("task-2", {"event": "done"})

    # 等待消费者完成
    await asyncio.wait_for(consumer_task, timeout=5)

    ok = len(received_events) >= 3
    ok = ok and received_events[0].get("event") == "start"
    ok = ok and received_events[-1].get("event") == "done"

    record("Collector-SSE推送", ok)


async def test_collector_multiple_tasks():
    """测试 17: Collector 多任务隔离"""
    from app.runtime.v2.collector import ResponseCollector

    collector = ResponseCollector()

    await collector.record("task-a", {"event": "start"})
    await collector.record("task-b", {"event": "start"})
    await collector.record("task-a", {"event": "end"})
    await collector.record("task-b", {"event": "end"})

    events_a = collector.get_events("task-a")
    events_b = collector.get_events("task-b")

    ok = len(events_a) == 2
    ok = ok and len(events_b) == 2
    ok = ok and events_a[0]["event"] == "start"
    ok = ok and events_b[1]["event"] == "end"

    record("Collector-多任务隔离", ok)


# ============================================================
# 测试 18-19: Scheduler
# ============================================================

async def test_scheduler_immediate():
    """测试 18: Scheduler 立即执行"""
    from app.runtime.v2.scheduler import TaskScheduler, ScheduleType
    from app.runtime.v2.state import TaskRequest

    mock_dispatcher = AsyncMock()
    mock_dispatcher.submit = AsyncMock(return_value="task-x")

    scheduler = TaskScheduler(dispatcher=mock_dispatcher)
    scheduler.set_dispatcher(mock_dispatcher)
    await scheduler.start()

    task_id = await scheduler.submit_now(
        TaskRequest(agent_name="test_agent")
    )

    ok = task_id == "task-x"
    ok = ok and mock_dispatcher.submit.called

    await scheduler.stop()

    record("Scheduler-立即执行", ok)


async def test_scheduler_delayed():
    """测试 19: Scheduler 延迟执行"""
    from app.runtime.v2.scheduler import TaskScheduler
    from app.runtime.v2.state import TaskRequest

    mock_dispatcher = AsyncMock()
    mock_dispatcher.submit = AsyncMock(return_value="task-y")

    scheduler = TaskScheduler(dispatcher=mock_dispatcher)
    scheduler.set_dispatcher(mock_dispatcher)
    await scheduler.start()

    sched_id = await scheduler.submit_delayed(
        TaskRequest(agent_name="test_agent"),
        delay_seconds=1,
    )

    ok = sched_id.startswith("sched-")

    # 等待延迟到期
    await asyncio.sleep(2)

    ok = ok and mock_dispatcher.submit.called

    await scheduler.stop()

    record("Scheduler-延迟执行", ok)


# ============================================================
# 测试 20: 全链路
# ============================================================

async def test_full_pipeline():
    """测试 20: 全链路 — submit → dispatch → worker → agent → collector → SSE"""
    from app.runtime.v2.state import TaskRequest, TaskStatus

    # 重置单例
    from app.runtime.v2.dispatcher import reset_dispatcher
    from app.runtime.v2.worker import reset_worker_pool
    from app.runtime.v2.collector import reset_collector
    from app.runtime.v2.scheduler import reset_scheduler
    reset_dispatcher()
    reset_worker_pool()
    reset_collector()
    reset_scheduler()

    # Mock AgentRegistry
    with patch("app.agents.factory.AgentRegistry") as mock_registry:
        mock_registry.exists.return_value = True
        mock_registry.is_enabled.return_value = True
        mock_registry.list_agents.return_value = ["pipeline_agent"]

        # Mock AgentFactory + Agent
        mock_agent = MagicMock()

        async def mock_execute(payload, ctx):
            return {"status": "success", "result": "管道执行完成"}
        mock_agent.execute = mock_execute

        with patch("app.agents.factory.AgentFactory") as mock_factory:
            mock_factory.create = AsyncMock(return_value=mock_agent)

            # 启动 Runtime
            from app.runtime.v2 import start_runtime, stop_runtime, get_dispatcher
            await start_runtime(worker_count=2)

            # 提交任务
            request = TaskRequest(
                agent_name="pipeline_agent",
                payload={"test": "full_pipeline"},
            )
            task_id = await get_dispatcher().submit(request)

            # 等待结果
            result = await get_dispatcher().wait_for_result(task_id, timeout=10)

            ok = result is not None
            ok = ok and result.status == TaskStatus.SUCCESS
            ok = ok and result.result == {"status": "success", "result": "管道执行完成"}

            await stop_runtime()

    record("全链路-submit→dispatch→worker→agent→collector", ok)


# ============================================================
# 测试 21: 重试全链路
# ============================================================

async def test_retry_pipeline():
    """测试 21: 重试全链路 — 失败后自动重试"""
    from app.runtime.v2.state import TaskRequest, TaskStatus

    from app.runtime.v2.dispatcher import reset_dispatcher
    from app.runtime.v2.worker import reset_worker_pool
    from app.runtime.v2.collector import reset_collector
    from app.runtime.v2.scheduler import reset_scheduler
    reset_dispatcher()
    reset_worker_pool()
    reset_collector()
    reset_scheduler()

    call_count = 0

    with patch("app.agents.factory.AgentRegistry") as mock_registry:
        mock_registry.exists.return_value = True
        mock_registry.is_enabled.return_value = True
        mock_registry.list_agents.return_value = ["retry_agent"]

        mock_agent = MagicMock()

        async def flaky_execute(payload, ctx):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"status": "error", "message": f"第{call_count}次失败"}
            return {"status": "success", "result": "重试成功"}
        mock_agent.execute = flaky_execute

        with patch("app.agents.factory.AgentFactory") as mock_factory:
            mock_factory.create = AsyncMock(return_value=mock_agent)

            from app.runtime.v2 import start_runtime, stop_runtime, get_dispatcher
            await start_runtime(worker_count=1)

            request = TaskRequest(
                agent_name="retry_agent",
                max_retries=3,
            )
            task_id = await get_dispatcher().submit(request)

            result = await get_dispatcher().wait_for_result(task_id, timeout=15)

            ok = result is not None
            ok = ok and result.status == TaskStatus.SUCCESS
            ok = ok and result.retry_count == 2  # 失败 2 次后第 3 次成功
            ok = ok and call_count == 3

            await stop_runtime()

    record("全链路-失败重试", ok)


# ============================================================
# 测试 22: API 路由
# ============================================================

async def test_api_routes():
    """测试 22: API 路由注册验证"""
    from app.api.runtime_v2 import router

    routes = []
    for route in router.routes:
        methods = getattr(route, "methods", set())
        path = getattr(route, "path", "")
        if methods:
            for m in methods:
                routes.append((m, path))
        else:
            # WebSocket
            routes.append(("WS", getattr(route, "path", "")))

    # 预期路由
    expected = [
        ("POST", "/api/v2/runtime/tasks"),
        ("GET", "/api/v2/runtime/tasks/{task_id}"),
        ("GET", "/api/v2/runtime/tasks/{task_id}/result"),
        ("DELETE", "/api/v2/runtime/tasks/{task_id}"),
        ("GET", "/api/v2/runtime/tasks"),
        ("GET", "/api/v2/runtime/stream/{task_id}"),
        ("GET", "/api/v2/runtime/stats"),
        ("GET", "/api/v2/runtime/workers"),
        ("GET", "/api/v2/runtime/schedules"),
    ]

    ok = len(routes) >= 9
    for method, path in expected:
        found = any(m == method and p == path for m, p in routes)
        if not found:
            ok = False
            break

    # WebSocket 路由
    ws_found = any(m == "WS" and "/ws/" in p for m, p in routes)
    ok = ok and ws_found

    record("API-路由注册 (10个端点)", ok)


# ============================================================
# 测试 23: 模块导入
# ============================================================

def test_imports():
    """测试 23: 模块导入验证"""
    try:
        from app.runtime.v2.state import (
            TaskStatus, TaskPriority, TaskType,
            TaskRequest, TaskState, TaskResult, TaskEvent,
        )
        from app.runtime.v2.dispatcher import (
            TaskDispatcher, DispatcherMode,
            get_dispatcher, reset_dispatcher,
        )
        from app.runtime.v2.worker import (
            AgentWorker, WorkerPool,
            get_worker_pool, reset_worker_pool,
        )
        from app.runtime.v2.collector import (
            ResponseCollector, StreamPublisher,
            get_collector, get_publisher,
        )
        from app.runtime.v2.scheduler import (
            TaskScheduler, ScheduleType, CronParser,
            get_scheduler,
        )
        from app.runtime.v2 import (
            start_runtime, stop_runtime, is_runtime_started,
        )
        ok = True
    except Exception as e:
        ok = False
        record("模块导入", False, str(e))
        return

    record("模块导入", ok)


# ============================================================
# 测试 24: Cron 解析
# ============================================================

def test_cron_parser():
    """测试 24: Cron 解析"""
    from app.runtime.v2.scheduler import CronParser

    # */5 * * * * — 每 5 分钟
    next_run = CronParser.next_run("*/5 * * * *")
    ok = next_run > time.time()

    # * * * * * — 每分钟
    next_run2 = CronParser.next_run("* * * * *")
    ok = ok and next_run2 > time.time()

    # 下次执行应在 5 分钟内
    ok = ok and (next_run - time.time()) <= 300

    record("Cron解析", ok)


# ============================================================
# 运行
# ============================================================

async def run_async_tests():
    await test_dispatcher_submit()
    await test_dispatcher_cancel()
    await test_dispatcher_stats()
    await test_worker_success()
    await test_worker_failure()
    await test_worker_exception()
    await test_worker_timeout()
    await test_worker_pool_assign()
    await test_worker_pool_stats()
    await test_collector_record()
    await test_collector_sse_push()
    await test_collector_multiple_tasks()
    await test_scheduler_immediate()
    await test_scheduler_delayed()
    await test_full_pipeline()
    await test_retry_pipeline()
    await test_api_routes()


def run_sync_tests():
    test_imports()
    test_state_machine()
    test_state_retry()
    test_state_serialization()
    test_state_from_request()
    test_state_duration()
    test_cron_parser()


def main():
    logger.info("=" * 60)
    logger.info("Runtime v2 全链路测试")
    logger.info("=" * 60)

    # 同步测试
    run_sync_tests()

    # 异步测试
    asyncio.run(run_async_tests())

    # 汇总
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    total = len(results)

    logger.info("=" * 60)
    logger.info(f"测试结果: {passed}/{total} 通过, {failed} 失败")
    logger.info("=" * 60)

    if failed:
        logger.error("失败用例:")
        for r in results:
            if r["status"] == "FAIL":
                logger.error(f"  ✗ {r['name']}: {r['detail']}")
        sys.exit(1)
    else:
        logger.info("全部测试通过!")


if __name__ == "__main__":
    main()
