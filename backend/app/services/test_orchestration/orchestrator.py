"""
TestOrchestrator - 测试编排服务层

作为 API 与 ExecutionFlow 引擎之间的桥梁,负责:
1. TestPlan CRUD(创建/查询/更新/删除/列表)
2. PlanSuite 关联管理(添加 Suite/移除 Suite/重排序)
3. 触发 ExecutionFlow 执行测试计划(同步 + 异步)
4. PlanExecution 历史查询与状态查询
5. 报告查询(对接 ReportGenerator / 落地文件)

依赖:
- ExecutionFlow(执行引擎)
- ReportGenerator(单 Suite 报告)
- SessionLocal(事务管理)
- TestPlan / PlanSuite / PlanExecution 数据模型

使用方式:
    orchestrator = get_test_orchestrator()
    plan = orchestrator.create_plan({...}, user_id=1)
    orchestrator.add_suite(plan_id=plan["id"], suite_id=5, execution_order=0)
    result = await orchestrator.execute_plan(plan["id"], user_id=1)
    history = orchestrator.list_executions(plan_id=plan["id"])
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.test_plan import TestPlan, PlanSuite, PlanExecution
from app.models.test_suite import TestSuite
from app.services.test_orchestration.execution_flow import (
    ExecutionFlow,
    get_execution_flow,
)

logger = logging.getLogger(__name__)


# ============================================================
# 合法状态(用于状态机校验)
# ============================================================

# TestPlan 允许的状态
_PLAN_STATUSES = {"draft", "ready", "running", "completed", "failed", "archived"}

# PlanExecution 允许的状态
_EXEC_STATUSES = {"pending", "running", "success", "failed", "cancelled", "timeout"}

# 允许的执行策略
_STRATEGIES = {"serial", "parallel"}

# 允许的失败策略
_FAIL_POLICIES = {"stop", "continue"}

# PlanSuite 允许的角色
_SUITE_ROLES = {"main", "setup", "teardown"}


class TestOrchestrator:
    """测试编排服务

    所有方法均为同步,仅 execute_plan 为 async(委托给 ExecutionFlow)。
    """

    def __init__(self, execution_flow: Optional[ExecutionFlow] = None) -> None:
        self._flow = execution_flow

    # ------------------------------------------------------------------ #
    #  会话管理                                                          #
    # ------------------------------------------------------------------ #

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文管理器

        正常退出 → commit
        异常退出 → rollback + 抛出原异常
        """
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _get_flow(self) -> ExecutionFlow:
        """懒加载 ExecutionFlow"""
        if self._flow is None:
            self._flow = get_execution_flow()
        return self._flow

    # ------------------------------------------------------------------ #
    #  TestPlan CRUD                                                     #
    # ------------------------------------------------------------------ #

    def create_plan(
        self,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """创建测试计划

        Args:
            payload: 计划字段(name 必填,其他可选)
            user_id: 创建者用户 ID

        Returns:
            创建的 TestPlan 字典
        """
        # 校验
        name = (payload.get("name") or "").strip()
        if not name:
            raise ValueError("name is required")

        strategy = payload.get("strategy", "serial")
        if strategy not in _STRATEGIES:
            raise ValueError(f"invalid strategy: {strategy}, must be one of {_STRATEGIES}")

        fail_policy = payload.get("fail_policy", "continue")
        if fail_policy not in _FAIL_POLICIES:
            raise ValueError(f"invalid fail_policy: {fail_policy}, must be one of {_FAIL_POLICIES}")

        status = payload.get("status", "draft")
        if status not in _PLAN_STATUSES:
            raise ValueError(f"invalid status: {status}")

        with self._session() as db:
            plan = TestPlan(
                name=name,
                description=payload.get("description"),
                strategy=strategy,
                fail_policy=fail_policy,
                env=payload.get("env", "test"),
                base_url=payload.get("base_url"),
                headers_json=payload.get("headers_json"),
                variables_json=payload.get("variables_json"),
                max_concurrency=payload.get("max_concurrency", 4),
                retry_count=payload.get("retry_count", 0),
                retry_delay=payload.get("retry_delay", 5),
                timeout_seconds=payload.get("timeout_seconds", 3600),
                schedule_cron=payload.get("schedule_cron"),
                schedule_enabled=payload.get("schedule_enabled", False),
                status=status,
                tags=payload.get("tags"),
                user_id=user_id,
                created_by=user_id,
            )
            db.add(plan)
            db.flush()
            plan_id = plan.id
            result = plan.to_dict(include_suites=True)

        logger.info(f"[TestOrchestrator] created plan id={plan_id} name={name}")
        return result

    def get_plan(
        self,
        plan_id: int,
        *,
        include_suites: bool = True,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取测试计划详情

        Args:
            plan_id: 计划 ID
            include_suites: 是否包含关联的 Suite 列表
            user_id: 用户 ID(用于数据隔离,为 None 时不限制)

        Returns:
            计划字典,不存在返回 None
        """
        db = SessionLocal()
        try:
            q = db.query(TestPlan).filter(
                TestPlan.id == plan_id,
                TestPlan.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestPlan.user_id == user_id)
            plan = q.first()
            if plan is None:
                return None
            return plan.to_dict(include_suites=include_suites)
        finally:
            db.close()

    def update_plan(
        self,
        plan_id: int,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新测试计划(部分更新)

        Args:
            plan_id: 计划 ID
            payload: 待更新字段
            user_id: 用户 ID

        Returns:
            更新后的计划字典

        Raises:
            ValueError: 计划不存在或字段非法
        """
        # 校验枚举字段
        if "strategy" in payload and payload["strategy"] not in _STRATEGIES:
            raise ValueError(f"invalid strategy: {payload['strategy']}")
        if "fail_policy" in payload and payload["fail_policy"] not in _FAIL_POLICIES:
            raise ValueError(f"invalid fail_policy: {payload['fail_policy']}")
        if "status" in payload and payload["status"] not in _PLAN_STATUSES:
            raise ValueError(f"invalid status: {payload['status']}")

        # 禁止更新的字段(自动生成或不可变)
        _IMMUTABLE = {"id", "created_at", "updated_at", "run_count", "last_run_at", "last_run_status"}

        with self._session() as db:
            q = db.query(TestPlan).filter(
                TestPlan.id == plan_id,
                TestPlan.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(TestPlan.user_id == user_id)
            plan = q.first()
            if plan is None:
                raise ValueError(f"TestPlan not found: {plan_id}")

            for key, value in payload.items():
                if key in _IMMUTABLE:
                    continue
                if hasattr(plan, key):
                    setattr(plan, key, value)

            db.flush()
            result = plan.to_dict(include_suites=True)

        logger.info(f"[TestOrchestrator] updated plan id={plan_id}")
        return result

    def delete_plan(
        self,
        plan_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除测试计划

        Args:
            plan_id: 计划 ID
            hard: True=物理删除 False=软删除(默认)
            user_id: 用户 ID

        Returns:
            是否删除成功
        """
        with self._session() as db:
            q = db.query(TestPlan).filter(TestPlan.id == plan_id)
            if user_id is not None:
                q = q.filter(TestPlan.user_id == user_id)
            plan = q.first()
            if plan is None:
                return False

            if hard:
                db.delete(plan)
            else:
                plan.is_deleted = True
                plan.status = "archived"
            db.flush()

        logger.info(f"[TestOrchestrator] deleted plan id={plan_id} hard={hard}")
        return True

    def list_plans(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        strategy: Optional[str] = None,
        tags: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询测试计划列表

        Returns:
            {"items": [...], "total": N, "page": 1, "page_size": 20}
        """
        db = SessionLocal()
        try:
            q = db.query(TestPlan).filter(TestPlan.is_deleted == False)

            if user_id is not None:
                q = q.filter(TestPlan.user_id == user_id)
            if status:
                q = q.filter(TestPlan.status == status)
            if strategy:
                q = q.filter(TestPlan.strategy == strategy)
            if keyword:
                like = f"%{keyword}%"
                q = q.filter(TestPlan.name.like(like))
            if tags:
                # tags 逗号分隔,任一匹配
                for tag in [t.strip() for t in tags.split(",") if t.strip()]:
                    q = q.filter(TestPlan.tags.like(f"%{tag}%"))

            total = q.count()
            items = (
                q.order_by(desc(TestPlan.updated_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [p.to_dict(include_suites=False) for p in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  PlanSuite 关联管理                                                #
    # ------------------------------------------------------------------ #

    def add_suite(
        self,
        plan_id: int,
        suite_id: int,
        *,
        execution_order: Optional[int] = None,
        role: str = "main",
        env_override: Optional[str] = None,
        base_url_override: Optional[str] = None,
        variables_override: Optional[str] = None,
        enabled: bool = True,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """将 TestSuite 添加到 TestPlan

        Args:
            plan_id: 计划 ID
            suite_id: 套件 ID
            execution_order: 执行顺序(为空则追加到最后)
            role: 角色(main/setup/teardown)
            ...

        Returns:
            PlanSuite 字典

        Raises:
            ValueError: 计划/套件不存在,或已关联
        """
        if role not in _SUITE_ROLES:
            raise ValueError(f"invalid role: {role}, must be one of {_SUITE_ROLES}")

        with self._session() as db:
            # 校验 Plan 存在
            plan_q = db.query(TestPlan).filter(
                TestPlan.id == plan_id,
                TestPlan.is_deleted == False,
            )
            if user_id is not None:
                plan_q = plan_q.filter(TestPlan.user_id == user_id)
            plan = plan_q.first()
            if plan is None:
                raise ValueError(f"TestPlan not found: {plan_id}")

            # 校验 Suite 存在
            suite = db.query(TestSuite).filter(
                TestSuite.id == suite_id,
                TestSuite.is_deleted == False,
            ).first()
            if suite is None:
                raise ValueError(f"TestSuite not found: {suite_id}")

            # 校验未重复关联
            existed = db.query(PlanSuite).filter(
                PlanSuite.plan_id == plan_id,
                PlanSuite.suite_id == suite_id,
            ).first()
            if existed is not None:
                raise ValueError(f"Suite {suite_id} already added to plan {plan_id}")

            # 自动追加 execution_order
            if execution_order is None:
                max_order = db.query(PlanSuite).filter(
                    PlanSuite.plan_id == plan_id,
                ).count()
                execution_order = max_order

            plan_suite = PlanSuite(
                plan_id=plan_id,
                suite_id=suite_id,
                execution_order=execution_order,
                role=role,
                env_override=env_override,
                base_url_override=base_url_override,
                variables_override=variables_override,
                enabled=enabled,
                user_id=user_id,
                created_by=user_id,
            )
            db.add(plan_suite)

            # 更新 Plan 的 suite_count 冗余字段
            plan.suite_count = (plan.suite_count or 0) + 1
            if plan.status == "draft":
                plan.status = "ready"

            db.flush()
            result = plan_suite.to_dict()

        logger.info(
            f"[TestOrchestrator] added suite {suite_id} to plan {plan_id}, "
            f"order={execution_order}, role={role}"
        )
        return result

    def remove_suite(
        self,
        plan_id: int,
        suite_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> bool:
        """从 TestPlan 移除 TestSuite

        Args:
            plan_id: 计划 ID
            suite_id: 套件 ID

        Returns:
            是否移除成功
        """
        with self._session() as db:
            q = db.query(PlanSuite).filter(
                PlanSuite.plan_id == plan_id,
                PlanSuite.suite_id == suite_id,
            )
            plan_suite = q.first()
            if plan_suite is None:
                return False

            q.delete()

            # 更新 Plan 统计
            plan = db.query(TestPlan).filter(TestPlan.id == plan_id).first()
            if plan and plan.suite_count and plan.suite_count > 0:
                plan.suite_count -= 1
                if plan.suite_count == 0 and plan.status == "ready":
                    plan.status = "draft"

            db.flush()

        logger.info(f"[TestOrchestrator] removed suite {suite_id} from plan {plan_id}")
        return True

    def reorder_suites(
        self,
        plan_id: int,
        suite_orders: List[Dict[str, int]],
        *,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """批量重排序 Plan 中的 Suite

        Args:
            plan_id: 计划 ID
            suite_orders: [{"suite_id": 5, "execution_order": 0}, ...]

        Returns:
            更新后的 PlanSuite 列表
        """
        with self._session() as db:
            plan_q = db.query(TestPlan).filter(
                TestPlan.id == plan_id,
                TestPlan.is_deleted == False,
            )
            if user_id is not None:
                plan_q = plan_q.filter(TestPlan.user_id == user_id)
            plan = plan_q.first()
            if plan is None:
                raise ValueError(f"TestPlan not found: {plan_id}")

            results: List[Dict[str, Any]] = []
            for item in suite_orders:
                suite_id = item.get("suite_id")
                order = item.get("execution_order", 0)
                ps = db.query(PlanSuite).filter(
                    PlanSuite.plan_id == plan_id,
                    PlanSuite.suite_id == suite_id,
                ).first()
                if ps:
                    ps.execution_order = order
                    results.append(ps.to_dict())

            db.flush()

        logger.info(f"[TestOrchestrator] reordered {len(results)} suites in plan {plan_id}")
        return results

    def toggle_suite(
        self,
        plan_id: int,
        suite_id: int,
        enabled: bool,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """启用/禁用 Plan 中的 Suite"""
        with self._session() as db:
            ps = db.query(PlanSuite).filter(
                PlanSuite.plan_id == plan_id,
                PlanSuite.suite_id == suite_id,
            ).first()
            if ps is None:
                return None
            ps.enabled = enabled
            db.flush()
            result = ps.to_dict()

        logger.info(
            f"[TestOrchestrator] suite {suite_id} in plan {plan_id} "
            f"enabled={enabled}"
        )
        return result

    def list_suites(
        self,
        plan_id: int,
        *,
        only_enabled: bool = False,
        user_id: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """列出 Plan 中的所有 Suite(带 Suite 详情)"""
        db = SessionLocal()
        try:
            q = db.query(PlanSuite).filter(PlanSuite.plan_id == plan_id)
            if only_enabled:
                q = q.filter(PlanSuite.enabled == True)
            plan_suites = q.order_by(PlanSuite.execution_order).all()

            results = []
            for ps in plan_suites:
                item = ps.to_dict()
                # 附带 Suite 详情
                suite = db.query(TestSuite).filter(TestSuite.id == ps.suite_id).first()
                if suite:
                    item["suite_name"] = suite.name
                    item["suite_type"] = suite.suite_type
                    item["suite_status"] = suite.status
                    item["case_count"] = self._count_suite_cases(suite)
                else:
                    item["suite_name"] = f"Suite-{ps.suite_id}"
                    item["suite_type"] = None
                    item["suite_status"] = "deleted"
                    item["case_count"] = 0
                results.append(item)
            return results
        finally:
            db.close()

    def _count_suite_cases(self, suite: TestSuite) -> int:
        """统计 Suite 中的用例数"""
        if not suite.case_ids:
            return 0
        try:
            ids = json.loads(suite.case_ids)
            return len(ids) if isinstance(ids, list) else 0
        except Exception:
            return 0

    # ------------------------------------------------------------------ #
    #  执行                                                              #
    # ------------------------------------------------------------------ #

    async def execute_plan(
        self,
        plan_id: int,
        *,
        user_id: Optional[int] = None,
        execution_id: Optional[str] = None,
        trigger_source: str = "manual",
        background: bool = False,
    ) -> Dict[str, Any]:
        """执行测试计划

        Args:
            plan_id: 计划 ID
            user_id: 用户 ID
            execution_id: 可指定执行 ID(为空自动生成)
            trigger_source: 触发来源(manual/schedule/api)
            background: True=后台执行(立即返回 exec_id) False=同步等待完成

        Returns:
            background=True: {"execution_id": "xxx", "status": "pending"}
            background=False: PlanExecution 的完整 to_dict()
        """
        # 校验 Plan 存在
        plan = self.get_plan(plan_id, include_suites=False, user_id=user_id)
        if plan is None:
            raise ValueError(f"TestPlan not found: {plan_id}")
        if plan["status"] == "archived":
            raise ValueError(f"TestPlan {plan_id} is archived, cannot execute")

        # 更新 Plan 状态为 running
        self.update_plan(plan_id, {"status": "running"}, user_id=user_id)

        flow = self._get_flow()
        exec_id = execution_id or f"plan_exec_{uuid.uuid4().hex[:12]}"

        if background:
            # 后台执行:启动 task,立即返回
            asyncio.create_task(
                self._execute_in_background(
                    plan_id=plan_id,
                    user_id=user_id,
                    exec_id=exec_id,
                    trigger_source=trigger_source,
                )
            )
            return {
                "execution_id": exec_id,
                "plan_id": plan_id,
                "status": "pending",
                "message": "execution started in background",
            }

        # 同步执行
        result = await flow.execute_plan(
            plan_id=plan_id,
            user_id=user_id,
            execution_id=exec_id,
            trigger_source=trigger_source,
        )

        # 根据执行结果更新 Plan 状态
        final_status = result.get("status")
        if final_status == "success":
            self.update_plan(plan_id, {"status": "completed"}, user_id=user_id)
        elif final_status in ("failed", "timeout", "cancelled"):
            self.update_plan(plan_id, {"status": "failed"}, user_id=user_id)

        return result

    async def _execute_in_background(
        self,
        plan_id: int,
        user_id: Optional[int],
        exec_id: str,
        trigger_source: str,
    ) -> None:
        """后台执行包装器(捕获异常,更新状态)"""
        try:
            flow = self._get_flow()
            result = await flow.execute_plan(
                plan_id=plan_id,
                user_id=user_id,
                execution_id=exec_id,
                trigger_source=trigger_source,
            )
            final_status = result.get("status")
            if final_status == "success":
                self.update_plan(plan_id, {"status": "completed"}, user_id=user_id)
            else:
                self.update_plan(plan_id, {"status": "failed"}, user_id=user_id)
            logger.info(
                f"[TestOrchestrator] background execution done: "
                f"plan={plan_id}, exec_id={exec_id}, status={final_status}"
            )
        except Exception as e:
            logger.error(
                f"[TestOrchestrator] background execution failed: {e}",
                exc_info=True,
            )
            try:
                self.update_plan(plan_id, {"status": "failed"}, user_id=user_id)
            except Exception:
                pass

    async def cancel_execution(
        self,
        execution_id: str,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """取消正在执行的 Plan

        Args:
            execution_id: 执行 ID(plan_exec_xxx)

        Returns:
            更新后的 PlanExecution 字典
        """
        with self._session() as db:
            exec_record = db.query(PlanExecution).filter(
                PlanExecution.execution_id == execution_id,
            ).first()
            if exec_record is None:
                raise ValueError(f"PlanExecution not found: {execution_id}")

            if exec_record.status in ("success", "failed", "cancelled", "timeout"):
                return exec_record.to_dict()

            # 通过 Runtime 取消关联任务
            runtime_task_id = exec_record.runtime_task_id
            if runtime_task_id:
                try:
                    from app.runtime.enterprise import get_task_dispatcher
                    dispatcher = get_task_dispatcher()
                    await dispatcher.cancel(runtime_task_id)
                    logger.info(
                        f"[TestOrchestrator] cancelled runtime task {runtime_task_id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[TestOrchestrator] cancel runtime task failed: {e}"
                    )

            exec_record.status = "cancelled"
            exec_record.end_time = datetime.now().isoformat()
            db.flush()
            result = exec_record.to_dict()

        # 更新 Plan 状态为 failed(取消视为失败)
        plan_id = result.get("plan_id")
        if plan_id:
            try:
                self.update_plan(plan_id, {"status": "failed"}, user_id=user_id)
            except Exception:
                pass

        return result

    # ------------------------------------------------------------------ #
    #  PlanExecution 查询                                                #
    # ------------------------------------------------------------------ #

    def get_execution(
        self,
        execution_id: str,
        *,
        include_details: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """获取执行记录详情"""
        db = SessionLocal()
        try:
            # execution_id 可能是字符串(plan_exec_xxx)或数据库主键
            q = db.query(PlanExecution).filter(
                PlanExecution.execution_id == execution_id,
            )
            exec_record = q.first()
            if exec_record is None:
                # 尝试按主键 ID 查询
                try:
                    pk = int(execution_id)
                    exec_record = db.query(PlanExecution).filter(
                        PlanExecution.id == pk,
                    ).first()
                except (ValueError, TypeError):
                    pass
            if exec_record is None:
                return None
            return exec_record.to_dict(include_details=include_details)
        finally:
            db.close()

    def list_executions(
        self,
        *,
        plan_id: Optional[int] = None,
        status: Optional[str] = None,
        trigger_source: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """分页查询执行历史

        Returns:
            {"items": [...], "total": N, "page": 1, "page_size": 20}
        """
        db = SessionLocal()
        try:
            q = db.query(PlanExecution)
            if plan_id is not None:
                q = q.filter(PlanExecution.plan_id == plan_id)
            if status:
                q = q.filter(PlanExecution.status == status)
            if trigger_source:
                q = q.filter(PlanExecution.trigger_source == trigger_source)
            if user_id is not None:
                q = q.filter(PlanExecution.user_id == user_id)

            total = q.count()
            items = (
                q.order_by(desc(PlanExecution.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [e.to_dict(include_details=False) for e in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_execution_stats(
        self,
        plan_id: Optional[int] = None,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取执行统计

        Returns:
            {
                "total_executions": N,
                "success": N, "failed": N, "running": N,
                "success_rate": 85.5,
                "avg_duration": 12.3,
                "total_cases": N, "passed_cases": N, "failed_cases": N,
            }
        """
        db = SessionLocal()
        try:
            q = db.query(PlanExecution)
            if plan_id is not None:
                q = q.filter(PlanExecution.plan_id == plan_id)
            if user_id is not None:
                q = q.filter(PlanExecution.user_id == user_id)

            all_execs = q.all()
            total = len(all_execs)
            if total == 0:
                return {
                    "total_executions": 0,
                    "success": 0, "failed": 0, "running": 0,
                    "success_rate": 0.0, "avg_duration": 0.0,
                    "total_cases": 0, "passed_cases": 0, "failed_cases": 0,
                }

            success = sum(1 for e in all_execs if e.status == "success")
            failed = sum(1 for e in all_execs if e.status in ("failed", "timeout", "cancelled"))
            running = sum(1 for e in all_execs if e.status == "running")

            durations = [e.duration or 0.0 for e in all_execs if e.duration]
            avg_duration = sum(durations) / len(durations) if durations else 0.0

            total_cases = sum(e.total_cases or 0 for e in all_execs)
            passed_cases = sum(e.passed_cases or 0 for e in all_execs)
            failed_cases = sum(e.failed_cases or 0 for e in all_execs)

            return {
                "total_executions": total,
                "success": success,
                "failed": failed,
                "running": running,
                "success_rate": round(success / total * 100, 2) if total else 0.0,
                "avg_duration": round(avg_duration, 2),
                "total_cases": total_cases,
                "passed_cases": passed_cases,
                "failed_cases": failed_cases,
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  报告查询                                                          #
    # ------------------------------------------------------------------ #

    def get_report(
        self,
        execution_id: str,
        *,
        format: str = "json",
    ) -> Dict[str, Any]:
        """获取计划执行报告

        优先读取 PlanExecution.report_path 指向的 JSON 文件,
        若文件不存在则基于 DB 中的执行记录重新构建。

        Args:
            execution_id: 执行 ID
            format: 报告格式(json,未来支持 html)

        Returns:
            报告字典
        """
        db = SessionLocal()
        try:
            exec_record = db.query(PlanExecution).filter(
                PlanExecution.execution_id == execution_id,
            ).first()
            if exec_record is None:
                try:
                    pk = int(execution_id)
                    exec_record = db.query(PlanExecution).filter(
                        PlanExecution.id == pk,
                    ).first()
                except (ValueError, TypeError):
                    pass
            if exec_record is None:
                return {"error": "execution not found", "execution_id": execution_id}

            # 1. 优先读取落地文件
            import os
            if exec_record.report_path and os.path.exists(exec_record.report_path):
                try:
                    with open(exec_record.report_path, "r", encoding="utf-8") as f:
                        report = json.load(f)
                    return {
                        "execution_id": execution_id,
                        "format": "file",
                        "report_path": exec_record.report_path,
                        "report": report,
                    }
                except Exception as e:
                    logger.warning(
                        f"[TestOrchestrator] read report file failed: {e}"
                    )

            # 2. 基于 DB 数据构建
            suite_executions = []
            if exec_record.suite_executions_json:
                try:
                    suite_executions = json.loads(exec_record.suite_executions_json)
                except Exception:
                    suite_executions = []

            total = exec_record.total_cases or 0
            passed = exec_record.passed_cases or 0
            failed = exec_record.failed_cases or 0
            pass_rate = round(passed / total * 100, 2) if total > 0 else 0.0

            report = {
                "execution_id": execution_id,
                "plan_id": exec_record.plan_id,
                "plan_name": exec_record.plan_name,
                "strategy": exec_record.strategy,
                "fail_policy": exec_record.fail_policy,
                "env": exec_record.env,
                "status": exec_record.status,
                "start_time": exec_record.start_time,
                "end_time": exec_record.end_time,
                "duration": exec_record.duration,
                "summary": {
                    "total_suites": exec_record.total_suites,
                    "executed_suites": exec_record.executed_suites,
                    "success_suites": exec_record.success_suites,
                    "failed_suites": exec_record.failed_suites,
                    "skipped_suites": exec_record.skipped_suites,
                    "total_cases": total,
                    "passed_cases": passed,
                    "failed_cases": failed,
                    "pass_rate": pass_rate,
                },
                "suites": suite_executions,
                "error_message": exec_record.error_message,
                "trigger_source": exec_record.trigger_source,
                "timestamp": datetime.now().isoformat(),
            }

            return {
                "execution_id": execution_id,
                "format": "inline",
                "report": report,
            }
        finally:
            db.close()

    def list_reports(
        self,
        *,
        plan_id: Optional[int] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """列出执行报告(轻量级,只返回元数据)"""
        db = SessionLocal()
        try:
            q = db.query(PlanExecution).filter(
                PlanExecution.report_path.isnot(None),
            )
            if plan_id is not None:
                q = q.filter(PlanExecution.plan_id == plan_id)
            if user_id is not None:
                q = q.filter(PlanExecution.user_id == user_id)

            total = q.count()
            items = (
                q.order_by(desc(PlanExecution.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )

            return {
                "items": [
                    {
                        "execution_id": e.execution_id,
                        "plan_id": e.plan_id,
                        "plan_name": e.plan_name,
                        "status": e.status,
                        "report_path": e.report_path,
                        "start_time": e.start_time,
                        "end_time": e.end_time,
                        "duration": e.duration,
                        "total_cases": e.total_cases,
                        "passed_cases": e.passed_cases,
                        "failed_cases": e.failed_cases,
                    }
                    for e in items
                ],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  统计 / 概览                                                       #
    # ------------------------------------------------------------------ #

    def get_plan_overview(
        self,
        plan_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取计划概览(基本信息 + Suite 列表 + 最近执行 + 统计)"""
        plan = self.get_plan(plan_id, include_suites=True, user_id=user_id)
        if plan is None:
            raise ValueError(f"TestPlan not found: {plan_id}")

        suites = self.list_suites(plan_id, only_enabled=False, user_id=user_id)
        recent_execs = self.list_executions(
            plan_id=plan_id, user_id=user_id, page=1, page_size=5,
        )
        stats = self.get_execution_stats(plan_id=plan_id, user_id=user_id)

        return {
            "plan": plan,
            "suites": suites,
            "recent_executions": recent_execs["items"],
            "stats": stats,
        }

    def get_dashboard(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """获取测试编排总览数据"""
        db = SessionLocal()
        try:
            q = db.query(TestPlan).filter(TestPlan.is_deleted == False)
            if user_id is not None:
                q = q.filter(TestPlan.user_id == user_id)
            all_plans = q.all()

            plan_stats = {
                "total": len(all_plans),
                "draft": sum(1 for p in all_plans if p.status == "draft"),
                "ready": sum(1 for p in all_plans if p.status == "ready"),
                "running": sum(1 for p in all_plans if p.status == "running"),
                "completed": sum(1 for p in all_plans if p.status == "completed"),
                "failed": sum(1 for p in all_plans if p.status == "failed"),
                "archived": sum(1 for p in all_plans if p.status == "archived"),
            }

            exec_stats = self.get_execution_stats(user_id=user_id)

            return {
                "plans": plan_stats,
                "executions": exec_stats,
            }
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================

_orchestrator: Optional[TestOrchestrator] = None


def get_test_orchestrator() -> TestOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = TestOrchestrator()
    return _orchestrator


def reset_test_orchestrator() -> None:
    """重置单例(测试用)"""
    global _orchestrator
    _orchestrator = None
