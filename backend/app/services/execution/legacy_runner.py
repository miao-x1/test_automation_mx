"""
执行服务 - Playwright 脚本执行器（旧版）

管理 Playwright 脚本的执行流程：
1. 创建执行记录
2. 调用 ExecutionAgent 执行脚本
3. SSE 实时推送执行进度
4. 保存执行结果
"""
import asyncio
import json
import queue
import threading
from typing import Any, AsyncGenerator
from sqlalchemy.orm import Session
from app.db.database import SessionLocal
from app.models.script import Script
from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.core.logger import log
from app.agents.factory import AgentRegistry

_LOG_CONTENT_LIMIT = 60000


def _clip_db_text(value: Any, limit: int = _LOG_CONTENT_LIMIT) -> Any:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n...[truncated]"


class LegacyExecutionRunner:
    """Playwright 脚本执行器（旧版线程+队列模式）"""

    @staticmethod
    def create_execution(db: Session, task_id: int) -> ExecutionRecord:
        """创建执行记录"""
        script = db.query(Script).filter(Script.task_id == task_id).first()
        if not script:
            raise ValueError("该任务没有可执行的脚本")

        record = ExecutionRecord(
            task_id=task_id,
            status=ExecutionStatus.PENDING,
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        log.info(f"执行记录已创建 | ID: {record.id}, Task: {task_id}")
        return record

    @staticmethod
    async def run_execution(execution_id: int) -> AsyncGenerator[str, None]:
        """
        执行脚本，SSE实时推送进度

        使用独立的数据库session，避免SSE长连接中session被关闭的问题。
        使用队列实现Agent → SSE的实时通信：
        1. Agent在子线程中执行，通过on_log回调将日志放入队列
        2. 主协程从队列中读取日志，通过SSE推送给前端
        """
        # 使用独立的数据库session
        db = SessionLocal()

        try:
            # 读取执行记录
            record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
            if not record:
                yield json.dumps({"step": "执行异常", "event": "done", "progress": 0, "message": "执行记录不存在"}, ensure_ascii=False)
                db.close()
                return

            # 读取脚本
            script = db.query(Script).filter(Script.task_id == record.task_id).first()
            if not script:
                record.status = ExecutionStatus.FAILED
                record.error_message = "脚本不存在"
                db.commit()
                yield json.dumps({"step": "执行异常", "event": "done", "progress": 0, "message": "脚本不存在"}, ensure_ascii=False)
                db.close()
                return

            # 更新状态为执行中
            record.status = ExecutionStatus.RUNNING
            db.commit()

            script_content = script.script_content
            task_id = record.task_id

        except Exception as e:
            try:
                record = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
                if record and record.status in (ExecutionStatus.WAITING, ExecutionStatus.PENDING, ExecutionStatus.RUNNING):
                    record.status = ExecutionStatus.FAILED
                    record.error_message = f"读取数据失败: {e}"
                    db.commit()
            except Exception:
                pass
            yield json.dumps({"step": "执行异常", "event": "done", "progress": 0, "message": f"读取数据失败: {e}"}, ensure_ascii=False)
            db.close()
            return

        persisted_terminal = False
        try:
            yield json.dumps({"step": "开始执行", "progress": 5, "message": f"准备执行任务 {task_id} 的脚本"}, ensure_ascii=False)

            log_queue = queue.Queue()
            exec_result = {"result": None}

            def on_log(log_data: dict):
                log_queue.put(log_data)

            def run_agent():
                try:
                    agent = AgentRegistry.create("execution_agent")
                    result = agent.execute_script(
                        script_content=script_content,
                        task_id=task_id,
                        execution_id=execution_id,
                        on_log=on_log,
                    )
                    exec_result["result"] = result
                except Exception as e:
                    err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                    exec_result["result"] = {
                        "status": "failed",
                        "error_message": err_msg,
                        "success_count": 0,
                        "failed_count": 0,
                        "duration": 0,
                        "log_content": err_msg,
                    }
                finally:
                    log_queue.put({"__done__": True})

            agent_thread = threading.Thread(target=run_agent, daemon=True)
            agent_thread.start()

            # 实时从队列读取日志并推送SSE（不阻塞事件循环，避免同进程 page.goto 死锁）
            while True:
                try:
                    log_data = log_queue.get_nowait()
                except queue.Empty:
                    if not agent_thread.is_alive():
                        break
                    await asyncio.sleep(0.2)
                    continue

                if log_data.get("__done__"):
                    break

                yield json.dumps({
                    "step": log_data.get("step", "执行日志"),
                    "progress": log_data.get("progress", 0),
                    "message": log_data.get("message", ""),
                }, ensure_ascii=False)

            agent_thread.join(timeout=5)

            try:
                result = exec_result["result"]
                if result:
                    db.refresh(record)
                    record.status = ExecutionStatus.SUCCESS if result["status"] == "success" else ExecutionStatus.FAILED
                    record.start_time = result.get("start_time")
                    record.end_time = result.get("end_time")
                    record.duration = result.get("duration")
                    record.success_count = result.get("success_count", 0)
                    record.failed_count = result.get("failed_count", 0)
                    record.error_message = _clip_db_text(result.get("error_message"), 2000)
                    record.log_content = _clip_db_text(result.get("log_content"))
                    record.report_path = result.get("report_path")
                    record.screenshot_path = result.get("screenshot_path")
                    db.commit()
                    persisted_terminal = True
                    yield json.dumps({
                        "step": "执行完成",
                        "event": "done",
                        "progress": 100,
                        "message": f"执行{'成功' if result['status'] == 'success' else '失败'} | 通过: {result.get('success_count', 0)}, 失败: {result.get('failed_count', 0)}",
                        "data": {
                            "execution_id": execution_id,
                            "status": result["status"],
                            "success_count": result.get("success_count", 0),
                            "failed_count": result.get("failed_count", 0),
                            "duration": result.get("duration", 0),
                        }
                    }, ensure_ascii=False)
                else:
                    db.refresh(record)
                    record.status = ExecutionStatus.FAILED
                    record.error_message = "执行结果为空"
                    db.commit()
                    persisted_terminal = True
                    yield json.dumps({"step": "执行异常", "event": "done", "progress": 100, "message": "执行结果为空"}, ensure_ascii=False)
            except Exception as e:
                err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
                log.error(f"更新执行记录失败 | exec={execution_id}: {err_msg}")
                try:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    fresh = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
                    if fresh:
                        fresh.status = ExecutionStatus.FAILED
                        fresh.error_message = _clip_db_text(err_msg, 2000)
                        fresh.log_content = None
                        db.commit()
                        persisted_terminal = True
                except Exception:
                    pass
                yield json.dumps({"step": "执行异常", "event": "done", "progress": 100, "message": f"更新执行记录失败: {_clip_db_text(err_msg, 200)}"}, ensure_ascii=False)
        finally:
            if not persisted_terminal:
                try:
                    try:
                        db.rollback()
                    except Exception:
                        pass
                    fresh = db.query(ExecutionRecord).filter(ExecutionRecord.id == execution_id).first()
                    if fresh and fresh.status in (
                        ExecutionStatus.WAITING,
                        ExecutionStatus.PENDING,
                        ExecutionStatus.RUNNING,
                    ):
                        fresh.status = ExecutionStatus.FAILED
                        fresh.error_message = fresh.error_message or "执行未完成或连接中断"
                        db.commit()
                except Exception:
                    pass
            db.close()
