"""
ExecutionQueue - 执行队列

职责：管理测试用例的执行调度

使用 asyncio.Queue 实现异步队列，支持并发执行
"""
import asyncio
import json
import time as _time
from typing import Any, Dict, List, Optional
from app.core.logger import log
from app.services.execution.context import ExecutionContext
from app.services.execution.case_runner import CaseRunner
from app.services.execution.result_writer import ResultWriter
from app.services.execution.report_generator import ReportGenerator


class ExecutionQueue:
    """
    执行队列（单例）

    流程：
    1. submit() 提交执行任务
    2. Worker 从队列取出任务
    3. CaseRunner 执行用例
    4. ResultWriter 写入结果
    5. ReportGenerator 生成报告
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._queue = None
            cls._instance._workers = []
            cls._instance._running = False
        return cls._instance

    async def start(self, worker_count: int = 3) -> None:
        """启动队列和Worker"""
        if self._running:
            return

        self._queue = asyncio.Queue()
        self._running = True

        for i in range(worker_count):
            worker = asyncio.create_task(self._worker_loop(i))
            self._workers.append(worker)

        log.info(f"ExecutionQueue | 启动 | workers={worker_count}")

    async def stop(self) -> None:
        """停止队列"""
        self._running = False
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        log.info("ExecutionQueue | 停止")

    async def submit(
        self,
        execution_id: int,
        cases: List[Dict[str, Any]],
        context_config: Dict[str, Any],
    ) -> None:
        """
        提交执行任务到队列

        Args:
            execution_id: 执行记录ID
            cases: 用例列表
            context_config: 上下文配置 {base_url, headers, env}
        """
        task = {
            "execution_id": execution_id,
            "cases": cases,
            "context_config": context_config,
        }
        await self._queue.put(task)

        # 更新状态为WAITING
        ResultWriter.update_execution(execution_id, status="waiting")
        log.info(f"ExecutionQueue | 任务入队 | execution_id={execution_id}, cases={len(cases)}")

    async def _worker_loop(self, worker_id: int) -> None:
        """Worker循环"""
        log.info(f"ExecutionQueue | Worker-{worker_id} 启动")

        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._execute_task(task, worker_id)
            except Exception as e:
                log.error(f"ExecutionQueue | Worker-{worker_id} 执行异常: {e}")

        log.info(f"ExecutionQueue | Worker-{worker_id} 停止")

    async def _execute_task(self, task: Dict[str, Any], worker_id: int) -> None:
        """执行单个任务"""
        execution_id = task["execution_id"]
        cases = task["cases"]
        context_config = task["context_config"]

        log.info(f"ExecutionQueue | Worker-{worker_id} | 开始执行 | execution_id={execution_id}")

        # 更新状态为RUNNING
        ResultWriter.update_execution(execution_id, status="running")

        # 初始化上下文
        context = ExecutionContext(
            base_url=context_config.get("base_url", "http://localhost:8080"),
            headers=context_config.get("headers", {}),
            variables=context_config.get("variables", {}),
            env=context_config.get("env", "test"),
        )

        # 执行用例
        runner = CaseRunner()
        case_results = []
        start = _time.time()

        for case in cases:
            try:
                result = await asyncio.to_thread(runner.run, case=case, context=context)
                case_results.append(result)

                # 逐条保存结果
                ResultWriter.save_case_result(execution_id, result)

            except Exception as e:
                log.error(f"ExecutionQueue | 用例执行异常: {e}")
                case_results.append({
                    "case_id": case.get("case_id", "unknown"),
                    "title": case.get("title", ""),
                    "status": "ERROR",
                    "duration_ms": 0,
                    "error": str(e),
                })

        total_ms = int((_time.time() - start) * 1000)

        # 保存全部结果
        ResultWriter.save_all_results(execution_id, case_results, total_ms)

        # 生成报告（持久化到文件，更新 report_path）
        report_path = ReportGenerator.generate_and_save(execution_id, format="html")

        _passed = sum(1 for r in case_results if r.get("status") == "PASS")
        _failed = len(case_results) - _passed

        log.info(
            f"ExecutionQueue | Worker-{worker_id} | 执行完成 | "
            f"execution_id={execution_id}, "
            f"total={len(case_results)}, "
            f"passed={_passed}, "
            f"failed={_failed}, "
            f"report={'saved' if report_path else 'failed'}"
        )
