"""
ExecutionFlow - 执行流程引擎

负责按 TestPlan 的策略执行多个 TestSuite:
- serial(串行): 按顺序逐个执行 Suite,前一个完成才下一个
- parallel(并行): 同时执行所有 Suite(asyncio.gather)
- fail_stop(失败停止): Suite 失败则中止整个 Plan,剩余标记 skipped
- fail_continue(失败继续): Suite 失败也继续执行后续

每个 Suite 的执行通过 Runtime 的 TaskDispatcher 提交,
由 AgentFactory 创建对应 Agent 执行用例,
结果落库 ExecutionRecord + SuiteExecution。

执行完成后调用 ReportAgent 生成 Plan 级汇总报告。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.models.test_plan import TestPlan, PlanSuite, PlanExecution

logger = logging.getLogger(__name__)


class SuiteExecutionResult:
    """单个 Suite 的执行结果"""

    def __init__(
        self,
        suite_id: int,
        suite_name: str = "",
        execution_id: Optional[int] = None,
        runtime_task_id: Optional[str] = None,
    ):
        self.suite_id = suite_id
        self.suite_name = suite_name
        self.execution_id = execution_id
        self.runtime_task_id = runtime_task_id
        self.status: str = "pending"  # pending/running/success/failed/skipped/error
        self.total_cases: int = 0
        self.passed_cases: int = 0
        self.failed_cases: int = 0
        self.skipped_cases: int = 0
        self.duration: float = 0.0
        self.error: Optional[str] = None
        self.start_time: Optional[str] = None
        self.end_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "suite_name": self.suite_name,
            "execution_id": self.execution_id,
            "runtime_task_id": self.runtime_task_id,
            "status": self.status,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "skipped_cases": self.skipped_cases,
            "duration": round(self.duration, 3),
            "error": self.error,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


class ExecutionFlow:
    """
    执行流程引擎

    使用方式:
        flow = get_execution_flow()
        result = await flow.execute_plan(plan_id=1, user_id=1)
    """

    def __init__(self) -> None:
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        logger.info("ExecutionFlow initialized")

    async def execute_plan(
        self,
        plan_id: int,
        user_id: Optional[int] = None,
        execution_id: Optional[str] = None,
        trigger_source: str = "manual",
    ) -> Dict[str, Any]:
        """
        执行测试计划

        流程:
        1. 加载 TestPlan + PlanSuite 列表
        2. 创建 PlanExecution 记录
        3. 按 strategy(serial/parallel)执行所有 Suite
        4. 按 fail_policy(stop/continue)处理失败
        5. 汇总结果 + 更新 PlanExecution
        6. 触发报告生成

        返回:PlanExecution 的 to_dict()
        """
        if not self._initialized:
            self.initialize()

        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            # 1. 加载 Plan
            plan = db.query(TestPlan).filter(
                TestPlan.id == plan_id,
                TestPlan.is_deleted == False,
            ).first()
            if plan is None:
                raise ValueError(f"TestPlan not found: {plan_id}")

            # 加载关联的 Suite(按 execution_order 排序)
            plan_suites = db.query(PlanSuite).filter(
                PlanSuite.plan_id == plan_id,
                PlanSuite.enabled == True,
            ).order_by(PlanSuite.execution_order).all()

            if not plan_suites:
                raise ValueError(f"TestPlan {plan_id} has no enabled suites")

            # 2. 创建 PlanExecution 记录
            exec_id = execution_id or f"plan_exec_{uuid.uuid4().hex[:12]}"
            plan_exec = PlanExecution(
                plan_id=plan_id,
                plan_name=plan.name,
                execution_id=exec_id,
                strategy=plan.strategy,
                fail_policy=plan.fail_policy,
                env=plan.env,
                status="running",
                start_time=datetime.now().isoformat(),
                total_suites=len(plan_suites),
                trigger_source=trigger_source,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(plan_exec)
            db.commit()
            db.refresh(plan_exec)

            logger.info(
                f"[ExecutionFlow] start plan '{plan.name}' (id={plan_id}), "
                f"strategy={plan.strategy}, fail_policy={plan.fail_policy}, "
                f"suites={len(plan_suites)}, exec_id={exec_id}"
            )

            # 3. 执行
            start_time = time.time()
            suite_results: List[SuiteExecutionResult] = []

            if plan.strategy == "parallel":
                suite_results = await self._execute_parallel(
                    plan, plan_suites, user_id, exec_id, db
                )
            else:
                # serial(默认)
                suite_results = await self._execute_serial(
                    plan, plan_suites, user_id, exec_id, db
                )

            duration = time.time() - start_time

            # 4. 汇总
            total_cases = sum(r.total_cases for r in suite_results)
            passed_cases = sum(r.passed_cases for r in suite_results)
            failed_cases = sum(r.failed_cases for r in suite_results)
            success_suites = sum(1 for r in suite_results if r.status == "success")
            failed_suites = sum(1 for r in suite_results if r.status in ("failed", "error"))
            skipped_suites = sum(1 for r in suite_results if r.status == "skipped")

            # 整体状态:有 failed 且 fail_stop → failed;否则 success
            all_skipped = all(r.status == "skipped" for r in suite_results)
            if failed_suites > 0 and plan.fail_policy == "stop":
                final_status = "failed"
            elif all_skipped:
                final_status = "failed"
            elif failed_suites > 0:
                # fail_continue 模式下,有失败也算 failed
                final_status = "failed"
            else:
                final_status = "success"

            # 5. 更新 PlanExecution
            plan_exec.status = final_status
            plan_exec.end_time = datetime.now().isoformat()
            plan_exec.duration = duration
            plan_exec.executed_suites = len(suite_results) - skipped_suites
            plan_exec.success_suites = success_suites
            plan_exec.failed_suites = failed_suites
            plan_exec.skipped_suites = skipped_suites
            plan_exec.total_cases = total_cases
            plan_exec.passed_cases = passed_cases
            plan_exec.failed_cases = failed_cases
            plan_exec.suite_executions_json = json.dumps(
                [r.to_dict() for r in suite_results],
                ensure_ascii=False,
            )
            if failed_suites > 0:
                errors = [r.error for r in suite_results if r.error]
                plan_exec.error_message = "; ".join(errors[:3])

            db.commit()

            # 更新 Plan 的统计
            plan.last_run_at = datetime.now().isoformat()
            plan.last_run_status = final_status
            plan.run_count = (plan.run_count or 0) + 1
            db.commit()

            logger.info(
                f"[ExecutionFlow] plan '{plan.name}' finished: "
                f"status={final_status}, suites={success_suites}/{failed_suites}/{skipped_suites}, "
                f"cases={passed_cases}/{failed_cases}, duration={duration:.1f}s"
            )

            # 6. 触发报告生成(异步,不阻塞)
            try:
                await self._generate_report(plan_exec.id, suite_results, plan, db)
            except Exception as e:
                logger.warning(f"[ExecutionFlow] report generation failed: {e}")

            return plan_exec.to_dict(include_details=True)

        except Exception as e:
            logger.error(f"[ExecutionFlow] execute_plan failed: {e}", exc_info=True)
            # 更新 PlanExecution 为 failed
            try:
                if 'plan_exec' in locals():
                    plan_exec.status = "failed"
                    plan_exec.error_message = str(e)
                    plan_exec.end_time = datetime.now().isoformat()
                    db.commit()
            except Exception:
                pass
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  串行执行                                                          #
    # ------------------------------------------------------------------ #

    async def _execute_serial(
        self,
        plan: TestPlan,
        plan_suites: List[PlanSuite],
        user_id: Optional[int],
        exec_id: str,
        db,
    ) -> List[SuiteExecutionResult]:
        """串行执行:按顺序逐个执行 Suite"""
        results: List[SuiteExecutionResult] = []
        fail_stop = plan.fail_policy == "stop"
        aborted = False

        for idx, ps in enumerate(plan_suites):
            if aborted:
                # fail_stop 模式下,已中止,剩余标记 skipped
                result = SuiteExecutionResult(
                    suite_id=ps.suite_id,
                    suite_name=self._get_suite_name(ps.suite_id, db),
                )
                result.status = "skipped"
                result.error = "Skipped due to previous failure (fail_stop)"
                results.append(result)
                logger.info(
                    f"[ExecutionFlow] skip suite {ps.suite_id} (fail_stop, idx={idx})"
                )
                continue

            result = await self._execute_single_suite(plan, ps, user_id, exec_id, db)
            results.append(result)

            # fail_stop 检查
            if fail_stop and result.status in ("failed", "error"):
                logger.warning(
                    f"[ExecutionFlow] abort plan due to suite {ps.suite_id} failed (fail_stop)"
                )
                aborted = True

        return results

    # ------------------------------------------------------------------ #
    #  并行执行                                                          #
    # ------------------------------------------------------------------ #

    async def _execute_parallel(
        self,
        plan: TestPlan,
        plan_suites: List[PlanSuite],
        user_id: Optional[int],
        exec_id: str,
        db,
    ) -> List[SuiteExecutionResult]:
        """并行执行:同时执行所有 Suite(asyncio.gather)"""
        max_concurrency = plan.max_concurrency or 4
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _run_with_limit(ps: PlanSuite) -> SuiteExecutionResult:
            async with semaphore:
                return await self._execute_single_suite(plan, ps, user_id, exec_id, db)

        tasks = [_run_with_limit(ps) for ps in plan_suites]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 处理异常
        final_results: List[SuiteExecutionResult] = []
        for idx, r in enumerate(results):
            if isinstance(r, Exception):
                result = SuiteExecutionResult(
                    suite_id=plan_suites[idx].suite_id,
                    suite_name=self._get_suite_name(plan_suites[idx].suite_id, db),
                )
                result.status = "error"
                result.error = str(r)
                final_results.append(result)
            else:
                final_results.append(r)

        return final_results

    # ------------------------------------------------------------------ #
    #  执行单个 Suite                                                    #
    # ------------------------------------------------------------------ #

    async def _execute_single_suite(
        self,
        plan: TestPlan,
        plan_suite: PlanSuite,
        user_id: Optional[int],
        exec_id: str,
        db,
    ) -> SuiteExecutionResult:
        """
        执行单个 Suite

        通过 Runtime TaskDispatcher 提交任务,由 Agent 执行用例。
        执行失败时按 plan.retry_count 重试。
        """
        suite_id = plan_suite.suite_id
        suite_name = self._get_suite_name(suite_id, db)
        result = SuiteExecutionResult(
            suite_id=suite_id,
            suite_name=suite_name,
        )
        result.status = "running"
        result.start_time = datetime.now().isoformat()

        suite_start = time.time()
        retry_count = plan.retry_count or 0
        last_error: Optional[str] = None

        logger.info(
            f"[ExecutionFlow] execute suite '{suite_name}' (id={suite_id}), "
            f"exec_id={exec_id}"
        )

        for attempt in range(retry_count + 1):
            try:
                # 通过 Runtime 提交 Suite 执行任务
                exec_result = await self._submit_suite_to_runtime(
                    plan=plan,
                    plan_suite=plan_suite,
                    user_id=user_id,
                    exec_id=exec_id,
                    attempt=attempt,
                    db=db,
                )

                if exec_result.get("success", False):
                    result.status = "success"
                    result.execution_id = exec_result.get("execution_id")
                    result.runtime_task_id = exec_result.get("runtime_task_id")
                    result.total_cases = exec_result.get("total", 0)
                    result.passed_cases = exec_result.get("passed", 0)
                    result.failed_cases = exec_result.get("failed", 0)
                    result.skipped_cases = exec_result.get("skipped", 0)
                    result.error = None
                    break
                else:
                    last_error = exec_result.get("error", "unknown error")
                    result.status = "failed"
                    result.error = last_error
                    if attempt < retry_count:
                        logger.info(
                            f"[ExecutionFlow] suite {suite_id} attempt {attempt + 1} failed, "
                            f"retrying in {plan.retry_delay}s..."
                        )
                        await asyncio.sleep(plan.retry_delay or 5)
                    else:
                        logger.warning(
                            f"[ExecutionFlow] suite {suite_id} failed after {attempt + 1} attempts"
                        )

            except Exception as e:
                last_error = str(e)
                result.status = "error"
                result.error = last_error
                logger.error(
                    f"[ExecutionFlow] suite {suite_id} exception: {e}",
                    exc_info=True,
                )
                if attempt < retry_count:
                    await asyncio.sleep(plan.retry_delay or 5)

        result.duration = time.time() - suite_start
        result.end_time = datetime.now().isoformat()

        logger.info(
            f"[ExecutionFlow] suite '{suite_name}' done: "
            f"status={result.status}, cases={result.passed_cases}/{result.failed_cases}, "
            f"duration={result.duration:.1f}s"
        )
        return result

    async def _submit_suite_to_runtime(
        self,
        plan: TestPlan,
        plan_suite: PlanSuite,
        user_id: Optional[int],
        exec_id: str,
        attempt: int,
        db,
    ) -> Dict[str, Any]:
        """
        将 Suite 执行提交到 Runtime

        优先使用 TaskDispatcher(企业级 Runtime),
        降级到直接调用 ExecutionDispatcher(同步执行)。

        环境配置注入:
        1. 从 EnvironmentManager 获取环境运行时配置(含解密的 db/api_key 等)
        2. Plan 的 base_url/variables 覆盖环境配置
        3. 将合并后的完整配置注入到 TaskRequest.payload
        """
        # 构建执行配置
        env = plan_suite.env_override or plan.env or "test"
        base_url = plan_suite.base_url_override or plan.base_url or ""
        variables = {}
        if plan.variables_json:
            try:
                variables.update(json.loads(plan.variables_json))
            except Exception:
                pass
        if plan_suite.variables_override:
            try:
                variables.update(json.loads(plan_suite.variables_override))
            except Exception:
                pass

        # 注入环境管理器配置(自动选择环境 + 解密敏感字段)
        env_config = None
        try:
            from app.services.environment_manager import get_environment_manager
            mgr = get_environment_manager()
            # 合并环境配置与 Plan 配置(Plan 优先)
            env_config = mgr.merge_with_plan_config(
                plan_env=env,
                plan_base_url=base_url or None,
                plan_variables=variables,
                user_id=user_id,
            )
            # 用合并后的 base_url 覆盖
            if env_config.get("base_url"):
                base_url = env_config["base_url"]
            # 合并 variables(环境变量 + Plan 变量)
            if env_config.get("variables"):
                variables.update(env_config["variables"])
            logger.info(
                f"[ExecutionFlow] environment config injected: "
                f"env={env_config.get('env_name')}, "
                f"base_url={base_url[:50] if base_url else 'N/A'}, "
                f"has_api_key={bool(env_config.get('api_key'))}, "
                f"has_db_password={bool(env_config.get('db', {}).get('password'))}"
            )
        except Exception as e:
            logger.warning(
                f"[ExecutionFlow] environment config injection failed: {e}, "
                f"using plan config only"
            )

        # 构建完整 payload(含环境配置)
        payload = {
            "suite_id": plan_suite.suite_id,
            "plan_execution_id": exec_id,
            "env": env,
            "base_url": base_url,
            "variables": variables,
            "attempt": attempt,
            "user_id": user_id,
        }

        # 注入环境运行时配置(供 Agent 使用解密后的敏感字段)
        if env_config:
            payload["env_config"] = {
                "env_name": env_config.get("env_name"),
                "api_url": env_config.get("api_url"),
                "web_url": env_config.get("web_url"),
                "db": env_config.get("db", {}),
                "api_key": env_config.get("api_key"),
                "api_secret": env_config.get("api_secret"),
                "headers": env_config.get("headers", {}),
                "secrets": env_config.get("secrets", {}),
            }

        # 尝试通过 Runtime TaskDispatcher 提交
        try:
            from app.runtime.enterprise import get_task_dispatcher, TaskRequest, TaskPriority

            dispatcher = get_task_dispatcher()
            task_request = TaskRequest(
                agent_name="execution_flow_agent",
                action="execute_suite",
                payload=payload,
                priority=TaskPriority.NORMAL,
                user_id=user_id,
                timeout_seconds=plan.timeout_seconds or 3600,
                max_retries=0,  # 重试由 ExecutionFlow 控制
                task_type="suite",
            )

            task_id = await dispatcher.submit(task_request)
            logger.info(
                f"[ExecutionFlow] submitted suite {plan_suite.suite_id} to runtime, "
                f"task_id={task_id}"
            )

            # 等待结果(带超时)
            timeout = plan.timeout_seconds or 3600
            try:
                state = await dispatcher.wait_for_result(task_id, timeout=timeout)
                result_data = state.result or {}
                return {
                    "success": state.status.value == "success",
                    "execution_id": result_data.get("execution_id"),
                    "runtime_task_id": task_id,
                    "total": result_data.get("total", 0),
                    "passed": result_data.get("passed", 0),
                    "failed": result_data.get("failed", 0),
                    "skipped": result_data.get("skipped", 0),
                    "error": state.error if state.status.value != "success" else None,
                }
            except asyncio.TimeoutError:
                await dispatcher.cancel(task_id)
                return {
                    "success": False,
                    "runtime_task_id": task_id,
                    "error": f"Suite execution timeout ({timeout}s)",
                }

        except ImportError:
            logger.warning("[ExecutionFlow] Runtime not available, fallback to direct execution")
        except Exception as e:
            logger.warning(f"[ExecutionFlow] Runtime submit failed: {e}, fallback to direct execution")

        # 降级:直接调用 ExecutionDispatcher
        return await self._execute_suite_direct(plan_suite, env, base_url, variables, user_id, db)

    async def _execute_suite_direct(
        self,
        plan_suite: PlanSuite,
        env: str,
        base_url: str,
        variables: Dict,
        user_id: Optional[int],
        db,
    ) -> Dict[str, Any]:
        """直接调用 ExecutionDispatcher 执行 Suite(Runtime 不可用时降级)

        TestSuite.case_ids 中存储的是 TestAsset ID 列表,
        使用 dispatch_batch 批量执行。
        """
        try:
            from app.services.execution.dispatcher import ExecutionDispatcher
            from app.models.test_suite import TestSuite

            # 加载 Suite 获取 case_ids(实际为 asset_ids)
            suite = db.query(TestSuite).filter(
                TestSuite.id == plan_suite.suite_id,
            ).first()
            if suite is None:
                return {
                    "success": False,
                    "error": f"TestSuite not found: {plan_suite.suite_id}",
                }

            # 解析 case_ids
            asset_ids: List[int] = []
            if suite.case_ids:
                try:
                    parsed = json.loads(suite.case_ids)
                    if isinstance(parsed, list):
                        asset_ids = [int(x) for x in parsed if x]
                except Exception:
                    pass

            if not asset_ids:
                return {
                    "success": False,
                    "error": "Suite has no case_ids / asset_ids to execute",
                    "total": 0, "passed": 0, "failed": 0, "skipped": 0,
                }

            # 使用 dispatch_batch 批量执行
            result = await ExecutionDispatcher.dispatch_batch(
                asset_ids=asset_ids,
                user_id=user_id or 0,
                env=env,
                base_url=base_url or "http://localhost:8080",
            )

            # 解析 dispatch_batch 返回结构
            results_list = result.get("results", [])
            passed = sum(1 for r in results_list if r.get("status") == "success")
            failed = sum(1 for r in results_list if r.get("status") not in ("success", "skipped"))
            skipped = sum(1 for r in results_list if r.get("status") == "skipped")

            return {
                "success": result.get("status") in ("success", "completed"),
                "execution_id": result.get("execution_id"),
                "total": len(results_list),
                "passed": passed,
                "failed": failed,
                "skipped": skipped,
                "error": result.get("error"),
            }
        except Exception as e:
            logger.error(f"[ExecutionFlow] direct execution failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
            }

    # ------------------------------------------------------------------ #
    #  报告生成                                                          #
    # ------------------------------------------------------------------ #

    async def _generate_report(
        self,
        plan_exec_id: int,
        suite_results: List[SuiteExecutionResult],
        plan: TestPlan,
        db,
    ) -> None:
        """生成 Plan 级汇总报告"""
        try:
            from app.services.execution.report_generator import ReportGenerator

            # 汇总数据
            total = sum(r.total_cases for r in suite_results)
            passed = sum(r.passed_cases for r in suite_results)
            failed = sum(r.failed_cases for r in suite_results)
            skipped = sum(r.skipped_cases for r in suite_results)

            report_data = {
                "plan_id": plan.id,
                "plan_name": plan.name,
                "execution_id": f"plan_exec_{plan_exec_id}",
                "timestamp": datetime.now().isoformat(),
                "summary": {
                    "total_suites": len(suite_results),
                    "success_suites": sum(1 for r in suite_results if r.status == "success"),
                    "failed_suites": sum(1 for r in suite_results if r.status in ("failed", "error")),
                    "skipped_suites": sum(1 for r in suite_results if r.status == "skipped"),
                    "total_cases": total,
                    "passed": passed,
                    "failed": failed,
                    "skipped": skipped,
                    "pass_rate": round(passed / total * 100, 2) if total > 0 else 0,
                },
                "suites": [r.to_dict() for r in suite_results],
                "strategy": plan.strategy,
                "fail_policy": plan.fail_policy,
            }

            # 写入文件
            import os
            from app.core.config import settings
            report_dir = settings.REPORT_DIR
            os.makedirs(report_dir, exist_ok=True)
            report_path = os.path.join(report_dir, f"plan_report_{plan_exec_id}.json")
            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(report_data, f, ensure_ascii=False, indent=2)

            # 更新 PlanExecution 报告路径
            plan_exec = db.query(PlanExecution).filter(PlanExecution.id == plan_exec_id).first()
            if plan_exec:
                plan_exec.report_path = report_path
                db.commit()

            logger.info(f"[ExecutionFlow] report generated: {report_path}")

        except Exception as e:
            logger.warning(f"[ExecutionFlow] report generation failed: {e}")

    # ------------------------------------------------------------------ #
    #  辅助方法                                                          #
    # ------------------------------------------------------------------ #

    def _get_suite_name(self, suite_id: int, db) -> str:
        """获取 Suite 名称"""
        try:
            from app.models.test_suite import TestSuite
            suite = db.query(TestSuite).filter(TestSuite.id == suite_id).first()
            return suite.name if suite else f"Suite-{suite_id}"
        except Exception:
            return f"Suite-{suite_id}"


# 单例
_flow: Optional[ExecutionFlow] = None


def get_execution_flow() -> ExecutionFlow:
    global _flow
    if _flow is None:
        _flow = ExecutionFlow()
    return _flow
