"""
统一运行时框架

架构（产品级重构）：
    FastAPI
      ↓
    Orchestrator（唯一入口）
      ↓
    FlowRegistry（流程定义）
      ↓
    TaskContext（执行上下文）
      ↓
    AgentFactory → AgentRegistry.create()
      ↓
    Agent.execute()
      ↓
    MessageBus（事件广播 → SSE）
      ↓
    TaskState（DB 持久化）

核心原则：
1. 所有用户操作必须经过 Orchestrator
2. API 层禁止直接调用 Agent
3. Agent 只负责能力，不负责流程
4. 流程定义集中在 FlowRegistry
5. Agent 间通信通过 Orchestrator 编排

快速使用：
    from app.runtime import get_orchestrator

    # SSE 流式
    async for event in get_orchestrator().execute(
        flow_name="unified_test_flow",
        payload={"requirement": "测试登录功能"},
    ):
        yield event

    # 同步
    result = get_orchestrator().execute_sync("image_test_flow", payload)
"""
# ===== 统一编排（新架构） =====
from app.runtime.event import (
    TaskEvent,
    EventType,
    StepStatus,
    AgentRequest as RuntimeAgentRequest,
    AgentResponse as RuntimeAgentResponse,
)
from app.runtime.task_context import TaskContext, StepRecord
from app.runtime.message_bus import MessageBus, get_message_bus, reset_message_bus
from app.runtime.agent_factory import AgentFactory
from app.runtime.flow_registry import (
    TaskFlow,
    FlowStep,
    get_flow,
    is_flow_exists,
    list_flows,
    get_flow_names,
)
from app.runtime.orchestrator import Orchestrator, get_orchestrator

# ===== 旧版组件（向后兼容） =====
from app.runtime.messages import (
    TaskMessage,
    AgentRequest,
    AgentResponse,
    ProgressMessage,
    ResultMessage,
    ErrorMessage,
    SessionMessage,
    AgentEventMessage,
    TaskStatusMessage,
)

from app.runtime.base_agent import (
    BaseRoutedAgent,
    action_handler,
)

from app.runtime.collector import (
    CollectorAgent,
    TaskResult,
)

from app.runtime.event_bus import (
    EventBus,
    Subscriber,
    get_event_bus,
)

from app.runtime.runtime import (
    CoreRuntime,
    get_core_runtime,
)

from app.runtime.agent_registry import (
    AgentRegistry,
    AgentDefinition,
    AGENT_DEFINITIONS,
    get_agent_registry,
)

from app.runtime.adapter import (
    LegacyAgentAdapter,
)

from app.runtime.runtime_manager import (
    RuntimeManager,
    SessionInfo,
    get_runtime_manager,
)

from app.runtime.task_runtime import (
    TaskRuntime,
    get_task_runtime,
)

from app.runtime.flow_node_adapter import (
    FlowNodeAdapter,
)

from app.runtime.graph_flow_manager import (
    GraphFlowManager,
    NodeSpec,
    get_graph_flow_manager,
)

from app.runtime.session_manager import (
    SessionManager,
    SessionState,
    SessionStatus,
    get_session_manager,
)

__all__ = [
    # ── 统一编排（新架构）──
    "Orchestrator",
    "get_orchestrator",
    "TaskEvent",
    "EventType",
    "StepStatus",
    "TaskContext",
    "StepRecord",
    "MessageBus",
    "get_message_bus",
    "reset_message_bus",
    "AgentFactory",
    "TaskFlow",
    "FlowStep",
    "get_flow",
    "is_flow_exists",
    "list_flows",
    "get_flow_names",
    # ── 旧版组件（向后兼容）──
    "TaskMessage",
    "AgentRequest",
    "AgentResponse",
    "ProgressMessage",
    "ResultMessage",
    "ErrorMessage",
    "SessionMessage",
    "AgentEventMessage",
    "TaskStatusMessage",
    "BaseRoutedAgent",
    "action_handler",
    "CollectorAgent",
    "TaskResult",
    "EventBus",
    "Subscriber",
    "get_event_bus",
    "CoreRuntime",
    "get_core_runtime",
    "AgentRegistry",
    "AgentDefinition",
    "AGENT_DEFINITIONS",
    "get_agent_registry",
    "LegacyAgentAdapter",
    "RuntimeManager",
    "SessionInfo",
    "get_runtime_manager",
    "TaskRuntime",
    "get_task_runtime",
    "FlowNodeAdapter",
    "GraphFlowManager",
    "NodeSpec",
    "get_graph_flow_manager",
    "SessionManager",
    "SessionState",
    "SessionStatus",
    "get_session_manager",
]
