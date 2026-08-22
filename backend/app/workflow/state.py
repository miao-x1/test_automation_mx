"""
WorkflowState — 工作流状态管理

定义工作流执行过程中的共享状态:
- 用户需求 (原始输入)
- 中间结果 (各节点输出)
- 最终结果 (工作流完成后的产物)
- 执行元数据 (耗时、状态、错误等)

设计原则:
1. 所有节点共享同一个 WorkflowState
2. 节点通过 input_keys 声明依赖, 通过 output_key 声明产出
3. 状态可序列化, 支持 SSE 推送和持久化
"""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class WorkflowStatus(str, Enum):
    """工作流状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class NodeStatus(str, Enum):
    """节点状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class NodeResult:
    """单个节点的执行结果"""
    node_name: str
    status: NodeStatus = NodeStatus.PENDING
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return round((self.completed_at - self.started_at) * 1000, 1)
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class WorkflowState:
    """工作流状态 — 贯穿整个工作流执行的生命周期

    保存内容:
        requirement:  用户原始需求文本 (如 "测试登录功能")
        intermediate: 中间结果 (节点名 → 输出 dict)
        final_result: 最终结果 (工作流完成后的产物)
        metadata:    执行元数据 (test_type, target_url, session_id 等)
    """
    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    workflow_name: str = ""
    requirement: str = ""
    status: WorkflowStatus = WorkflowStatus.PENDING

    # 中间结果: { "requirement_node": {...}, "rag_node": {...}, ... }
    intermediate: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    # 节点执行记录 (按执行顺序)
    node_results: List[NodeResult] = field(default_factory=list)

    # 最终结果
    final_result: Optional[Dict[str, Any]] = None

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # 当前正在执行的节点
    current_node: Optional[str] = None

    # SSE 事件队列 (由 Runtime 注入)
    _event_callback: Optional[Any] = field(default=None, repr=False)

    # ------------------------------------------------------------------ #
    #  读写接口                                                           #
    # ------------------------------------------------------------------ #

    def get(self, key: str, default: Any = None) -> Any:
        """从中间结果中读取值 (跨节点)

        查找顺序:
        1. metadata[key]
        2. 在所有 intermediate 值中查找 key
        """
        if key in self.metadata:
            return self.metadata[key]
        for node_output in self.intermediate.values():
            if key in node_output:
                return node_output[key]
        return default

    def get_node_output(self, node_name: str) -> Dict[str, Any]:
        """获取指定节点的完整输出"""
        return self.intermediate.get(node_name, {})

    def set_node_output(self, node_name: str, output: Dict[str, Any]) -> None:
        """设置节点输出到中间结果"""
        self.intermediate[node_name] = output

    def set(self, key: str, value: Any) -> None:
        """设置元数据"""
        self.metadata[key] = value

    def add_node_result(self, result: NodeResult) -> None:
        """追加节点执行记录"""
        self.node_results.append(result)

    def emit_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """推送 SSE 事件 (如果有回调)"""
        if self._event_callback:
            try:
                import asyncio
                if asyncio.iscoroutinefunction(self._event_callback):
                    asyncio.create_task(self._event_callback({
                        "event": event_type,
                        "data": data,
                        "workflow_id": self.workflow_id,
                        "timestamp": time.time(),
                    }))
                else:
                    self._event_callback({
                        "event": event_type,
                        "data": data,
                        "workflow_id": self.workflow_id,
                        "timestamp": time.time(),
                    })
            except Exception:
                pass  # 事件推送失败不影响工作流执行

    # ------------------------------------------------------------------ #
    #  序列化                                                             #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "requirement": self.requirement,
            "status": self.status.value,
            "intermediate": self.intermediate,
            "node_results": [r.to_dict() for r in self.node_results],
            "final_result": self.final_result,
            "metadata": self.metadata,
            "error": self.error,
            "current_node": self.current_node,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WorkflowState":
        state = cls(
            workflow_id=d.get("workflow_id", str(uuid.uuid4())[:12]),
            workflow_name=d.get("workflow_name", ""),
            requirement=d.get("requirement", ""),
            status=WorkflowStatus(d.get("status", "pending")),
            intermediate=d.get("intermediate", {}),
            final_result=d.get("final_result"),
            metadata=d.get("metadata", {}),
            error=d.get("error"),
            current_node=d.get("current_node"),
            started_at=d.get("started_at"),
            completed_at=d.get("completed_at"),
        )
        for nr in d.get("node_results", []):
            state.node_results.append(NodeResult(
                node_name=nr["node_name"],
                status=NodeStatus(nr.get("status", "pending")),
                output=nr.get("output", {}),
                error=nr.get("error"),
            ))
        return state

    @classmethod
    def create(
        cls,
        requirement: str,
        workflow_name: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> "WorkflowState":
        """创建工作流状态"""
        return cls(
            requirement=requirement,
            workflow_name=workflow_name,
            metadata=metadata or {},
            started_at=time.time(),
        )
