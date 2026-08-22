"""
Runtime 任务持久化服务

职责:
    1. 将 TaskState 变更同步到 runtime_task 表
    2. 从 DB 恢复崩溃前的任务
    3. 提供历史任务查询
    4. 提供指标统计 (成功率/平均耗时/吞吐量)

被 TaskDispatcher 调用:
    - submit()  → create_task()
    - complete() → update_task()
    - recover()  → load_pending_tasks()
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import desc, asc, func, and_, or_

logger = logging.getLogger(__name__)


class RuntimePersistence:
    """Runtime 任务持久化"""

    def __init__(self) -> None:
        self._enabled = False
        try:
            from app.db.database import SessionLocal
            from app.models.runtime_task import RuntimeTask
            self._SessionLocal = SessionLocal
            self._RuntimeTask = RuntimeTask
            self._enabled = True
        except Exception as e:
            logger.warning(f"[RuntimePersistence] 初始化失败,持久化禁用: {e}")

    @property
    def enabled(self) -> bool:
        return self._enabled

    # ----------------------------------------------------------
    # 创建任务记录
    # ----------------------------------------------------------

    def create_task(self, state: Any) -> None:
        """创建任务记录 (submit 时调用)

        Args:
            state: TaskState 实例
        """
        if not self._enabled:
            return
        try:
            db = self._SessionLocal()
            try:
                record = self._RuntimeTask(
                    task_id=state.task_id,
                    parent_task_id=state.payload.get("parent_task_id"),
                    task_type=state.task_type,
                    agent_name=state.agent_name,
                    action=state.action,
                    payload_json=json.dumps(state.payload, ensure_ascii=False, default=str)[:50000] if state.payload else None,
                    status=state.status.value if hasattr(state.status, 'value') else str(state.status),
                    priority=state.priority.value if hasattr(state.priority, 'value') else str(state.priority),
                    retry_count=state.retry_count,
                    max_retries=state.max_retries,
                    created_at_ts=datetime.fromisoformat(state.created_at) if state.created_at else datetime.now(),
                    timeout_seconds=state.timeout_seconds,
                    user_id=state.user_id,
                    session_id=state.session_id,
                )
                db.add(record)
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[RuntimePersistence] create_task 失败 (忽略): {e}")

    # ----------------------------------------------------------
    # 更新任务记录
    # ----------------------------------------------------------

    def update_task(
        self,
        task_id: str,
        status: Optional[str] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
        duration_ms: Optional[int] = None,
        worker_id: Optional[str] = None,
        result: Optional[Any] = None,
        error: Optional[str] = None,
        events_count: int = 0,
        retry_count: Optional[int] = None,
    ) -> None:
        """更新任务记录 (complete 时调用)"""
        if not self._enabled:
            return
        try:
            db = self._SessionLocal()
            try:
                record = db.query(self._RuntimeTask).filter(
                    self._RuntimeTask.task_id == task_id
                ).first()
                if record is None:
                    logger.debug(f"[RuntimePersistence] 任务不存在: {task_id}")
                    return

                if status:
                    record.status = status
                if started_at:
                    record.started_at_ts = datetime.fromisoformat(started_at)
                if completed_at:
                    record.completed_at_ts = datetime.fromisoformat(completed_at)
                if duration_ms is not None:
                    record.duration_ms = duration_ms
                if worker_id:
                    record.worker_id = worker_id
                if result is not None:
                    record.result_json = json.dumps(result, ensure_ascii=False, default=str)[:50000]
                if error:
                    record.error = error[:5000]
                if events_count:
                    record.events_count = events_count
                if retry_count is not None:
                    record.retry_count = retry_count

                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[RuntimePersistence] update_task 失败 (忽略): {e}")

    # ----------------------------------------------------------
    # 崩溃恢复
    # ----------------------------------------------------------

    def load_pending_tasks(self) -> List[Dict[str, Any]]:
        """加载未完成的任务 (recover 时调用)

        Returns:
            任务字典列表 (可重建 TaskState)
        """
        if not self._enabled:
            return []
        try:
            db = self._SessionLocal()
            try:
                records = db.query(self._RuntimeTask).filter(
                    self._RuntimeTask.status.in_(["pending", "running"])
                ).all()
                return [r.to_dict() for r in records]
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[RuntimePersistence] load_pending_tasks 失败: {e}")
            return []

    def mark_recovered(self, task_id: str) -> None:
        """标记任务已恢复 (重置为 pending)"""
        if not self._enabled:
            return
        try:
            db = self._SessionLocal()
            try:
                record = db.query(self._RuntimeTask).filter(
                    self._RuntimeTask.task_id == task_id
                ).first()
                if record:
                    record.status = "pending"
                    record.started_at_ts = None
                    record.worker_id = None
                    db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.debug(f"[RuntimePersistence] mark_recovered 失败: {e}")

    # ----------------------------------------------------------
    # 历史查询
    # ----------------------------------------------------------

    def query_history(
        self,
        status: Optional[str] = None,
        agent_name: Optional[str] = None,
        user_id: Optional[int] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """查询历史任务

        Returns:
            (任务列表, 总数)
        """
        if not self._enabled:
            return [], 0
        try:
            db = self._SessionLocal()
            try:
                query = db.query(self._RuntimeTask)

                if status:
                    query = query.filter(self._RuntimeTask.status == status)
                if agent_name:
                    query = query.filter(self._RuntimeTask.agent_name == agent_name)
                if user_id is not None:
                    query = query.filter(self._RuntimeTask.user_id == user_id)
                if start_time:
                    query = query.filter(self._RuntimeTask.created_at_ts >= start_time)
                if end_time:
                    query = query.filter(self._RuntimeTask.created_at_ts <= end_time)

                total = query.count()
                records = query.order_by(
                    desc(self._RuntimeTask.created_at_ts)
                ).offset(offset).limit(limit).all()

                return [r.to_dict() for r in records], total
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[RuntimePersistence] query_history 失败: {e}")
            return [], 0

    def get_task_by_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """按 task_id 查询"""
        if not self._enabled:
            return None
        try:
            db = self._SessionLocal()
            try:
                record = db.query(self._RuntimeTask).filter(
                    self._RuntimeTask.task_id == task_id
                ).first()
                return record.to_dict() if record else None
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[RuntimePersistence] get_task_by_id 失败: {e}")
            return None

    # ----------------------------------------------------------
    # 指标统计
    # ----------------------------------------------------------

    def get_metrics(
        self,
        hours: int = 24,
        agent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """获取指标统计

        Args:
            hours: 统计时间范围 (最近 N 小时)
            agent_name: 按 Agent 过滤 (None=全部)

        Returns:
            指标字典:
                - total: 总任务数
                - by_status: 按状态分组
                - success_rate: 成功率
                - avg_duration_ms: 平均耗时
                - p50_duration_ms: 中位数耗时
                - p95_duration_ms: 95 分位耗时
                - throughput: 吞吐量 (任务/分钟)
                - by_agent: 按 Agent 分组
                - hourly: 按小时分组的趋势
        """
        if not self._enabled:
            return {}
        try:
            db = self._SessionLocal()
            try:
                start_time = datetime.now() - timedelta(hours=hours)
                query = db.query(self._RuntimeTask).filter(
                    self._RuntimeTask.created_at_ts >= start_time
                )
                if agent_name:
                    query = query.filter(self._RuntimeTask.agent_name == agent_name)

                records = query.all()

                if not records:
                    return {
                        "hours": hours,
                        "total": 0,
                        "by_status": {},
                        "success_rate": 0,
                        "avg_duration_ms": 0,
                        "p50_duration_ms": 0,
                        "p95_duration_ms": 0,
                        "throughput": 0,
                        "by_agent": {},
                        "hourly": [],
                    }

                # 按状态分组
                by_status: Dict[str, int] = {}
                durations: List[int] = []
                by_agent: Dict[str, Dict[str, Any]] = {}
                hourly: Dict[str, Dict[str, int]] = {}

                for r in records:
                    # 状态统计
                    status = r.status.value if hasattr(r.status, 'value') else str(r.status)
                    by_status[status] = by_status.get(status, 0) + 1

                    # 耗时统计
                    if r.duration_ms:
                        durations.append(r.duration_ms)

                    # 按 Agent 统计
                    if r.agent_name not in by_agent:
                        by_agent[r.agent_name] = {
                            "total": 0, "success": 0, "failed": 0,
                            "total_duration_ms": 0,
                        }
                    by_agent[r.agent_name]["total"] += 1
                    if status == "success":
                        by_agent[r.agent_name]["success"] += 1
                    elif status in ("failed", "timeout"):
                        by_agent[r.agent_name]["failed"] += 1
                    if r.duration_ms:
                        by_agent[r.agent_name]["total_duration_ms"] += r.duration_ms

                    # 按小时统计
                    if r.created_at_ts:
                        hour_key = r.created_at_ts.strftime("%Y-%m-%d %H:00")
                        if hour_key not in hourly:
                            hourly[hour_key] = {"total": 0, "success": 0, "failed": 0}
                        hourly[hour_key]["total"] += 1
                        if status == "success":
                            hourly[hour_key]["success"] += 1
                        elif status in ("failed", "timeout"):
                            hourly[hour_key]["failed"] += 1

                # 计算指标
                total = len(records)
                success_count = by_status.get("success", 0)
                success_rate = (success_count / total * 100) if total > 0 else 0

                # 耗时统计
                durations.sort()
                avg_duration = sum(durations) / len(durations) if durations else 0
                p50 = durations[len(durations) // 2] if durations else 0
                p95 = durations[int(len(durations) * 0.95)] if durations else 0

                # 吞吐量 (任务/分钟)
                minutes = hours * 60
                throughput = total / minutes if minutes > 0 else 0

                # Agent 统计补充
                for agent, data in by_agent.items():
                    data["success_rate"] = (
                        data["success"] / data["total"] * 100
                        if data["total"] > 0 else 0
                    )
                    data["avg_duration_ms"] = (
                        data["total_duration_ms"] / data["success"]
                        if data["success"] > 0 else 0
                    )

                # 按小时排序
                hourly_list = [
                    {"hour": k, **v}
                    for k, v in sorted(hourly.items())
                ]

                return {
                    "hours": hours,
                    "total": total,
                    "by_status": by_status,
                    "success_rate": round(success_rate, 2),
                    "avg_duration_ms": round(avg_duration, 0),
                    "p50_duration_ms": p50,
                    "p95_duration_ms": p95,
                    "throughput": round(throughput, 2),
                    "by_agent": by_agent,
                    "hourly": hourly_list,
                }
            finally:
                db.close()
        except Exception as e:
            logger.error(f"[RuntimePersistence] get_metrics 失败: {e}")
            return {}


# ============================================================
# 单例
# ============================================================

_persistence: Optional[RuntimePersistence] = None


def get_runtime_persistence() -> RuntimePersistence:
    """获取全局 RuntimePersistence 单例"""
    global _persistence
    if _persistence is None:
        _persistence = RuntimePersistence()
        if _persistence.enabled:
            logger.info("[RuntimePersistence] 持久化服务已启用")
        else:
            logger.warning("[RuntimePersistence] 持久化服务禁用")
    return _persistence
