"""
任务队列 + Worker Pool

异步执行架构核心：
- 前端/定时任务提交执行请求到队列
- Worker Pool 从队列取出任务异步执行
- SSE 订阅机制推送执行进度
- 支持取消执行

设计原则：
- 提交即返回 execution_id，不阻塞调用方
- Worker 使用 asyncio.to_thread 执行同步 subprocess
- 定时任务执行不影响 API 响应速度
"""
import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from app.core.logger import log
from app.models.execution_record import ExecutionStatus
from app.agents.factory import AgentRegistry


@dataclass
class ExecutionJob:
    """执行任务"""
    execution_id: int
    task_id: int
    script_content: str = ""
    trigger_source: str = "manual"  # manual/schedule/script_upload/retry
    cancelled: bool = False
    process: Optional[asyncio.subprocess.Process] = None
    subscribers: List[asyncio.Queue] = field(default_factory=list)


class TaskQueue:
    """
    全局任务队列（单例）

    使用方式：
        queue = TaskQueue()
        await queue.start(worker_count=3)
        await queue.submit(execution_id=1, task_id=1, script_content="...")
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._queue = asyncio.Queue()
            cls._instance._workers: List[asyncio.Task] = []
            cls._instance._jobs: Dict[int, ExecutionJob] = {}
            cls._instance._subscribers: Dict[int, List[asyncio.Queue]] = {}
            cls._instance._started = False
        return cls._instance

    @property
    def started(self) -> bool:
        return self._started

    async def start(self, worker_count: int = 3):
        """启动 Worker 池 + 恢复未完成任务"""
        if self._started:
            return
        for i in range(worker_count):
            w = asyncio.create_task(self._worker_loop(f"worker-{i}"))
            self._workers.append(w)
        self._started = True
        log.info(f"TaskQueue 启动 | workers={worker_count}")

        # 恢复 WAITING/PENDING 状态的任务（进程重启后内存队列丢失）
        await self._recover_pending_jobs()

    async def stop(self):
        """停止所有 Worker"""
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        self._started = False
        log.info("TaskQueue 已停止")

    async def submit(self, execution_id: int, task_id: int,
                     script_content: str = "",
                     trigger_source: str = "manual") -> None:
        """提交执行任务到队列"""
        job = ExecutionJob(
            execution_id=execution_id,
            task_id=task_id,
            script_content=script_content,
            trigger_source=trigger_source,
        )
        self._jobs[execution_id] = job
        await self._queue.put(job)
        log.info(f"任务已入队 | execution_id={execution_id}, task_id={task_id}, source={trigger_source}")

    async def cancel(self, execution_id: int) -> bool:
        """取消执行"""
        job = self._jobs.get(execution_id)
        if not job:
            return False
        if job.cancelled:
            return True

        job.cancelled = True

        # 终止子进程
        if job.process:
            try:
                job.process.terminate()
            except Exception:
                pass

        # 更新数据库状态
        from app.db.database import SessionLocal
        from app.models.execution_record import ExecutionRecord
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(
                ExecutionRecord.id == execution_id
            ).first()
            if record and record.status in (ExecutionStatus.PENDING, ExecutionStatus.WAITING, ExecutionStatus.RUNNING):
                record.status = ExecutionStatus.CANCELLED
                db.commit()
        finally:
            db.close()

        # 通知订阅者
        await self._notify(execution_id, {
            "step": "执行取消",
            "status": "cancelled",
            "progress": 0,
            "message": "执行已被取消",
        })
        return True

    async def subscribe(self, execution_id: int) -> asyncio.Queue:
        """订阅执行进度（用于 SSE）"""
        q = asyncio.Queue()
        self._subscribers.setdefault(execution_id, []).append(q)
        return q

    async def unsubscribe(self, execution_id: int, q: asyncio.Queue):
        """取消订阅"""
        if execution_id in self._subscribers:
            self._subscribers[execution_id] = [
                x for x in self._subscribers[execution_id] if x is not q
            ]

    def get_job(self, execution_id: int) -> Optional[ExecutionJob]:
        """获取任务信息"""
        return self._jobs.get(execution_id)

    async def _recover_pending_jobs(self):
        """恢复 WAITING/PENDING 状态的任务（进程重启后内存队列丢失）"""
        from app.db.database import SessionLocal
        from app.models.execution_record import ExecutionRecord
        from app.models.script import Script

        db = SessionLocal()
        try:
            # 查找所有 WAITING/PENDING 状态的执行记录
            pending_records = db.query(ExecutionRecord).filter(
                ExecutionRecord.status.in_([
                    ExecutionStatus.WAITING,
                    ExecutionStatus.PENDING,
                ])
            ).all()

            if not pending_records:
                log.info("无需恢复的任务")
                return

            recovered = 0
            for record in pending_records:
                # 读取关联的脚本
                script = db.query(Script).filter(
                    Script.task_id == record.task_id
                ).first()
                script_content = script.script_content if script else ""

                # 重新提交到队列
                job = ExecutionJob(
                    execution_id=record.id,
                    task_id=record.task_id,
                    script_content=script_content,
                    trigger_source=record.trigger_source or "recovery",
                )
                self._jobs[record.id] = job
                await self._queue.put(job)
                recovered += 1
                log.info(f"恢复任务 | execution_id={record.id}, task_id={record.task_id}")

            log.info(f"任务恢复完成 | 恢复数量={recovered}")
        except Exception as e:
            log.error(f"恢复任务异常: {e}", exc_info=True)
        finally:
            db.close()

    async def _notify(self, execution_id: int, data: dict):
        """通知所有订阅者"""
        for q in self._subscribers.get(execution_id, []):
            try:
                await q.put(data)
            except Exception:
                pass

    async def _worker_loop(self, name: str):
        """Worker 主循环"""
        while True:
            try:
                job = await self._queue.get()
                if job.cancelled:
                    log.info(f"{name}: 任务已取消 | execution_id={job.execution_id}")
                    continue
                await self._execute_job(job)
            except asyncio.CancelledError:
                break
            except Exception as e:
                log.error(f"{name} 异常: {e}", exc_info=True)

    async def _execute_job(self, job: ExecutionJob):
        """执行单个任务"""
        from app.db.database import SessionLocal
        from app.models.execution_record import ExecutionRecord

        execution_id = job.execution_id

        # 更新状态为 RUNNING
        db = SessionLocal()
        try:
            record = db.query(ExecutionRecord).filter(
                ExecutionRecord.id == execution_id
            ).first()
            if record:
                record.status = ExecutionStatus.RUNNING
                record.start_time = datetime.now().isoformat()
                db.commit()
        finally:
            db.close()

        await self._notify(execution_id, {
            "step": "执行开始",
            "status": "running",
            "progress": 10,
            "message": f"开始执行任务 {job.task_id}",
        })

        try:
            # 使用 asyncio.wait_for 添加超时控制（默认300秒=5分钟）
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._run_script_sync,
                    execution_id,
                    job.task_id,
                    job.script_content,
                ),
                timeout=300,
            )

            if job.cancelled:
                return

            # 更新执行结果
            db = SessionLocal()
            try:
                record = db.query(ExecutionRecord).filter(
                    ExecutionRecord.id == execution_id
                ).first()
                if record:
                    is_success = result.get("success", False)
                    record.status = ExecutionStatus.SUCCESS if is_success else ExecutionStatus.FAILED
                    record.end_time = datetime.now().isoformat()
                    record.duration = result.get("duration", 0)
                    record.success_count = 1 if is_success else 0
                    record.failed_count = 0 if is_success else 1
                    record.error_message = result.get("error", "")
                    record.log_content = result.get("output", "")
                    record.report_path = result.get("report_path")
                    record.screenshot_path = result.get("screenshot_path")
                    db.commit()

                    # 更新关联的 Task 状态
                    from app.models.task import Task, TaskStatus
                    task = db.query(Task).filter(Task.id == job.task_id).first()
                    if task:
                        task.status = TaskStatus.SUCCESS if is_success else TaskStatus.FAILED
                        db.commit()
            finally:
                db.close()

            # 执行失败时自动触发缺陷分析
            if not result.get("success") and not job.cancelled:
                try:
                    agent = AgentRegistry.create("execution_agent")
                    analysis = agent.analyze_failure(
                        log_content=result.get("output", ""),
                        error_message=result.get("error", ""),
                        script_content=job.script_content,
                        screenshot_path=result.get("screenshot_path", ""),
                    )
                    db = SessionLocal()
                    try:
                        record = db.query(ExecutionRecord).filter(
                            ExecutionRecord.id == execution_id
                        ).first()
                        if record:
                            record.analysis_result = json.dumps(analysis, ensure_ascii=False)
                            db.commit()
                    finally:
                        db.close()
                except Exception as e:
                    log.warning(f"自动缺陷分析失败 | execution_id={execution_id}: {e}")

            final_step = "执行完成" if result.get("success") else "执行异常"
            await self._notify(execution_id, {
                "step": final_step,
                "status": "success" if result.get("success") else "failed",
                "progress": 100,
                "message": f"{final_step} | 耗时: {result.get('duration', 0):.1f}s",
                "data": {
                    "execution_id": execution_id,
                    "status": "success" if result.get("success") else "failed",
                    "duration": result.get("duration", 0),
                },
            })

        except asyncio.TimeoutError:
            log.error(f"执行超时 | execution_id={execution_id}, 超时时间=300s")
            db = SessionLocal()
            try:
                record = db.query(ExecutionRecord).filter(
                    ExecutionRecord.id == execution_id
                ).first()
                if record:
                    record.status = ExecutionStatus.FAILED
                    record.error_message = "执行超时（300秒）"
                    record.end_time = datetime.now().isoformat()
                    db.commit()
            finally:
                db.close()

            await self._notify(execution_id, {
                "step": "执行超时",
                "status": "failed",
                "progress": 100,
                "message": "执行超时（300秒），已自动终止",
            })

        except Exception as e:
            log.error(f"执行异常 | execution_id={execution_id}: {e}", exc_info=True)
            db = SessionLocal()
            try:
                record = db.query(ExecutionRecord).filter(
                    ExecutionRecord.id == execution_id
                ).first()
                if record:
                    record.status = ExecutionStatus.FAILED
                    record.error_message = str(e)
                    record.end_time = datetime.now().isoformat()
                    db.commit()
            finally:
                db.close()

            await self._notify(execution_id, {
                "step": "执行异常",
                "status": "failed",
                "progress": 100,
                "message": f"执行异常: {e}",
            })

    @staticmethod
    def _run_script_sync(execution_id: int, task_id: int, script_content: str) -> dict:
        """
        同步执行脚本（在 asyncio.to_thread 中运行）

        复用 ExecutionAgent 的执行逻辑
        """
        agent = AgentRegistry.create("execution_agent")
        result = agent.execute_script(
            script_content=script_content,
            task_id=task_id,
            execution_id=execution_id,
        )

        return {
            "success": result.get("status") == "success",
            "duration": result.get("duration", 0),
            "error": result.get("error_message", ""),
            "output": result.get("log_content", ""),
            "report_path": result.get("report_path"),
            "screenshot_path": result.get("screenshot_path"),
        }
