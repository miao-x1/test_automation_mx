"""
AutoGen Core Runtime - 消息类型定义

所有 Agent 间通信统一使用以下消息类型：
- TaskMessage:         FastAPI → Agent  (启动任务)
- AgentRequest:        Agent → Agent   (请求另一个Agent服务)
- AgentResponse:       Agent → Agent   (响应请求)
- ProgressMessage:      Agent → 前端     (进度推送，通过SSE)
- ResultMessage:       Agent → Collector (最终结果投递)
- ErrorMessage:        Agent → 前端     (错误通知)
- AgentEventMessage:   Agent → Collector (详细事件: Prompt/Model/Token/重试等)
- TaskStatusMessage:   Collector → 前端   (任务状态变更通知)

设计原则：
1. 所有消息均为 Pydantic BaseModel（AutoGen Core 支持，且兼容 Union 类型）
2. Agent 不得直接调用其它 Agent 的方法
3. 所有通信通过 runtime.send_message() 或 publish_message() 完成
4. 所有 Agent 输出统一发送给 CollectorAgent，不直接返回 FastAPI
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional
import uuid
import time


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class TaskMessage(BaseModel):
    """
    FastAPI → Agent: 启动一个任务

    由 TaskRuntime 发送，目标 Agent 接收后开始执行。
    """
    task_id: str = Field(default_factory=_gen_uuid)
    task_type: str = ""                         # 任务类型: requirement / script / execution / case ...
    action: str = "execute"                    # 调用的方法名
    payload: Dict[str, Any] = Field(default_factory=dict)  # 方法参数
    user_id: int = 0                            # 用户ID（0=匿名，多用户隔离）
    session_id: str = ""                       # 会话ID（多会话隔离）
    reply_to: str = "collector"               # 结果投递目标 Agent 类型


class AgentRequest(BaseModel):
    """
    Agent → Agent: 请求另一个 Agent 的服务

    sender 通过 runtime.send_message() 将此消息发送给目标 Agent。
    目标 Agent 根据 action 调用对应方法，返回 AgentResponse。
    """
    request_id: str = Field(default_factory=_gen_uuid)
    sender_type: str = ""                  # 发送方 Agent 类型
    sender_key: str = ""                   # 发送方 Agent key (session标识)
    target_action: str = "execute"         # 目标方法名
    payload: Dict[str, Any] = Field(default_factory=dict)
    reply_to: str = "collector"            # 结果投递目标


class AgentResponse(BaseModel):
    """
    Agent → Agent: 响应请求

    目标 Agent 处理完 AgentRequest 后返回此消息。
    """
    request_id: str = ""
    sender_type: str = ""
    status: str = "success"                # success / error
    data: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""                        # 空字符串表示无错误
    duration: float = 0.0                  # 耗时（秒）


class ProgressMessage(BaseModel):
    """
    Agent → 前端: 进度推送

    通过 publish_message 发布到 topic，
    TaskRuntime 订阅后通过 SSE 推送到前端。
    """
    task_id: str = ""
    agent_type: str = ""
    step: str = ""                         # 当前步骤名称
    status: str = "running"                # running / completed / failed
    progress: float = 0.0                  # 0.0 ~ 1.0
    message: str = ""                      # 描述文本
    timestamp: float = Field(default_factory=time.time)
    data: Dict[str, Any] = Field(default_factory=dict)  # 额外数据


class ResultMessage(BaseModel):
    """
    Agent → CollectorAgent: 最终结果投递

    Agent 完成任务后将结果发送给 CollectorAgent。
    CollectorAgent 收集所有结果，保存到数据库。
    """
    task_id: str = ""
    agent_type: str = ""                   # 产出此结果的 Agent 类型
    agent_key: str = ""                    # Agent 实例 key
    status: str = "success"                # success / error
    data: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""                        # 空字符串表示无错误
    duration: float = 0.0
    timestamp: float = Field(default_factory=time.time)
    is_final: bool = True                  # 是否为最终结果（Pipeline 中间结果为 False）


class ErrorMessage(BaseModel):
    """
    Agent → 前端: 错误通知

    Agent 发生不可恢复错误时发送。
    """
    task_id: str = ""
    agent_type: str = ""
    error_type: str = "AgentError"
    message: str = ""
    traceback: str = ""
    timestamp: float = Field(default_factory=time.time)


class SessionMessage(BaseModel):
    """
    系统消息: 会话管理

    用于通知 Agent 会话的创建和销毁。
    """
    session_id: str = ""
    user_id: int = 0
    action: str = "create"                 # create / destroy
    agent_types: List[str] = Field(default_factory=list)  # 需要初始化的 Agent 类型


class AgentEventMessage(BaseModel):
    """
    Agent → CollectorAgent: 详细事件记录

    记录所有关键节点：
    - start:  Agent 开始处理
    - end:    Agent 结束处理
    - prompt: LLM 调用（含 Prompt 内容、模型、Token）
    - model:  模型信息
    - token:  Token 消耗
    - error:  错误发生
    - retry:  重试事件
    - result: 中间/最终结果
    - progress: 进度更新

    CollectorAgent 收到此消息后：
    1. 保存到 agent_event 表
    2. 记录日志
    3. 通过 EventBus 推送 SSE / WebSocket
    """
    task_id: str = ""
    session_key: str = "default"
    agent_type: str = ""
    agent_name: str = ""
    event_type: str = "progress"            # start/end/prompt/model/token/error/retry/result/progress
    step: str = ""
    status: str = "info"                    # info/success/warning/error

    # LLM 详细信息
    model_name: str = ""
    prompt: str = ""                        # System Prompt（截断保存）
    user_prompt: str = ""                   # User Prompt（截断保存）
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # 耗时
    duration: float = 0.0

    # 数据
    data: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""
    error_message: str = ""
    error_traceback: str = ""

    # 重试
    retry_count: int = 0
    is_retry: bool = False

    # 消息类型标记
    message_type: str = ""

    # 是否最终结果
    is_final: bool = False

    timestamp: float = Field(default_factory=time.time)


class TaskStatusMessage(BaseModel):
    """
    CollectorAgent → 前端: 任务状态变更通知

    当任务状态发生变化时（开始/进行中/完成/失败），
    CollectorAgent 通过 EventBus 推送此消息。
    """
    task_id: str = ""
    session_key: str = "default"
    status: str = "running"                 # running/completed/failed/timeout
    step: str = ""
    agent_type: str = ""
    message: str = ""
    progress: float = 0.0                   # 0.0 ~ 1.0
    timestamp: float = Field(default_factory=time.time)
    data: Dict[str, Any] = Field(default_factory=dict)
