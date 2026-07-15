"""
Agent 模块 - 企业级 Agent 架构

子目录结构：
  core/        - 基类、配置、异常、类型、消息总线
  vision/      - 页面抓取、元素识别、元素融合
  requirement/ - 需求解析、输入路由、类型分类、流程编排
  script/      - 脚本生成、执行、解析、校验、复用
  rag/         - 检索增强生成、向量嵌入、知识检索
  execution/   - 脚本执行、执行器工厂
  graph/       - 图推理、关系分析
  feedback/    - 失败分析、结果反馈
  scheduling/  - 定时任务、任务执行器
  case/        - 用例生成流水线
  testcase/    - 测试用例生成流程
  factory/     - Agent 工厂（注册/注销/获取/按能力查询）
  router/      - Intent Router（任务类型 → Agent 自动路由）
  memory/      - Memory 模块（Session 级独立 Memory）

向后兼容：
- core.base.BaseAgent → LegacyBaseAgent（旧基类，保留兼容）
- core.message_bus.MessageBus → 保留
"""
from app.agent.core.base_agent import BaseAgent
from app.agent.core.config import AgentConfig, create_default_config
from app.agent.core.message import AgentMessage
from app.agent.core.exceptions import (
    AgentError,
    AgentNotFoundError,
    AgentExecutionError,
    AgentTimeoutError,
    AgentLLMError,
    RuntimeNotFoundError,
    RuntimeStateError,
)
from app.agent.core.types import (
    AgentStatus,
    RuntimeStatus,
    MessageType,
    MessageStatus,
    IntentType,
    AgentCapability,
    MemoryType,
    ExecutionResult,
)

# 新架构模块
from app.agent.memory import (
    BaseMemory,
    ListMemory,
    DBMemory,
    MemoryManager,
    get_memory_manager,
)
from app.agent.factory import (
    AgentFactory,
    AgentRegistry,
    auto_register_agents,
)
from app.agent.router import (
    IntentRouter,
    get_intent_router,
)

# 向后兼容：旧模块导出
from app.agent.core.base import (
    BaseAgent as LegacyBaseAgent,
    BaseVisionAgent,
    BaseCrawlAgent,
    BaseMergeAgent,
    BaseCaseAgent,
    BaseScriptAgent,
)
from app.agent.core.message_bus import MessageBus, Message

__all__ = [
    # ---- 新架构：核心 ----
    "BaseAgent",
    "AgentConfig",
    "create_default_config",
    "AgentMessage",
    # ---- 新架构：异常 ----
    "AgentError",
    "AgentNotFoundError",
    "AgentExecutionError",
    "AgentTimeoutError",
    "AgentLLMError",
    "RuntimeNotFoundError",
    "RuntimeStateError",
    # ---- 新架构：类型 ----
    "AgentStatus",
    "RuntimeStatus",
    "MessageType",
    "MessageStatus",
    "IntentType",
    "AgentCapability",
    "MemoryType",
    "ExecutionResult",
    # ---- 新架构：Memory ----
    "BaseMemory",
    "ListMemory",
    "DBMemory",
    "MemoryManager",
    "get_memory_manager",
    # ---- 新架构：Factory ----
    "AgentFactory",
    "AgentRegistry",
    "auto_register_agents",
    # ---- 新架构：Router ----
    "IntentRouter",
    "get_intent_router",
    # ---- 向后兼容 ----
    "LegacyBaseAgent",
    "BaseVisionAgent",
    "BaseCrawlAgent",
    "BaseMergeAgent",
    "BaseCaseAgent",
    "BaseScriptAgent",
    "MessageBus",
    "Message",
]
