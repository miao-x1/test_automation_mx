"""
统一任务上下文

TaskContext 是整个任务执行过程中的状态载体，
在编排器的各个步骤之间传递数据。

职责：
  1. 携带用户输入（payload）
  2. 累积各步骤输出（step_outputs）
  3. 追踪当前执行状态（current_step, status）
  4. 提供 merge_input() 方法：合并 payload + 前序步骤输出
  5. 提供 to_dict() 方法：序列化为 DB 可存储格式

设计原则：
  - 上下文是可变的（每步追加输出）
  - 但每步的输出一旦写入不可修改
  - 上下文不直接操作数据库，只负责状态管理
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.runtime.event import StepStatus


@dataclass
class StepRecord:
    """单步执行记录"""
    step_name: str
    agent_name: str
    action: str
    status: str = StepStatus.PENDING.value
    output: Any = None
    error: str = ""
    duration_ms: int = 0
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_name": self.step_name,
            "agent_name": self.agent_name,
            "action": self.action,
            "status": self.status,
            "output": _safe_serialize(self.output),
            "error": self.error,
            "duration_ms": self.duration_ms,
        }


@dataclass
class TaskContext:
    """
    任务执行上下文

    生命周期：
      1. 编排器创建 TaskContext（携带 payload）
      2. 每步执行前，调用 merge_input() 获取合并输入
      3. 每步执行后，调用 add_output() 追加结果
      4. 流程结束后，调用 to_result() 获取最终结果
    """
    # ── 标识 ──
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])

    # ── 任务关联 ──
    task_id: str = ""                           # DB Task ID
    session_id: str = ""                        # 会话 ID
    flow_name: str = ""                          # 流程名称
    user_id: int = 0                             # 用户 ID

    # ── 输入 ──
    payload: Dict[str, Any] = field(default_factory=dict)

    # ── 步骤状态 ──
    step_records: List[StepRecord] = field(default_factory=list)
    _step_outputs: Dict[str, Any] = field(default_factory=dict)  # step_name → output

    # ── 当前状态 ──
    current_step_index: int = 0
    total_steps: int = 0
    status: str = "pending"                     # pending / running / success / failed

    # ── 元数据 ──
    created_at: float = field(default_factory=time.time)
    finished_at: float = 0.0
    error: str = ""

    # ── 可选开关（由 payload 控制） ──
    enable_reuse_check: bool = True
    enable_knowledge_graph: bool = True
    enable_human_review: bool = False

    def __post_init__(self):
        """从 payload 中提取开关"""
        self.enable_reuse_check = self.payload.get("enable_reuse_check", True)
        self.enable_knowledge_graph = self.payload.get("enable_knowledge_graph", True)
        self.enable_human_review = self.payload.get("enable_human_review", False)

    # ── 步骤管理 ──

    def start_step(self, step_name: str, agent_name: str, action: str) -> StepRecord:
        """开始一个新步骤"""
        record = StepRecord(
            step_name=step_name,
            agent_name=agent_name,
            action=action,
            status=StepStatus.RUNNING.value,
            started_at=time.time(),
        )
        self.step_records.append(record)
        self.current_step_index = len(self.step_records) - 1
        self.status = "running"
        return record

    def finish_step(self, step_name: str, output: Any, duration_ms: int = 0) -> None:
        """完成一个步骤"""
        record = self._get_record(step_name)
        if record:
            record.status = StepStatus.SUCCESS.value
            record.output = output
            record.duration_ms = duration_ms
            record.finished_at = time.time()
        self._step_outputs[step_name] = output

    def fail_step(self, step_name: str, error: str, duration_ms: int = 0) -> None:
        """标记步骤失败"""
        record = self._get_record(step_name)
        if record:
            record.status = StepStatus.FAILED.value
            record.error = error
            record.duration_ms = duration_ms
            record.finished_at = time.time()

    def skip_step(self, step_name: str) -> None:
        """标记步骤跳过"""
        record = self._get_record(step_name)
        if record:
            record.status = StepStatus.SKIPPED.value
            record.finished_at = time.time()

    # ── 输入合并 ──

    def merge_input(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """合并 payload + 所有已完成步骤的输出

        这是每步 Agent 的输入。
        后续步骤可以引用前序步骤的结果。

        Args:
            extra: 额外覆盖的键值

        Returns:
            合并后的输入字典
        """
        result = dict(self.payload)
        for step_output in self._step_outputs.values():
            if not isinstance(step_output, dict):
                continue
            for key, value in step_output.items():
                existing = result.get(key)
                # 后续空列表不能冲掉前序步骤已产出的元素/用例
                if (
                    isinstance(value, list)
                    and not value
                    and isinstance(existing, list)
                    and existing
                ):
                    continue
                result[key] = value
        if extra:
            result.update(extra)
        return result

    def get_step_output(self, step_name: str) -> Any:
        """获取某个步骤的输出"""
        return self._step_outputs.get(step_name)

    # ── 条件评估 ──

    def eval_condition(self, condition: Optional[str]) -> bool:
        """评估步骤条件

        支持：
          - None → 始终执行
          - "has:key" → payload 或步骤输出中 key 非空
          - "no:key" → key 为空
          - "enable_xxx" → 开关为 True
          - "and:cond1,cond2" → 多条件 AND
        """
        if condition is None:
            return True

        condition = condition.strip()

        # AND 多条件
        if condition.startswith("and:"):
            parts = condition[4:].split(",")
            return all(self.eval_condition(p.strip()) for p in parts)

        # 构建上下文：payload + 步骤输出
        ctx = self.merge_input()

        # has: 检查非空
        if condition.startswith("has:"):
            key = condition[4:].strip()
            val = ctx.get(key)
            if val is None:
                return False
            if isinstance(val, (list, str, dict)):
                return len(val) > 0
            return bool(val)

        # no: 检查为空
        if condition.startswith("no:"):
            key = condition[3:].strip()
            val = ctx.get(key)
            if val is None:
                return True
            if isinstance(val, (list, str, dict)):
                return len(val) == 0
            return not bool(val)

        # 布尔开关
        return bool(ctx.get(condition, False))

    # ── 结果 ──

    def to_result(self) -> Dict[str, Any]:
        """获取最终执行结果"""
        return {
            "request_id": self.request_id,
            "task_id": self.task_id,
            "flow_name": self.flow_name,
            "status": self.status,
            "total_steps": self.total_steps,
            "completed_steps": len([r for r in self.step_records if r.status == StepStatus.SUCCESS.value]),
            "skipped_steps": len([r for r in self.step_records if r.status == StepStatus.SKIPPED.value]),
            "failed_steps": len([r for r in self.step_records if r.status == StepStatus.FAILED.value]),
            "steps": [r.to_dict() for r in self.step_records],
            "outputs": _safe_serialize(self._step_outputs),
            "error": self.error,
            "duration_s": round(self.finished_at - self.created_at, 2) if self.finished_at else 0,
        }

    def to_sse_result(self) -> Dict[str, Any]:
        """SSE 安全的结果序列化"""
        return _safe_serialize(self.to_result())

    # ── 内部方法 ──

    def _get_record(self, step_name: str) -> Optional[StepRecord]:
        for r in self.step_records:
            if r.step_name == step_name:
                return r
        return None


def _safe_serialize(obj: Any) -> Any:
    """安全序列化"""
    import json
    try:
        json.dumps(obj, ensure_ascii=False, default=str)
        return obj
    except (TypeError, ValueError):
        return str(obj)
