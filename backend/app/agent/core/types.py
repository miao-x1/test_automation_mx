"""
Agent 统一类型定义
提供所有 Agent 模块共享的枚举和类型别名。
"""
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field


class AgentStatus(str, Enum):
    """Agent 运行状态"""
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class RuntimeStatus(str, Enum):
    """Runtime 生命周期状态"""
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


class MessageStatus(str, Enum):
    """消息状态"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class MessageType(str, Enum):
    """消息类型"""
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    PROGRESS = "progress"
    ERROR = "error"
    SYSTEM = "system"


class IntentType(str, Enum):
    """意图类型 - 用于 Intent Router 路由"""
    IMAGE = "image"
    PDF = "pdf"
    DOCUMENT = "document"
    SWAGGER = "swagger"
    API_DOC = "api_doc"
    VIDEO = "video"
    SCHEMA = "schema"
    URL = "url"
    SCRIPT = "script"
    TEXT = "text"
    REQUIREMENT = "requirement"
    MIXED = "mixed"
    MINDMAP = "mindmap"
    REVIEW = "review"
    KNOWLEDGE = "knowledge"
    EXECUTION = "execution"
    GRAPH = "graph"
    RAG = "rag"


class AgentCapability(str, Enum):
    """Agent 能力标签 - 支持按能力查询 Agent"""
    VISION = "vision"
    CRAWL = "crawl"
    MERGE = "merge"
    CASE_GENERATE = "case_generate"
    SCRIPT_GENERATE = "script_generate"
    SCRIPT_EXECUTE = "script_execute"
    REQUIREMENT_PARSE = "requirement_parse"
    RAG_RETRIEVE = "rag_retrieve"
    GRAPH_INFER = "graph_infer"
    KNOWLEDGE_UPDATE = "knowledge_update"
    EMBEDDING = "embedding"
    FEEDBACK = "feedback"
    RELATION = "relation"
    FLOW_PARSE = "flow_parse"
    FLOW_SCRIPT = "flow_script"
    SCHEDULE = "schedule"
    REUSE_CHECK = "reuse_check"
    GRAPH_SEARCH = "graph_search"
    INTENT_ROUTE = "intent_route"
    DATA_FUSION = "data_fusion"
    TYPE_CLASSIFY = "type_classify"
    SCRIPT_PARSE = "script_parse"
    SCRIPT_VALIDATE = "script_validate"
    MOCK = "mock"
    PAGE_STATE = "page_state"
    STRATEGY = "strategy"
    MINDMAP = "mindmap"
    REVIEW = "review"
    API_EXTRACT = "api_extract"


class MemoryType(str, Enum):
    """Memory 存储类型"""
    LIST = "list"
    DB = "database"
    AUTOGEN = "autogen"


class ProviderType(str, Enum):
    """LLM 提供者类型"""
    DASHSCOPE = "dashscope"
    DEEPSEEK = "deepseek"
    OLLAMA = "ollama"
    OPENAI = "openai"
    UITARS = "uitars"
    MOCK = "mock"


# 类型别名
Payload = Dict[str, Any]
AgentOutput = Dict[str, Any]
SSECallback = Optional[Callable[[str], Awaitable[None]]]


@dataclass
class ExecutionResult:
    """统一执行结果"""
    agent_name: str
    status: AgentStatus
    output: Any = None
    error: Optional[str] = None
    duration: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration": round(self.duration, 3),
            "metadata": self.metadata,
        }
