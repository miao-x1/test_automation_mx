"""
AgentExecutionMonitor - Agent 执行监控系统

职责：
  1. 记录每个 Agent 执行的开始/结束/状态/输入/输出
  2. 提供执行时间线查询（类似 Dify 工作流展示）
  3. 支持查看失败节点详情
  4. 提供执行统计

使用现有模型：
  - AgentExecutionLog（完整执行记录）
  - AgentEvent（细粒度事件溯源）

集成方式：
  TaskOrchestrator._execute_agent() 调用 monitor.record_start() / record_end()
"""
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.logger import log


class AgentExecutionMonitor:
    """
    Agent 执行监控器

    记录每个 Agent 的执行详情，支持前端时间线展示。

    使用方式：
      monitor = AgentExecutionMonitor()
      log_id = monitor.record_start(agent_name, step, input_data, task_id, session_id)
      try:
          output = agent.execute(...)
          monitor.record_success(log_id, output, duration_ms)
      except Exception as e:
          monitor.record_failure(log_id, str(e), duration_ms)
    """

    # ------------------------------------------------------------------
    # 记录执行
    # ------------------------------------------------------------------

    def record_start(
        self,
        agent_name: str,
        step: str,
        input_data: Dict[str, Any],
        task_id: str = "",
        session_id: str = "",
        flow_name: str = "",
    ) -> str:
        """记录 Agent 执行开始

        Args:
            agent_name: Agent 名称
            step: 步骤名称
            input_data: 输入数据
            task_id: 任务ID
            session_id: 会话ID
            flow_name: 流程名称

        Returns:
            execution_log_id（用于后续 record_success/record_failure）
        """
        execution_id = str(uuid.uuid4())

        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                log_record = AgentExecutionLog(
                    session_id=session_id,
                    task_id=task_id,
                    agent_name=agent_name,
                    step=step,
                    input_data=json.dumps(input_data, ensure_ascii=False, default=str) if input_data else None,
                    status="running",
                    start_time=datetime.now(timezone.utc),
                    extra_json=json.dumps({"flow_name": flow_name, "execution_id": execution_id}, ensure_ascii=False) if flow_name else json.dumps({"execution_id": execution_id}),
                )
                db.add(log_record)
                db.commit()
                db.refresh(log_record)

                log.info(
                    f"AgentExecutionMonitor | 记录开始 | "
                    f"agent={agent_name} | step={step} | "
                    f"log_id={log_record.id} | task_id={task_id}"
                )
                return str(log_record.id)

            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | record_start 失败: {e}")
            return ""

    def record_success(
        self,
        log_id: str,
        output: Any,
        duration_ms: float = 0,
        tokens_used: int = 0,
        model_name: str = "",
    ) -> None:
        """记录 Agent 执行成功"""
        if not log_id:
            return

        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                record = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.id == int(log_id)
                ).first()
                if record:
                    record.status = "success"
                    record.end_time = datetime.now(timezone.utc)
                    record.duration = duration_ms / 1000.0
                    record.output_data = json.dumps(output, ensure_ascii=False, default=str) if output else None
                    if tokens_used:
                        record.tokens_used = tokens_used
                    if model_name:
                        record.model_name = model_name
                    db.commit()

                    log.info(
                        f"AgentExecutionMonitor | 记录成功 | "
                        f"log_id={log_id} | duration={duration_ms:.0f}ms"
                    )
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | record_success 失败: {e}")

    def record_failure(
        self,
        log_id: str,
        error: str,
        duration_ms: float = 0,
    ) -> None:
        """记录 Agent 执行失败"""
        if not log_id:
            return

        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                record = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.id == int(log_id)
                ).first()
                if record:
                    record.status = "error"
                    record.end_time = datetime.now(timezone.utc)
                    record.duration = duration_ms / 1000.0
                    record.error = error
                    db.commit()

                    log.warning(
                        f"AgentExecutionMonitor | 记录失败 | "
                        f"log_id={log_id} | error={error[:100]}"
                    )
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | record_failure 失败: {e}")

    def record_skipped(
        self,
        log_id: str,
        reason: str = "",
    ) -> None:
        """记录 Agent 跳过"""
        if not log_id:
            return

        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                record = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.id == int(log_id)
                ).first()
                if record:
                    record.status = "skipped"
                    record.end_time = datetime.now(timezone.utc)
                    record.error = reason
                    db.commit()

                    log.info(
                        f"AgentExecutionMonitor | 记录跳过 | "
                        f"log_id={log_id} | reason={reason[:100]}"
                    )
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | record_skipped 失败: {e}")

    # ------------------------------------------------------------------
    # 时间线查询（Dify 风格）
    # ------------------------------------------------------------------

    def get_timeline(
        self,
        task_id: str,
    ) -> Dict[str, Any]:
        """获取执行时间线（Dify 风格）

        返回结构：
        {
            "task_id": "...",
            "total_steps": N,
            "success_count": N,
            "failed_count": N,
            "running_count": N,
            "skipped_count": N,
            "total_duration_ms": 12345,
            "timeline": [
                {
                    "step_index": 0,
                    "step_name": "analyze_image",
                    "agent_name": "element_agent",
                    "status": "success",
                    "start_time": "2026-07-13T...",
                    "end_time": "2026-07-13T...",
                    "duration_ms": 1500,
                    "input": {...},
                    "output": {...},
                    "error": null,
                    "tokens_used": 0,
                    "model_name": "qwen-vl-plus",
                },
                ...
            ]
        }
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                records = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.task_id == str(task_id)
                ).order_by(AgentExecutionLog.id.asc()).all()

                timeline = []
                for i, r in enumerate(records):
                    timeline.append({
                        "step_index": i,
                        "log_id": r.id,
                        "step_name": r.step or "",
                        "agent_name": r.agent_name or "",
                        "status": r.status or "unknown",
                        "start_time": r.start_time.isoformat() if r.start_time else None,
                        "end_time": r.end_time.isoformat() if r.end_time else None,
                        "duration_ms": int((r.duration or 0) * 1000),
                        "input": r.get_input() if hasattr(r, "get_input") else None,
                        "output": r.get_output() if hasattr(r, "get_output") else None,
                        "error": r.error or None,
                        "tokens_used": r.tokens_used or 0,
                        "model_name": r.model_name or "",
                    })

                # 统计
                success_count = sum(1 for t in timeline if t["status"] == "success")
                failed_count = sum(1 for t in timeline if t["status"] == "error")
                running_count = sum(1 for t in timeline if t["status"] == "running")
                skipped_count = sum(1 for t in timeline if t["status"] == "skipped")
                total_duration_ms = sum(t["duration_ms"] for t in timeline)

                return {
                    "task_id": str(task_id),
                    "total_steps": len(timeline),
                    "success_count": success_count,
                    "failed_count": failed_count,
                    "running_count": running_count,
                    "skipped_count": skipped_count,
                    "total_duration_ms": total_duration_ms,
                    "timeline": timeline,
                }
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | get_timeline 失败: {e}")
            return {
                "task_id": str(task_id),
                "total_steps": 0,
                "timeline": [],
                "error": str(e),
            }

    # ------------------------------------------------------------------
    # 失败节点查询
    # ------------------------------------------------------------------

    def get_failed_nodes(
        self,
        task_id: str,
    ) -> List[Dict[str, Any]]:
        """获取所有失败节点

        Returns:
            失败节点列表，包含错误详情
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                records = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.task_id == str(task_id),
                    AgentExecutionLog.status == "error",
                ).order_by(AgentExecutionLog.id.asc()).all()

                return [
                    {
                        "log_id": r.id,
                        "step_name": r.step or "",
                        "agent_name": r.agent_name or "",
                        "status": "error",
                        "start_time": r.start_time.isoformat() if r.start_time else None,
                        "end_time": r.end_time.isoformat() if r.end_time else None,
                        "duration_ms": int((r.duration or 0) * 1000),
                        "input": r.get_input() if hasattr(r, "get_input") else None,
                        "output": r.get_output() if hasattr(r, "get_output") else None,
                        "error": r.error or "",
                    }
                    for r in records
                ]
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | get_failed_nodes 失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 单节点详情
    # ------------------------------------------------------------------

    def get_node_detail(
        self,
        log_id: int,
    ) -> Optional[Dict[str, Any]]:
        """获取单个执行节点的详细信息

        用于前端点击时间线节点时展示详情。
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog

            db = SessionLocal()
            try:
                record = db.query(AgentExecutionLog).filter(
                    AgentExecutionLog.id == log_id
                ).first()
                if record is None:
                    return None

                return {
                    "log_id": record.id,
                    "session_id": record.session_id,
                    "task_id": record.task_id,
                    "agent_name": record.agent_name,
                    "step": record.step,
                    "status": record.status,
                    "start_time": record.start_time.isoformat() if record.start_time else None,
                    "end_time": record.end_time.isoformat() if record.end_time else None,
                    "duration_ms": int((record.duration or 0) * 1000),
                    "input": record.get_input() if hasattr(record, "get_input") else None,
                    "output": record.get_output() if hasattr(record, "get_output") else None,
                    "error": record.error,
                    "model_name": record.model_name,
                    "tokens_used": record.tokens_used,
                    "extra": json.loads(record.extra_json) if record.extra_json else {},
                }
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | get_node_detail 失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 执行统计
    # ------------------------------------------------------------------

    def get_stats(
        self,
        task_id: str = "",
        session_id: str = "",
    ) -> Dict[str, Any]:
        """获取执行统计

        Args:
            task_id: 按任务过滤
            session_id: 按会话过滤

        Returns:
            统计信息
        """
        try:
            from app.db.database import SessionLocal
            from app.models.agent_execution_log import AgentExecutionLog
            from sqlalchemy import func

            db = SessionLocal()
            try:
                q = db.query(AgentExecutionLog)
                if task_id:
                    q = q.filter(AgentExecutionLog.task_id == str(task_id))
                if session_id:
                    q = q.filter(AgentExecutionLog.session_id == session_id)

                total = q.count()
                success = q.filter(AgentExecutionLog.status == "success").count()
                failed = q.filter(AgentExecutionLog.status == "error").count()
                running = q.filter(AgentExecutionLog.status == "running").count()
                skipped = q.filter(AgentExecutionLog.status == "skipped").count()

                # 按 Agent 分组统计
                agent_stats = db.query(
                    AgentExecutionLog.agent_name,
                    func.count(AgentExecutionLog.id).label("count"),
                    func.avg(AgentExecutionLog.duration).label("avg_duration"),
                )
                if task_id:
                    agent_stats = agent_stats.filter(AgentExecutionLog.task_id == str(task_id))
                agent_stats = agent_stats.group_by(AgentExecutionLog.agent_name).all()

                # 总耗时
                total_duration = db.query(
                    func.sum(AgentExecutionLog.duration)
                )
                if task_id:
                    total_duration = total_duration.filter(AgentExecutionLog.task_id == str(task_id))
                total_duration = total_duration.scalar() or 0

                # 总 token
                total_tokens = db.query(
                    func.sum(AgentExecutionLog.tokens_used)
                )
                if task_id:
                    total_tokens = total_tokens.filter(AgentExecutionLog.task_id == str(task_id))
                total_tokens = total_tokens.scalar() or 0

                return {
                    "total": total,
                    "success": success,
                    "failed": failed,
                    "running": running,
                    "skipped": skipped,
                    "success_rate": round(success / total * 100, 1) if total > 0 else 0,
                    "total_duration_s": round(total_duration or 0, 2),
                    "total_tokens": total_tokens,
                    "by_agent": [
                        {
                            "agent_name": a.agent_name,
                            "count": a.count,
                            "avg_duration_ms": int((a.avg_duration or 0) * 1000),
                        }
                        for a in agent_stats
                    ],
                }
            finally:
                db.close()
        except Exception as e:
            log.warning(f"AgentExecutionMonitor | get_stats 失败: {e}")
            return {"error": str(e)}


# ------------------------------------------------------------------
# 单例
# ------------------------------------------------------------------

_monitor: Optional[AgentExecutionMonitor] = None


def get_execution_monitor() -> AgentExecutionMonitor:
    """获取 AgentExecutionMonitor 单例"""
    global _monitor
    if _monitor is None:
        _monitor = AgentExecutionMonitor()
    return _monitor
