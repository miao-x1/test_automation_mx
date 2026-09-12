"""专业测试任务工作台：局部操作 + 专业用例表 + 回写项目资产。"""
from __future__ import annotations

import json
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.execution_record import ExecutionRecord
from app.models.project_test_task import ProjectTestTask
from app.models.test_case import TestCase
from app.models.test_case_point import TestCasePoint
from app.models.test_requirement import TestRequirement
from app.services.asset_lifecycle import AssetLifecycleService
from app.services.project_memory import ProjectMemoryService
from app.services.testing_brain import (
    TestingBrainService,
    build_professional_cases,
    cases_to_playwright,
    check_case_coverage,
    infer_module,
)

OPERATIONS = {
    "analyze": "需求分析 / 测试分析",
    "generate_cases": "生成测试用例",
    "supplement_exception": "补充异常场景",
    "supplement_boundary": "补充边界场景",
    "check_coverage": "检查测试覆盖率",
    "optimize_cases": "优化测试用例",
    "to_automation": "转自动化测试",
    "execute": "执行测试",
    "analyze_failure": "分析失败原因",
    "create_bug": "生成缺陷",
    "generate_report": "生成测试报告",
}


def _loads(raw: Optional[str], default: Any = None) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def serialize_task(row: ProjectTestTask, extras: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    data = {
        "id": row.id,
        "project_id": row.project_id,
        "name": row.name,
        "focus": row.focus,
        "status": row.status,
        "requirement_text": row.requirement_text,
        "analysis": _loads(row.analysis_json, {}),
        "strategy": _loads(row.strategy_json, {}),
        "test_requirement_id": row.test_requirement_id,
        "last_execution_id": row.last_execution_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    return serialize_task_payload(data, extras)


def serialize_task_payload(data: dict[str, Any], extras: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if extras:
        data.update(extras)
    return data


def serialize_case(row: TestCase) -> dict[str, Any]:
    steps = _loads(row.steps, [])
    tags = [item for item in (getattr(row, "tags", None) or "").split(",") if item]
    return {
        "id": row.id,
        "case_code": getattr(row, "case_code", None) or f"TC-{row.id}",
        "module": getattr(row, "module", None) or "",
        "scenario": getattr(row, "scenario", None) or row.case_name,
        "case_name": row.case_name,
        "precondition": row.precondition,
        "steps": steps,
        "test_data": getattr(row, "test_data", None) or "",
        "expected_result": row.expected_result,
        "priority": row.priority,
        "type": row.type,
        "tags": tags,
        "status": row.status,
        "test_task_id": getattr(row, "test_task_id", None),
    }


class ProjectTestTaskService:
    def __init__(self):
        self.brain = TestingBrainService()
        self.assets = AssetLifecycleService()
        self.memory = ProjectMemoryService()

    def list_tasks(self, user_id: int, project_id: int) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            rows = db.query(ProjectTestTask).filter(
                ProjectTestTask.user_id == user_id,
                ProjectTestTask.project_id == project_id,
            ).order_by(ProjectTestTask.updated_at.desc()).all()
            items = []
            for row in rows:
                cases = db.query(TestCase).filter(
                    getattr(TestCase, "test_task_id") == row.id,
                    TestCase.is_deleted == False,  # noqa: E712
                ).count() if hasattr(TestCase, "test_task_id") else 0
                items.append(serialize_task(row, {"case_count": cases}))
            return items
        finally:
            db.close()

    def create_task(
        self,
        user_id: int,
        project_id: int,
        name: str,
        requirement_text: str = "",
        focus: str = "",
    ) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("请输入测试任务名称")
        db = SessionLocal()
        try:
            row = ProjectTestTask(
                user_id=user_id,
                created_by=user_id,
                project_id=project_id,
                name=name[:200],
                focus=(focus or infer_module(name + requirement_text))[:200],
                status="draft",
                requirement_text=requirement_text or f"围绕「{name}」开展局部测试。",
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            task = serialize_task(row, {"case_count": 0})
        finally:
            db.close()
        self.memory.remember(
            user_id, project_id, kind="focus", title=f"测试任务 {name}",
            content=requirement_text or name, workspace="design",
            extra={"test_task_id": task["id"]}, test_task_id=task["id"],
        )
        try:
            self.assets.create_asset(
                user_id,
                name=f"{name} 需求",
                stage="01_analysis",
                category="需求文档",
                content=task["requirement_text"],
                source="ai",
                project_id=project_id,
                ref_type="requirement",
                ref_id=task["id"],
            )
        except Exception:
            pass
        return task

    def get_workspace(self, user_id: int, project_id: int, task_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            row = self._get(db, user_id, project_id, task_id)
            task = serialize_task(row)
            cases = self._cases(db, task_id)
            executions = []
            if row.last_execution_id:
                rec = db.query(ExecutionRecord).filter(ExecutionRecord.id == row.last_execution_id).first()
                if rec:
                    executions.append({
                        "id": rec.id,
                        "status": rec.status,
                        "error": getattr(rec, "error_message", None),
                    })
        finally:
            db.close()
        assets = self.assets.list_assets(user_id, project_id=project_id, page_size=40).get("items") or []
        related = [
            item for item in assets
            if str(item.get("ref_id") or "") == str(task_id) or task["name"] in (item.get("name") or "")
        ]
        brain = self.brain.retrieve(user_id, project_id, task.get("focus") or task["name"], test_task_id=task_id, workspace="design")
        return serialize_task_payload(task, {
            "cases": cases,
            "case_count": len(cases),
            "executions": executions,
            "defects": [item for item in related if item.get("stage") == "07_defect"],
            "reports": [item for item in related if item.get("stage") == "09_report"],
            "scripts": [item for item in related if item.get("stage") == "05_scripts"],
            "data_assets": [item for item in related if item.get("category") == "测试数据"],
            "brain": {
                "expert": brain.get("expert"),
                "locations": brain.get("locations"),
                "memory": brain.get("memory"),
            },
            "operations": OPERATIONS,
        })

    def update_task(self, user_id: int, project_id: int, task_id: int, **fields: Any) -> dict[str, Any]:
        db = SessionLocal()
        try:
            row = self._get(db, user_id, project_id, task_id)
            if "name" in fields and fields["name"]:
                row.name = str(fields["name"])[:200]
            if "focus" in fields:
                row.focus = str(fields["focus"] or "")[:200]
            if "requirement_text" in fields:
                row.requirement_text = fields["requirement_text"]
            if "status" in fields and fields["status"]:
                row.status = fields["status"]
            db.commit()
            db.refresh(row)
            return serialize_task(row)
        finally:
            db.close()

    def list_cases(self, user_id: int, project_id: int, task_id: int) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            self._get(db, user_id, project_id, task_id)
            return self._cases(db, task_id)
        finally:
            db.close()

    def upsert_case(self, user_id: int, project_id: int, task_id: int, payload: dict[str, Any], case_id: Optional[int] = None) -> dict[str, Any]:
        db = SessionLocal()
        try:
            task = self._get(db, user_id, project_id, task_id)
            point = self._ensure_point(db, user_id, task)
            if case_id:
                row = db.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
                if not row:
                    raise ValueError("用例不存在")
            else:
                row = TestCase(
                    user_id=user_id,
                    created_by=user_id,
                    project_id=project_id,
                    point_id=point.id,
                    case_name=(payload.get("case_name") or payload.get("scenario") or "未命名用例")[:200],
                    priority=payload.get("priority") or "P1",
                    type=payload.get("type") or "functional",
                    status=payload.get("status") or "draft",
                )
                db.add(row)
            self._apply_case(row, payload, task_id, project_id)
            db.commit()
            db.refresh(row)
            return serialize_case(row)
        finally:
            db.close()

    def delete_case(self, user_id: int, project_id: int, task_id: int, case_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            self._get(db, user_id, project_id, task_id)
            row = db.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
            if not row:
                raise ValueError("用例不存在")
            row.is_deleted = True
            db.commit()
            return {"id": case_id, "deleted": True}
        finally:
            db.close()

    def export_cases(self, user_id: int, project_id: int, task_id: int) -> dict[str, Any]:
        cases = self.list_cases(user_id, project_id, task_id)
        headers = ["用例ID", "模块", "测试场景", "前置条件", "操作步骤", "测试数据", "预期结果", "优先级", "类型", "标签", "状态"]
        lines = [",".join(headers)]
        for item in cases:
            steps = " | ".join(
                f"{step.get('no')}.{step.get('action')}" if isinstance(step, dict) else str(step)
                for step in (item.get("steps") or [])
            )
            row = [
                item.get("case_code") or "",
                item.get("module") or "",
                item.get("scenario") or item.get("case_name") or "",
                item.get("precondition") or "",
                steps,
                item.get("test_data") or "",
                item.get("expected_result") or "",
                item.get("priority") or "",
                item.get("type") or "",
                ",".join(item.get("tags") or []),
                item.get("status") or "",
            ]
            lines.append(",".join(f'"{str(col).replace(chr(34), chr(39))}"' for col in row))
        return {"filename": f"test-cases-{task_id}.csv", "csv": "\n".join(lines), "count": len(cases)}

    def operate(self, user_id: int, project_id: int, task_id: int, op: str, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        if op not in OPERATIONS:
            raise ValueError("未知局部操作")
        payload = payload or {}
        db = SessionLocal()
        try:
            row = self._get(db, user_id, project_id, task_id)
            task = serialize_task(row)
            query = payload.get("query") or task.get("requirement_text") or task["name"]
            existing = self._cases(db, task_id)
        finally:
            db.close()
        task_name = task["name"]
        task_focus = task.get("focus") or infer_module(query)
        brain = self.brain.retrieve(user_id, project_id, query, test_task_id=task_id, workspace="design")
        result: dict[str, Any] = {"op": op, "path": OPERATIONS[op], "brain_used": True}

        if op == "analyze":
            analysis = self.brain.analyze(query)
            strategy = {
                "must_test": analysis.get("must_test") or [],
                "should_test": analysis.get("should_test") or [],
                "techniques": analysis.get("techniques") or [],
                "thinking": analysis.get("thinking") or [],
            }
            self._save_json(user_id, project_id, task_id, analysis=analysis, strategy=strategy, status="ready")
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 测试分析", "03_design", "测试设计文档", json.dumps(analysis, ensure_ascii=False))
            result.update({"analysis": analysis, "strategy": strategy, "assets": [asset]})
        elif op in {"generate_cases", "supplement_exception", "supplement_boundary"}:
            types = {
                "generate_cases": ["functional", "error", "boundary", "permission"],
                "supplement_exception": ["error"],
                "supplement_boundary": ["boundary"],
            }[op]
            built = build_professional_cases(task_focus, query, case_types=types, start_index=len(existing) + 1)
            saved = self._persist_cases(user_id, project_id, task_id, built)
            asset = self._sink(
                user_id, project_id, task_id, f"{task_name} 测试用例", "04_cases",
                "功能测试用例" if op == "generate_cases" else ("异常测试用例" if "exception" in op else "边界测试用例"),
                json.dumps(saved, ensure_ascii=False),
            )
            self.memory.remember(
                user_id, project_id, kind="test_design", title=f"{task_name} 用例",
                content=f"已写入 {len(saved)} 条专业用例", workspace="design",
                extra={"test_task_id": task_id, "count": len(saved)}, test_task_id=task_id,
            )
            result.update({"cases": saved, "assets": [asset]})
        elif op == "check_coverage":
            coverage = check_case_coverage(existing, query)
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 覆盖率", "03_design", "测试覆盖率", json.dumps(coverage, ensure_ascii=False))
            result.update({"coverage": coverage, "assets": [asset]})
        elif op == "optimize_cases":
            seen = set()
            kept, dropped = [], []
            for item in existing:
                key = (item.get("case_name"), item.get("type"))
                if key in seen:
                    dropped.append(item)
                    continue
                seen.add(key)
                kept.append(item)
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 用例优化", "03_design", "测试设计文档", json.dumps({"kept": len(kept), "dropped": len(dropped)}, ensure_ascii=False))
            result.update({"kept": kept, "dropped": dropped, "assets": [asset]})
        elif op == "to_automation":
            script = cases_to_playwright(existing, task_focus)
            asset = self._sink(user_id, project_id, task_id, f"{task_name} Playwright", "05_scripts", "Playwright脚本", script)
            result.update({"script": script, "assets": [asset]})
        elif op == "execute":
            plan = {
                "ready": True,
                "case_ids": [item["id"] for item in existing[:10]],
                "message": f"已按当前任务选出 {min(10, len(existing))} 条用例准备执行，不另起无关流程。",
            }
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 执行清单", "06_execution", "测试执行记录", json.dumps(plan, ensure_ascii=False))
            result.update({"execution": plan, "assets": [asset]})
        elif op == "analyze_failure":
            diagnosis = {
                "summary": "优先对照当前任务用例的预期结果、接口定位和最近执行错误。",
                "locations": brain.get("locations")[:4],
                "thinking": (brain.get("expert") or {}).get("thinking") or [],
            }
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 失败分析", "06_execution", "失败分析", json.dumps(diagnosis, ensure_ascii=False))
            result.update({"diagnosis": diagnosis, "assets": [asset]})
        elif op == "create_bug":
            bug = {
                "title": payload.get("title") or f"{task_name} 发现缺陷",
                "steps": payload.get("steps") or [item.get("case_name") for item in existing[:3]],
                "expected": payload.get("expected") or "与当前任务预期结果一致",
                "actual": payload.get("actual") or "执行未达预期",
            }
            asset = self._sink(user_id, project_id, task_id, bug["title"], "07_defect", "缺陷记录", json.dumps(bug, ensure_ascii=False))
            result.update({"bug": bug, "assets": [asset]})
        elif op == "generate_report":
            coverage = check_case_coverage(existing, query)
            report = {
                "task": task_name,
                "case_count": len(existing),
                "coverage": coverage,
                "conclusion": coverage.get("advice"),
            }
            asset = self._sink(user_id, project_id, task_id, f"{task_name} 测试报告", "09_report", "测试报告", json.dumps(report, ensure_ascii=False))
            result.update({"report": report, "assets": [asset]})
        result["workspace"] = self.get_workspace(user_id, project_id, task_id)
        return result

    def persist_generated(self, user_id: int, project_id: int, task_id: int, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._persist_cases(user_id, project_id, task_id, cases)

    def _get(self, db, user_id: int, project_id: int, task_id: int) -> ProjectTestTask:
        row = db.query(ProjectTestTask).filter(
            ProjectTestTask.id == task_id,
            ProjectTestTask.user_id == user_id,
            ProjectTestTask.project_id == project_id,
        ).first()
        if not row:
            raise ValueError("测试任务不存在")
        return row

    def _cases(self, db, task_id: int) -> list[dict[str, Any]]:
        if not hasattr(TestCase, "test_task_id"):
            return []
        rows = db.query(TestCase).filter(
            TestCase.test_task_id == task_id,
            TestCase.is_deleted == False,  # noqa: E712
        ).order_by(TestCase.id.asc()).all()
        return [serialize_case(row) for row in rows]

    def _ensure_point(self, db, user_id: int, task: ProjectTestTask) -> TestCasePoint:
        if task.test_requirement_id:
            point = db.query(TestCasePoint).filter(
                TestCasePoint.requirement_id == task.test_requirement_id,
                TestCasePoint.is_deleted == False,  # noqa: E712
            ).first()
            if point:
                return point
        req = TestRequirement(
            user_id=user_id,
            created_by=user_id,
            content=task.requirement_text or task.name,
            source_type="text",
            status="analyzed",
        )
        db.add(req)
        db.flush()
        point = TestCasePoint(
            user_id=user_id,
            created_by=user_id,
            requirement_id=req.id,
            name=task.focus or task.name,
            description=task.requirement_text,
            priority="P0",
            type="functional",
            scenario=task.name,
        )
        db.add(point)
        db.flush()
        task.test_requirement_id = req.id
        return point

    def _apply_case(self, row: TestCase, payload: dict[str, Any], task_id: int, project_id: int) -> None:
        row.case_name = (payload.get("case_name") or payload.get("scenario") or row.case_name)[:200]
        row.precondition = payload.get("precondition")
        steps = payload.get("steps")
        row.steps = json.dumps(steps, ensure_ascii=False) if not isinstance(steps, str) else steps
        row.expected_result = payload.get("expected_result")
        row.priority = payload.get("priority") or row.priority or "P1"
        row.type = payload.get("type") or row.type or "functional"
        row.status = payload.get("status") or row.status or "draft"
        row.project_id = project_id
        if hasattr(row, "case_code"):
            row.case_code = payload.get("case_code") or row.case_code
        if hasattr(row, "module"):
            row.module = payload.get("module") or row.module
        if hasattr(row, "scenario"):
            row.scenario = payload.get("scenario") or row.case_name
        if hasattr(row, "test_data"):
            row.test_data = payload.get("test_data")
        if hasattr(row, "tags"):
            tags = payload.get("tags") or []
            row.tags = ",".join(tags) if isinstance(tags, list) else str(tags or "")
        if hasattr(row, "test_task_id"):
            row.test_task_id = task_id

    def _persist_cases(self, user_id: int, project_id: int, task_id: int, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        db = SessionLocal()
        saved: list[dict[str, Any]] = []
        try:
            task = self._get(db, user_id, project_id, task_id)
            point = self._ensure_point(db, user_id, task)
            for item in cases:
                row = TestCase(
                    user_id=user_id,
                    created_by=user_id,
                    project_id=project_id,
                    point_id=point.id,
                    case_name=(item.get("case_name") or item.get("scenario") or "未命名用例")[:200],
                    priority=item.get("priority") or "P1",
                    type=item.get("type") or "functional",
                    status="draft",
                )
                db.add(row)
                db.flush()
                self._apply_case(row, item, task_id, project_id)
                saved.append(serialize_case(row))
            db.commit()
            return saved
        except Exception:
            db.rollback()
            return cases
        finally:
            db.close()

    def _save_json(self, user_id: int, project_id: int, task_id: int, **fields: Any) -> None:
        db = SessionLocal()
        try:
            row = self._get(db, user_id, project_id, task_id)
            if "analysis" in fields:
                row.analysis_json = json.dumps(fields["analysis"], ensure_ascii=False)
            if "strategy" in fields:
                row.strategy_json = json.dumps(fields["strategy"], ensure_ascii=False)
            if "status" in fields:
                row.status = fields["status"]
            db.commit()
        finally:
            db.close()

    def _sink(self, user_id: int, project_id: int, task_id: int, name: str, stage: str, category: str, content: str) -> dict[str, Any]:
        created = self.assets.create_asset(
            user_id,
            name=name,
            stage=stage,
            category=category,
            content=content,
            source="ai",
            project_id=project_id,
            ref_id=task_id,
        )
        self.memory.remember(
            user_id, project_id, kind="conclusion", title=name,
            content=content[:400], workspace="design",
            extra={"test_task_id": task_id, "asset_id": created.get("id")},
            test_task_id=task_id,
        )
        return created
