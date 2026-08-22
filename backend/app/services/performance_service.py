"""
性能测试 Service 层

编排流程:
  1. PerformancePlanAgent   → 生成测试方案 (并发/持续时间/TPS)
  2. PerformanceScriptAgent → 生成 Locust / JMeter 脚本
  3. PerformanceExecutor    → 执行测试, 实时采集指标
  4. PerformanceAnalysisAgent → 分析 TPS/RT/CPU/Memory/日志

设计约束:
  - 不使用 RAG 分析实时性能数据
  - 使用实时指标 + LLM 分析
"""
import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.models.performance import (
    PerformanceTask,
    PerformanceResult,
    PerformanceMetric,
    TaskStatus,
    ResultStatus,
)
from app.domains.performance.executor import get_performance_executor

logger = logging.getLogger(__name__)


class PerformanceService:
    """性能测试服务"""

    def __init__(self) -> None:
        from app.agents.factory.factory import AgentFactory
        self._factory = AgentFactory()

    # ----------------------------------------------------------------
    # 任务 CRUD
    # ----------------------------------------------------------------

    def create_task(
        self,
        name: str,
        target_url: str,
        method: str = "GET",
        test_type: str = "api",
        headers: Optional[Dict] = None,
        body: Optional[Dict] = None,
        business_volume: int = 10000,
        user_id: Optional[int] = None,
        created_by: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建性能测试任务"""
        db = SessionLocal()
        try:
            task = PerformanceTask(
                name=name,
                test_type=test_type,
                target_url=target_url,
                method=method,
                headers_json=json.dumps(headers, ensure_ascii=False) if headers else None,
                body_json=json.dumps(body, ensure_ascii=False) if body else None,
                business_volume=business_volume,
                concurrency=10,  # 默认值, 后续由 PlanAgent 更新
                duration_seconds=60,
                ramp_up=10,
                status=TaskStatus.PENDING.value,
                user_id=user_id,
                created_by=created_by,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            return self._task_to_dict(task)
        finally:
            db.close()

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        """获取任务详情"""
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
                PerformanceTask.is_deleted == False,
            ).first()
            if not task:
                return None
            return self._task_to_dict(task)
        finally:
            db.close()

    def list_tasks(
        self,
        page: int = 1,
        page_size: int = 20,
        test_type: Optional[str] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """分页查询任务列表"""
        db = SessionLocal()
        try:
            q = db.query(PerformanceTask).filter(PerformanceTask.is_deleted == False)
            if test_type:
                q = q.filter(PerformanceTask.test_type == test_type)
            if status:
                q = q.filter(PerformanceTask.status == status)
            if user_id:
                q = q.filter(PerformanceTask.user_id == user_id)
            total = q.count()
            tasks = q.order_by(PerformanceTask.created_at.desc()) \
                .offset((page - 1) * page_size).limit(page_size).all()
            return {
                "items": [self._task_to_dict(t) for t in tasks],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def delete_task(self, task_id: int) -> bool:
        """软删除任务"""
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(PerformanceTask.id == task_id).first()
            if not task:
                return False
            task.is_deleted = True
            db.commit()
            return True
        finally:
            db.close()

    # ----------------------------------------------------------------
    # Agent 编排
    # ----------------------------------------------------------------

    async def run_plan(self, task_id: int) -> Dict[str, Any]:
        """执行性能测试方案生成 (PerformancePlanAgent)"""
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(PerformanceTask.id == task_id).first()
            if not task:
                return {"status": "error", "error": "任务不存在"}

            task.status = TaskStatus.PLANNING.value
            db.commit()

            # 创建 PlanAgent 并执行
            agent = await self._factory.create("performance_plan_agent")
            result = await agent.execute({
                "target_url": task.target_url,
                "method": task.method,
                "business_volume": task.business_volume or 10000,
                "headers": json.loads(task.headers_json) if task.headers_json else {},
                "body": json.loads(task.body_json) if task.body_json else {},
                "test_type": task.test_type,
            }, ctx=None)

            if result.get("status") == "success":
                plan = result["plan"]
                # 更新任务配置
                task.concurrency = plan.get("concurrency", task.concurrency)
                task.duration_seconds = plan.get("duration_seconds", task.duration_seconds)
                task.tps_target = plan.get("tps_target")
                task.ramp_up = plan.get("ramp_up", task.ramp_up)
                task.plan_json = json.dumps(plan, ensure_ascii=False)
                db.commit()
                return {"status": "success", "plan": plan}
            else:
                task.status = TaskStatus.FAILED.value
                task.error_message = result.get("error", "PlanAgent 执行失败")
                db.commit()
                return result
        finally:
            db.close()

    async def run_script(self, task_id: int, script_type: str = "locust") -> Dict[str, Any]:
        """执行脚本生成 (PerformanceScriptAgent)"""
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(PerformanceTask.id == task_id).first()
            if not task:
                return {"status": "error", "error": "任务不存在"}

            task.status = TaskStatus.SCRIPTING.value
            task.script_type = script_type
            db.commit()

            plan = json.loads(task.plan_json) if task.plan_json else {}
            agent = await self._factory.create("performance_script_agent")
            result = await agent.execute({
                "plan": plan,
                "target_url": task.target_url,
                "method": task.method,
                "headers": json.loads(task.headers_json) if task.headers_json else {},
                "body": json.loads(task.body_json) if task.body_json else {},
                "script_type": script_type,
                "test_type": task.test_type,
            }, ctx=None)

            if result.get("status") == "success":
                task.script_content = result.get("script_content", "")
                if result.get("jmeter_config"):
                    task.jmeter_config = result["jmeter_config"]
                db.commit()
                return result
            else:
                task.status = TaskStatus.FAILED.value
                task.error_message = result.get("error", "ScriptAgent 执行失败")
                db.commit()
                return result
        finally:
            db.close()

    async def run_analysis(self, task_id: int, logs: List[Dict[str, Any]] = None) -> Dict[str, Any]:
        """执行性能分析 (PerformanceAnalysisAgent)

        使用实时指标 + 日志 + LLM 分析, 不使用 RAG。

        Args:
            task_id: 任务 ID
            logs: 应用日志列表 (可选), 每条日志为 dict 或 str
        """
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(PerformanceTask.id == task_id).first()
            if not task:
                return {"status": "error", "error": "任务不存在"}

            # 获取最新结果
            result = db.query(PerformanceResult).filter(
                PerformanceResult.task_id == task_id,
            ).order_by(PerformanceResult.created_at.desc()).first()
            if not result:
                return {"status": "error", "error": "无执行结果可分析"}

            # 获取实时指标
            metrics = db.query(PerformanceMetric).filter(
                PerformanceMetric.result_id == result.id,
            ).order_by(PerformanceMetric.elapsed).all()

            plan = json.loads(task.plan_json) if task.plan_json else {}

            # 创建 AnalysisAgent 并执行 (实时指标 + 日志直接传入, 不走 RAG)
            agent = await self._factory.create("performance_analysis_agent")
            analysis_result = await agent.execute({
                "result_summary": {
                    "avg_tps": result.avg_tps,
                    "peak_tps": result.peak_tps,
                    "avg_rt": result.avg_rt,
                    "p95_rt": result.p95_rt,
                    "p99_rt": result.p99_rt,
                    "error_rate": result.error_rate,
                    "total_requests": result.total_requests,
                    "total_errors": result.total_errors,
                    "concurrency": result.concurrency,
                    "duration_seconds": result.duration_seconds,
                },
                "metrics": [self._metric_to_dict(m) for m in metrics],
                "target_plan": plan,
                "logs": logs or [],
            }, ctx=None)

            if analysis_result.get("status") == "success":
                result.analysis_json = json.dumps(
                    analysis_result.get("analysis", {}), ensure_ascii=False
                )
                db.commit()
                return analysis_result
            return analysis_result
        finally:
            db.close()

    async def run_diagnostic(
        self,
        task_id: int,
        jstack_dump: str = "",
        logs: List[Any] = None,
    ) -> Dict[str, Any]:
        """执行性能诊断 (PerformanceDiagnosticAgent)

        编排诊断 Agent, 输入 jstack + 日志 + 监控数据, 输出问题定位。

        Args:
            task_id: 关联任务 ID
            jstack_dump: jstack 命令输出文本
            logs: 应用日志列表

        Returns:
            诊断报告 (problems + correlations + llm_analysis)
        """
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
                PerformanceTask.is_deleted == False,
            ).first()
            if not task:
                return {"status": "error", "error": "任务不存在"}

            # 收集监控数据 (从最近一次执行结果获取)
            monitoring_data: Dict[str, Any] = {}
            result = db.query(PerformanceResult).filter(
                PerformanceResult.task_id == task_id,
            ).order_by(PerformanceResult.id.desc()).first()

            if result:
                monitoring_data = {
                    "avg_tps": result.avg_tps or 0,
                    "peak_tps": result.peak_tps or 0,
                    "avg_rt": result.avg_rt or 0,
                    "p95_rt": result.p95_rt or 0,
                    "p99_rt": result.p99_rt or 0,
                    "error_rate": result.error_rate or 0,
                    "total_requests": result.total_requests or 0,
                    "total_errors": result.total_errors or 0,
                    "concurrency": result.concurrency or 0,
                    "duration_seconds": result.duration_seconds or 0,
                }

                # 获取指标列表
                metrics = db.query(PerformanceMetric).filter(
                    PerformanceMetric.result_id == result.id,
                ).order_by(PerformanceMetric.elapsed).all()
                monitoring_data["metrics"] = [self._metric_to_dict(m) for m in metrics]

                # 从指标中提取 CPU/内存峰值
                cpu_values = [m.cpu_percent for m in metrics if m.cpu_percent is not None]
                mem_values = [m.memory_mb for m in metrics if m.memory_mb is not None]
                if cpu_values:
                    monitoring_data["cpu_peak_pct"] = max(cpu_values)
                if mem_values:
                    monitoring_data["mem_peak_mb"] = max(mem_values)

            # 创建诊断 Agent 并执行
            agent = await self._factory.create("performance_diagnostic_agent")
            diag_result = await agent.execute({
                "jstack_dump": jstack_dump,
                "logs": logs or [],
                "monitoring_data": monitoring_data,
                "task_id": task_id,
            }, ctx=None)

            # 将诊断结果保存到最近一次执行结果的 analysis_json
            if result and diag_result.get("status") == "success":
                existing_analysis = {}
                if result.analysis_json:
                    try:
                        existing_analysis = json.loads(result.analysis_json)
                    except (json.JSONDecodeError, TypeError):
                        existing_analysis = {}
                existing_analysis["diagnosis"] = diag_result
                result.analysis_json = json.dumps(existing_analysis, ensure_ascii=False, default=str)
                db.commit()

            return diag_result
        finally:
            db.close()

    # ----------------------------------------------------------------
    # 结果和指标查询
    # ----------------------------------------------------------------

    def get_results(self, task_id: int) -> List[Dict[str, Any]]:
        """获取任务的所有执行结果"""
        db = SessionLocal()
        try:
            results = db.query(PerformanceResult).filter(
                PerformanceResult.task_id == task_id,
            ).order_by(PerformanceResult.created_at.desc()).all()
            return [self._result_to_dict(r) for r in results]
        finally:
            db.close()

    def get_metrics(self, result_id: int) -> List[Dict[str, Any]]:
        """获取某次执行的实时指标"""
        db = SessionLocal()
        try:
            metrics = db.query(PerformanceMetric).filter(
                PerformanceMetric.result_id == result_id,
            ).order_by(PerformanceMetric.elapsed).all()
            return [self._metric_to_dict(m) for m in metrics]
        finally:
            db.close()

    def save_result(self, task_id: int, result_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存执行结果"""
        db = SessionLocal()
        try:
            result = PerformanceResult(
                task_id=task_id,
                total_requests=result_data.get("total_requests", 0),
                total_errors=result_data.get("total_errors", 0),
                error_rate=result_data.get("error_rate", 0.0),
                avg_tps=result_data.get("avg_tps", 0.0),
                peak_tps=result_data.get("peak_tps", 0.0),
                avg_rt=result_data.get("avg_rt", 0.0),
                p50_rt=result_data.get("p50_rt"),
                p90_rt=result_data.get("p90_rt"),
                p95_rt=result_data.get("p95_rt"),
                p99_rt=result_data.get("p99_rt"),
                concurrency=result_data.get("concurrency", 0),
                duration_seconds=result_data.get("duration_seconds", 0),
                status=result_data.get("status", ResultStatus.RUNNING.value),
            )
            db.add(result)
            db.commit()
            db.refresh(result)
            return self._result_to_dict(result)
        finally:
            db.close()

    def save_metric(self, result_id: int, metric_data: Dict[str, Any]) -> Dict[str, Any]:
        """保存单条实时指标"""
        db = SessionLocal()
        try:
            metric = PerformanceMetric(
                result_id=result_id,
                timestamp=metric_data.get("timestamp", time.time()),
                elapsed=metric_data.get("elapsed", 0),
                tps=metric_data.get("tps", 0.0),
                avg_rt=metric_data.get("avg_rt", 0.0),
                concurrent_users=metric_data.get("concurrent_users", 0),
                error_count=metric_data.get("error_count", 0),
                cpu_percent=metric_data.get("cpu_percent"),
                memory_mb=metric_data.get("memory_mb"),
            )
            db.add(metric)
            db.commit()
            db.refresh(metric)
            return self._metric_to_dict(metric)
        finally:
            db.close()

    # ----------------------------------------------------------------
    # 测试执行 (PerformanceExecutor)
    # ----------------------------------------------------------------

    async def run_execute(self, task_id: int) -> Dict[str, Any]:
        """启动性能测试执行

        使用 PerformanceExecutor 运行 Locust 脚本, 实时采集指标。
        指标通过 asyncio.Queue 推送, 同时异步写入数据库。
        """
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
                PerformanceTask.is_deleted == False,
            ).first()
            if not task:
                return {"status": "error", "error": "任务不存在"}

            if not task.script_content:
                return {"status": "error", "error": "尚未生成测试脚本, 请先执行方案和脚本生成"}

            # 更新任务状态
            task.status = TaskStatus.RUNNING.value
            db.commit()

            # 创建结果记录
            result = PerformanceResult(
                task_id=task_id,
                concurrency=task.concurrency or 10,
                duration_seconds=task.duration_seconds or 60,
                status=ResultStatus.RUNNING.value,
            )
            db.add(result)
            db.commit()
            db.refresh(result)

            result_id = result.id

            # 启动执行器
            executor = get_performance_executor()
            exec_result = await executor.execute(
                task_id=task_id,
                result_id=result_id,
                script_content=task.script_content,
                concurrency=task.concurrency or 10,
                duration_seconds=task.duration_seconds or 60,
                ramp_up=task.ramp_up or 10,
                host=task.target_url or "",
            )

            # 启动后台任务: 从 executor 队列读取指标并写入数据库
            asyncio.create_task(self._persist_metrics(task_id, result_id))

            return {
                "status": "started",
                "task_id": task_id,
                "result_id": result_id,
            }
        finally:
            db.close()

    async def stop_execute(self, task_id: int) -> Dict[str, Any]:
        """停止正在运行的性能测试"""
        executor = get_performance_executor()
        result = await executor.stop(task_id)

        # 更新任务和结果状态
        db = SessionLocal()
        try:
            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
            ).first()
            if task:
                task.status = TaskStatus.STOPPED.value
                db.commit()

            result = db.query(PerformanceResult).filter(
                PerformanceResult.task_id == task_id,
                PerformanceResult.status == ResultStatus.RUNNING.value,
            ).first()
            if result:
                result.status = ResultStatus.STOPPED.value
                db.commit()
        finally:
            db.close()

        return result

    def get_execution_status(self, task_id: int) -> Dict[str, Any]:
        """获取执行状态"""
        executor = get_performance_executor()
        status = executor.get_status(task_id)

        # 如果执行已完成, 同步最终结果到数据库
        if status.get("status") in ("completed", "failed", "stopped"):
            self._finalize_result(task_id, status)

        return status

    async def stream_metrics(self, task_id: int):
        """异步生成器: 实时推送指标 (供 SSE 端点消费)

        Yields:
            Dict: 指标事件 (type=metric/end/stopped)
        """
        executor = get_performance_executor()
        queue = executor.get_stream_queue(task_id)

        if not queue:
            yield {"type": "error", "message": "任务未在运行或队列不存在"}
            return

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)
                yield event
                if event.get("type") in ("end", "stopped"):
                    break
            except asyncio.TimeoutError:
                # 检查任务是否仍在运行
                status = executor.get_status(task_id)
                if status.get("status") not in ("running",):
                    yield {"type": "end", "status": status.get("status"), "task_id": task_id}
                    break
                # 继续等待
                continue

    async def _persist_metrics(self, task_id: int, result_id: int) -> None:
        """后台任务: 从 executor 队列读取指标并写入数据库"""
        executor = get_performance_executor()
        queue = executor.get_stream_queue(task_id)

        if not queue:
            return

        batch: List[Dict[str, Any]] = []
        flush_interval = 5  # 每 5 条批量写入一次
        last_flush = time.time()

        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=1.0)

                if event.get("type") == "metric":
                    batch.append(event)
                    if len(batch) >= flush_interval or (time.time() - last_flush) > 3:
                        await asyncio.to_thread(self._batch_save_metrics, result_id, batch)
                        batch.clear()
                        last_flush = time.time()

                elif event.get("type") in ("end", "stopped", "final"):
                    # 保存剩余指标
                    if batch:
                        await asyncio.to_thread(self._batch_save_metrics, result_id, batch)
                        batch.clear()

                    # 保存最终结果
                    if event.get("type") == "end" or event.get("final_stats"):
                        final = event.get("final_stats", event.get("data", {}))
                        if final:
                            await asyncio.to_thread(
                                self._save_final_result, task_id, result_id, final,
                                event.get("status", "completed"),
                            )
                    break

            except asyncio.TimeoutError:
                status = executor.get_status(task_id)
                if status.get("status") not in ("running",):
                    if batch:
                        await asyncio.to_thread(self._batch_save_metrics, result_id, batch)
                    break
                continue
            except Exception as e:
                logger.exception(f"[PerformanceService] 指标持久化异常: {e}")
                break

    def _batch_save_metrics(self, result_id: int, metrics: List[Dict[str, Any]]) -> None:
        """批量保存指标到数据库"""
        if not metrics:
            return
        db = SessionLocal()
        try:
            for m in metrics:
                metric = PerformanceMetric(
                    result_id=result_id,
                    timestamp=m.get("timestamp", time.time()),
                    elapsed=m.get("elapsed", 0),
                    tps=m.get("tps", 0.0),
                    avg_rt=m.get("avg_rt", 0.0),
                    concurrent_users=m.get("concurrent_users", 0),
                    error_count=m.get("error_count", 0),
                    cpu_percent=m.get("cpu_percent"),
                    memory_mb=m.get("memory_mb"),
                )
                db.add(metric)
            db.commit()
        except Exception as e:
            logger.error(f"[PerformanceService] 批量保存指标失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _save_final_result(
        self, task_id: int, result_id: int, final: Dict[str, Any], status: str,
    ) -> None:
        """保存最终执行结果到数据库"""
        db = SessionLocal()
        try:
            result = db.query(PerformanceResult).filter(
                PerformanceResult.id == result_id,
            ).first()
            if not result:
                return

            result.total_requests = final.get("requests", 0)
            result.total_errors = final.get("failures", 0)
            result.error_rate = (
                result.total_errors / result.total_requests * 100
                if result.total_requests > 0 else 0
            )
            result.avg_tps = final.get("rps", 0)
            result.peak_tps = final.get("rps", 0)
            result.avg_rt = final.get("avg_rt", 0)
            result.p50_rt = final.get("p50_rt")
            result.p90_rt = final.get("p90_rt")
            result.p95_rt = final.get("p95_rt")
            result.p99_rt = final.get("p99_rt")
            result.duration_seconds = final.get("elapsed", 0)
            result.status = (
                ResultStatus.SUCCESS.value if status == "completed"
                else ResultStatus.STOPPED.value if status == "stopped"
                else ResultStatus.FAILED.value
            )
            db.commit()

            # 更新任务状态
            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
            ).first()
            if task:
                task.status = (
                    TaskStatus.COMPLETED.value if status == "completed"
                    else TaskStatus.STOPPED.value if status == "stopped"
                    else TaskStatus.FAILED.value
                )
                if status == "failed":
                    task.error_message = "执行失败, 请检查脚本和环境"
                db.commit()
        except Exception as e:
            logger.error(f"[PerformanceService] 保存最终结果失败: {e}")
            db.rollback()
        finally:
            db.close()

    def _finalize_result(self, task_id: int, status: Dict[str, Any]) -> None:
        """同步最终结果 (如果后台任务未完成)"""
        executor = get_performance_executor()
        rt = executor._running.get(task_id)
        if not rt or not rt.final_stats:
            return

        db = SessionLocal()
        try:
            result = db.query(PerformanceResult).filter(
                PerformanceResult.id == rt.result_id,
                PerformanceResult.status == ResultStatus.RUNNING.value,
            ).first()
            if result:
                final = rt.final_stats
                result.total_requests = final.get("requests", 0)
                result.total_errors = final.get("failures", 0)
                result.error_rate = (
                    result.total_errors / result.total_requests * 100
                    if result.total_requests > 0 else 0
                )
                result.avg_tps = final.get("rps", 0)
                result.avg_rt = final.get("avg_rt", 0)
                result.p50_rt = final.get("p50_rt")
                result.p90_rt = final.get("p90_rt")
                result.p95_rt = final.get("p95_rt")
                result.p99_rt = final.get("p99_rt")
                result.duration_seconds = final.get("elapsed", 0)
                result.status = (
                    ResultStatus.SUCCESS.value if status.get("status") == "completed"
                    else ResultStatus.STOPPED.value if status.get("status") == "stopped"
                    else ResultStatus.FAILED.value
                )
                db.commit()

            task = db.query(PerformanceTask).filter(
                PerformanceTask.id == task_id,
            ).first()
            if task and task.status == TaskStatus.RUNNING.value:
                task.status = (
                    TaskStatus.COMPLETED.value if status.get("status") == "completed"
                    else TaskStatus.STOPPED.value if status.get("status") == "stopped"
                    else TaskStatus.FAILED.value
                )
                db.commit()
        except Exception as e:
            logger.error(f"[PerformanceService] 同步最终结果失败: {e}")
            db.rollback()
        finally:
            db.close()

    # ----------------------------------------------------------------
    # 转换方法
    # ----------------------------------------------------------------

    @staticmethod
    def _task_to_dict(task: PerformanceTask) -> Dict[str, Any]:
        return {
            "id": task.id,
            "name": task.name,
            "test_type": task.test_type,
            "target_url": task.target_url,
            "method": task.method,
            "headers": json.loads(task.headers_json) if task.headers_json else {},
            "body": json.loads(task.body_json) if task.body_json else {},
            "business_volume": task.business_volume,
            "concurrency": task.concurrency,
            "duration_seconds": task.duration_seconds,
            "tps_target": task.tps_target,
            "ramp_up": task.ramp_up,
            "script_type": task.script_type,
            "script_content": task.script_content,
            "jmeter_config": task.jmeter_config,
            "plan": json.loads(task.plan_json) if task.plan_json else None,
            "status": task.status,
            "error_message": task.error_message,
            "created_at": task.created_at.isoformat() if task.created_at else None,
            "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        }

    @staticmethod
    def _result_to_dict(result: PerformanceResult) -> Dict[str, Any]:
        return {
            "id": result.id,
            "task_id": result.task_id,
            "total_requests": result.total_requests,
            "total_errors": result.total_errors,
            "error_rate": result.error_rate,
            "avg_tps": result.avg_tps,
            "peak_tps": result.peak_tps,
            "avg_rt": result.avg_rt,
            "p50_rt": result.p50_rt,
            "p90_rt": result.p90_rt,
            "p95_rt": result.p95_rt,
            "p99_rt": result.p99_rt,
            "concurrency": result.concurrency,
            "duration_seconds": result.duration_seconds,
            "analysis": json.loads(result.analysis_json) if result.analysis_json else None,
            "status": result.status,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        }

    @staticmethod
    def _metric_to_dict(metric: PerformanceMetric) -> Dict[str, Any]:
        return {
            "id": metric.id,
            "result_id": metric.result_id,
            "timestamp": metric.timestamp,
            "elapsed": metric.elapsed,
            "tps": metric.tps,
            "avg_rt": metric.avg_rt,
            "concurrent_users": metric.concurrent_users,
            "error_count": metric.error_count,
            "cpu_percent": metric.cpu_percent,
            "memory_mb": metric.memory_mb,
        }
