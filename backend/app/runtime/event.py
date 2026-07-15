"""
统一事件类型定义

所有运行时通信使用这些事件类型：
  - TaskEvent:       任务生命周期事件（flow_start/step_start/step_done/flow_done）
  - AgentRequest:    编排器 → Agent 的调用请求
  - AgentResponse:   Agent → 编排器 的执行结果
  - ProgressEvent:   进度推送（SSE）
  - ErrorEvent:       错误通知
  - LogEvent:         日志事件

设计原则：
  1. 所有事件均为 Pydantic BaseModel，可序列化
  2. 事件是不可变的（创建后不修改）
  3. 每个事件携带 task_id + request_id 用于追踪
  4. Agent 不得直接调用其它 Agent，必须通过事件
"""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


def _gen_id() -> str:
    return uuid.uuid4().hex[:16]


def _now() -> float:
    return time.time()


# ── 事件类型枚举 ──

class EventType(str, Enum):
    """事件类型"""
    FLOW_START = "flow_start"
    FLOW_SUCCESS = "flow_success"
    FLOW_FAILED = "flow_failed"
    STEP_START = "step_start"
    STEP_SUCCESS = "step_success"
    STEP_FAILED = "step_failed"
    STEP_SKIPPED = "step_skipped"
    PROGRESS = "progress"
    LOG = "log"
    ERROR = "error"
    DONE = "done"


class StepStatus(str, Enum):
    """步骤状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── 基础事件 ──

class TaskEvent(BaseModel):
    """任务生命周期事件

    编排器在每个阶段发布此事件，
    MessageBus 广播给订阅者（SSE → 前端）。
    """
    event: str                        # EventType 的值
    request_id: str = Field(default_factory=_gen_id)
    task_id: str = ""
    flow_name: str = ""
    step_name: str = ""               # 当前步骤名（flow 级事件为空）
    agent_name: str = ""              # 当前 Agent 名
    step_index: int = 0
    total_steps: int = 0
    progress: int = 0                 # 0-100
    data: Dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    timestamp: float = Field(default_factory=_now)

    def to_sse(self) -> Dict[str, Any]:
        """转换为 SSE 可序列化的 dict"""
        return {
            "event": self.event,
            "request_id": self.request_id,
            "task_id": self.task_id,
            "flow_name": self.flow_name,
            "step_name": self.step_name,
            "agent_name": self.agent_name,
            "step_index": self.step_index,
            "total_steps": self.total_steps,
            "progress": self.progress,
            "data": _safe(self.data),
            "error": self.error,
            "timestamp": self.timestamp,
        }


# ── Agent 请求/响应 ──

class AgentRequest(BaseModel):
    """编排器 → Agent 的调用请求

    AgentFactory 根据 agent_name 创建 Agent 实例，
    然后调用 action 对应的方法，传入 payload。
    """
    request_id: str = Field(default_factory=_gen_id)
    task_id: str = ""
    agent_name: str = ""               # 目标 Agent 名称
    action: str = "execute"            # 调用的方法名
    payload: Dict[str, Any] = Field(default_factory=dict)
    session_id: str = ""
    flow_name: str = ""
    step_name: str = ""


class AgentResponse(BaseModel):
    """Agent → 编排器 的执行结果"""
    request_id: str = ""
    agent_name: str = ""
    status: str = "success"            # success / error
    data: Any = None                   # Agent 输出
    error: str = ""
    duration_ms: int = 0


# ── 工具函数 ──

def _safe(obj: Any) -> Any:
    """安全序列化"""
    import json
    try:
        json.dumps(obj, ensure_ascii=False, default=str)
        return obj
    except (TypeError, ValueError):
        return str(obj)
