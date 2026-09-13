"""项目级测试用例工作台：可独立生成，也可承接需求/设计。不伪造执行结果。"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.project_test_task import ProjectTestTask
from app.models.test_case import TestCase
from app.services.project_test_task import ProjectTestTaskService, serialize_case
from app.services.requirement_analysis_doc import RequirementAnalysisDocService, extract_file_text
from app.services.test_design_doc import TestDesignDocService
from app.services.testing_brain import build_professional_cases, infer_module

SOURCE_TYPES = {"TEST_DESIGN", "REQUIREMENT", "FILE", "TEXT", "API_SPEC", "MANUAL", "IMPORT"}
REVIEW_STATUSES = {"DRAFT", "AI_GENERATED", "PENDING_REVIEW", "CHANGES_REQUIRED", "APPROVED", "DEPRECATED"}
DIM_TYPE = {
    "normal": "functional",
    "exception": "error",
    "boundary": "boundary",
    "rule": "rule",
    "permission": "permission",
    "state": "state",
    "data": "data",
    "interaction": "functional",
    "dependency": "error",
    "repeat": "error",
    "concurrency": "concurrency",
    "regression": "regression",
}
VAGUE = ("检查结果", "输入正确数据", "验证一下", "看看是否正常", "操作成功")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(raw: Any, default: Any) -> Any:
    if raw is None or raw == "":
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _meta(row: TestCase) -> dict[str, Any]:
    extra = _loads(getattr(row, "rag_references", None), {})
    return extra if isinstance(extra, dict) else {}


def serialize_workbench_case(row: TestCase) -> dict[str, Any]:
    data = serialize_case(row)
    extra = _meta(row)
    steps = []
    for index, item in enumerate(data.get("steps") or [], start=1):
        if isinstance(item, dict):
            steps.append({
                "stepNo": item.get("stepNo") or item.get("no") or index,
                "action": item.get("action") or item.get("name") or "",
                "data": item.get("data") or "",
                "expected": item.get("expected") or "",
            })
        else:
            steps.append({"stepNo": index, "action": str(item), "data": "", "expected": ""})
    data["steps"] = steps
    data["source_type"] = extra.get("source_type") or "MANUAL"
    data["source_label"] = extra.get("source_label") or ""
    data["source_id"] = extra.get("source_id") or ""
    data["review_status"] = extra.get("review_status") or ("AI_GENERATED" if data.get("status") == "draft" and extra.get("source_type") not in {None, "MANUAL"} else "DRAFT")
    data["requirement_ids"] = extra.get("requirement_ids") or []
    data["test_design_ids"] = extra.get("test_design_ids") or []
    data["test_scenario_ids"] = extra.get("test_scenario_ids") or []
    data["risk_level"] = extra.get("risk_level") or ""
    data["postconditions"] = extra.get("postconditions") or ""
    data["version"] = getattr(row, "version", 1) or 1
    data["project_id"] = getattr(row, "project_id", None)
    data["created_at"] = row.created_at.isoformat() if getattr(row, "created_at", None) else None
    data["updated_at"] = row.updated_at.isoformat() if getattr(row, "updated_at", None) else None
    return data


def _write_meta(row: TestCase, payload: dict[str, Any]) -> None:
    extra = _meta(row)
    for key in ("source_type", "source_label", "source_id", "review_status", "risk_level", "postconditions"):
        if payload.get(key) is not None:
            extra[key] = payload[key]
    for key in ("requirement_ids", "test_design_ids", "test_scenario_ids"):
        if key in payload:
            extra[key] = [str(item) for item in (payload.get(key) or []) if item]
    extra["updated_at"] = _now()
    row.rag_references = json.dumps(extra, ensure_ascii=False)


def _normalize_steps(raw: Any, data: str = "", expected: str = "") -> list[dict[str, Any]]:
    items = raw if isinstance(raw, list) else []
    steps = []
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            steps.append({
                "stepNo": item.get("stepNo") or item.get("no") or index,
                "action": str(item.get("action") or item.get("name") or "").strip(),
                "data": str(item.get("data") or data or ""),
                "expected": str(item.get("expected") or ""),
            })
        elif str(item).strip():
            steps.append({"stepNo": index, "action": str(item).strip(), "data": data, "expected": ""})
    if steps and expected and not steps[-1].get("expected"):
        steps[-1]["expected"] = expected
    if not steps:
        steps = [
            {"stepNo": 1, "action": "准备前置条件和测试数据", "data": data, "expected": "前置条件满足"},
            {"stepNo": 2, "action": "按场景执行操作", "data": data, "expected": expected or "需求未定义，待确认"},
        ]
    return steps


class CaseWorkbenchService:
    def __init__(self):
        self.tasks = ProjectTestTaskService()
        self.designs = TestDesignDocService()
        self.requirements = RequirementAnalysisDocService()

    def context(self, user_id: int, project_id: int) -> dict[str, Any]:
        req = self.requirements.get(user_id, project_id)
        design = self.designs.get(user_id, project_id)
        cases = self.list_cases(user_id, project_id)
        return {
            "requirement": {
                "available": bool(req.get("requirements") or req.get("functions")),
                "status": req.get("status"),
                "name": ((req.get("overview") or {}).get("name") or {}),
                "counts": req.get("counts") or {},
            },
            "design": {
                "available": bool(design.get("objects") or design.get("scenarios")),
                "status": design.get("status"),
                "plan": design.get("plan") or {},
                "counts": design.get("counts") or {},
                "objects": [
                    {
                        "id": item.get("id"),
                        "name": item.get("name"),
                        "module": item.get("module"),
                        "priority": item.get("priority"),
                        "scenarios": sum(1 for row in (design.get("scenarios") or []) if row.get("td_id") == item.get("id")),
                    }
                    for item in (design.get("objects") or [])[:12]
                ],
                "scenarios": [
                    {"id": item.get("id"), "td_id": item.get("td_id"), "name": item.get("name"), "dimension": item.get("dimension"), "priority": item.get("priority")}
                    for item in (design.get("scenarios") or [])[:40]
                ],
            },
            "cases": self.statistics(cases),
            "has_cases": bool(cases),
        }

    def list_cases(self, user_id: int, project_id: int) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            q = db.query(TestCase).filter(TestCase.user_id == user_id, TestCase.is_deleted == False)  # noqa: E712
            clauses = []
            if hasattr(TestCase, "project_id"):
                clauses.append(TestCase.project_id == project_id)
            task_ids = [
                row.id for row in db.query(ProjectTestTask.id).filter(
                    ProjectTestTask.user_id == user_id,
                    ProjectTestTask.project_id == project_id,
                ).all()
            ]
            if task_ids and hasattr(TestCase, "test_task_id"):
                clauses.append(TestCase.test_task_id.in_(task_ids))
            if clauses:
                from sqlalchemy import or_
                q = q.filter(or_(*clauses))
            rows = q.order_by(TestCase.id.asc()).all()
            return [serialize_workbench_case(row) for row in rows]
        finally:
            db.close()

    def get_case(self, user_id: int, project_id: int, case_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            return serialize_workbench_case(self._row(user_id, project_id, case_id, db=db))
        finally:
            db.close()

    def create_case(self, user_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        payload = dict(payload)
        payload.setdefault("source_type", "MANUAL")
        payload.setdefault("review_status", "DRAFT")
        payload.setdefault("source_label", "人工创建")
        if not payload.get("case_name"):
            raise ValueError("请填写用例名称")
        task = self._workspace_task(user_id, project_id, payload.get("case_name") or "手工用例")
        saved = self._save_cases(user_id, project_id, task["id"], [payload])
        return saved[0]

    def update_case(self, user_id: int, project_id: int, case_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            row = self._row(user_id, project_id, case_id, db=db)
            task_id = getattr(row, "test_task_id", None) or self._workspace_task(user_id, project_id, row.case_name)["id"]
            self.tasks._apply_case(row, payload, task_id, project_id)
            if hasattr(row, "version"):
                row.version = (row.version or 1) + 1
            _write_meta(row, payload)
            db.commit()
            db.refresh(row)
            return serialize_workbench_case(row)
        finally:
            db.close()

    def delete_cases(self, user_id: int, project_id: int, case_ids: list[int]) -> dict[str, Any]:
        db = SessionLocal()
        try:
            changed = 0
            for case_id in case_ids or []:
                row = db.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
                if not row:
                    continue
                row.is_deleted = True
                changed += 1
            db.commit()
            return {"deleted": changed}
        finally:
            db.close()

    def generate(self, user_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        source = str(payload.get("source_type") or "").upper()
        text = (payload.get("text") or "").strip()
        files = payload.get("files") or []
        progress = []
        if source == "TEST_DESIGN" or (not source and not text and not files):
            design = self.designs.get(user_id, project_id)
            if design.get("objects") or design.get("scenarios"):
                source = "TEST_DESIGN"
        if source == "REQUIREMENT" or (source not in SOURCE_TYPES and not text and not files):
            req = self.requirements.get(user_id, project_id)
            if source != "TEST_DESIGN" and (req.get("requirements") or req.get("functions")):
                source = "REQUIREMENT"
        if files:
            source = source if source in {"FILE", "API_SPEC", "IMPORT"} else "FILE"
        if text and source not in SOURCE_TYPES:
            source = "TEXT"
        if source not in SOURCE_TYPES:
            raise ValueError("请上传资料、描述测试目标、承接测试设计，或手动创建用例。测试用例不依赖上一阶段才能工作。")

        progress.append({"step": "正在识别输入来源", "status": "done", "detail": source})
        drafts: list[dict[str, Any]] = []
        source_label = payload.get("source_label") or ""
        if source == "TEST_DESIGN":
            design = self.designs.get(user_id, project_id)
            if not (design.get("scenarios") or design.get("objects")):
                raise ValueError("当前没有可承接的测试设计。可以改为上传资料、直接描述，或手动创建。")
            drafts = self._from_design(design, payload)
            source_label = source_label or (design.get("plan") or {}).get("name") or "测试设计"
            progress.append({"step": "正在读取测试对象和场景", "status": "done", "detail": f"{len(design.get('scenarios') or [])} 个场景"})
        elif source == "REQUIREMENT":
            req = self.requirements.get(user_id, project_id)
            if not (req.get("requirements") or req.get("functions")):
                raise ValueError("当前没有需求分析。可以上传资料或直接描述测试目标。")
            drafts = self._from_requirement(req, payload)
            source_label = source_label or "需求分析"
            progress.append({"step": "正在根据需求推导用例", "status": "done"})
        elif source in {"FILE", "API_SPEC", "IMPORT"}:
            chunks = []
            names = []
            for item in files:
                name = item.get("name") or "upload"
                names.append(name)
                chunks.append(extract_file_text(name, item.get("payload") or b""))
            if text:
                chunks.append(text)
            blob = "\n\n".join(part for part in chunks if part).strip()
            if not blob:
                raise ValueError("文件里没有可解析的文本")
            drafts = self._from_text(blob, payload, hint_name=names[0] if names else "上传资料")
            source_label = source_label or "、".join(names) or "上传资料"
            progress.append({"step": "正在解析文件并识别测试范围", "status": "done"})
        else:
            if not text:
                raise ValueError("请输入要测试的功能或场景")
            drafts = self._from_text(text, payload)
            source_label = source_label or "用户描述"
            progress.append({"step": "正在理解测试目标", "status": "done"})

        wanted_types = set(payload.get("types") or [])
        wanted_priorities = set(payload.get("priorities") or [])
        if wanted_types:
            drafts = [item for item in drafts if item.get("type") in wanted_types]
        if wanted_priorities:
            drafts = [item for item in drafts if item.get("priority") in wanted_priorities]
        if not drafts:
            raise ValueError("按当前筛选没有可生成的用例。请放宽类型或优先级，或补充输入。")

        for item in drafts:
            item["source_type"] = source
            item["source_label"] = source_label
            item["review_status"] = "AI_GENERATED"
            item["status"] = "draft"
            item["steps"] = _normalize_steps(item.get("steps"), item.get("test_data") or "", item.get("expected_result") or "")
        progress.append({"step": "正在生成结构化用例", "status": "done", "detail": f"{len(drafts)} 条"})
        quality = self.check_quality(drafts)
        progress.append({"step": "正在检查重复和可执行性", "status": "done", "detail": f"重复 {len(quality['duplicates'])}"})
        coverage = self.check_coverage(user_id, project_id, drafts)
        progress.append({"step": "正在检查覆盖", "status": "done"})
        task = self._workspace_task(user_id, project_id, source_label or infer_module(text or source_label))
        saved = self._save_cases(user_id, project_id, task["id"], drafts)
        return {
            "source_type": source,
            "source_label": source_label,
            "created": saved,
            "count": len(saved),
            "progress": progress,
            "quality": quality,
            "coverage": coverage,
            "note": "这些用例是 AI_GENERATED，不能当成已评审或已执行。",
        }

    def review(self, user_id: int, project_id: int, case_ids: list[int], review_status: str, note: str = "") -> dict[str, Any]:
        status = str(review_status or "").upper()
        if status not in REVIEW_STATUSES:
            raise ValueError("无效评审状态")
        if status == "APPROVED" and not case_ids:
            raise ValueError("请选择要评审的用例")
        db = SessionLocal()
        changed = []
        try:
            for case_id in case_ids or []:
                row = db.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
                if not row:
                    continue
                extra = _meta(row)
                extra["review_status"] = status
                extra["review_note"] = note
                extra["reviewed_at"] = _now()
                row.rag_references = json.dumps(extra, ensure_ascii=False)
                if status == "APPROVED":
                    row.status = "reviewed"
                elif status == "DEPRECATED":
                    row.status = "archived"
                elif status == "CHANGES_REQUIRED":
                    row.status = "draft"
                changed.append(case_id)
            db.commit()
        finally:
            db.close()
        return {"changed": len(changed), "review_status": status, "ids": changed}

    def batch_update(self, user_id: int, project_id: int, case_ids: list[int], patch: dict[str, Any]) -> dict[str, Any]:
        if patch.get("copy"):
            copied = []
            for case_id in case_ids or []:
                row = self.get_case(user_id, project_id, case_id)
                row["case_name"] = f"{row.get('case_name') or '用例'} 副本"
                row["case_code"] = ""
                row["source_type"] = "MANUAL"
                row["source_label"] = "批量复制"
                row["review_status"] = "DRAFT"
                row.pop("id", None)
                copied.append(self.create_case(user_id, project_id, row))
            return {"changed": len(copied), "created": copied, "patch": {"copy": True}}
        allowed = {key: patch[key] for key in ("priority", "type", "module", "tags") if key in patch}
        if not allowed:
            raise ValueError("没有可批量修改的字段")
        changed = 0
        for case_id in case_ids or []:
            self.update_case(user_id, project_id, case_id, allowed)
            changed += 1
        return {"changed": changed, "patch": allowed}

    def check_quality(self, cases: list[dict[str, Any]]) -> dict[str, Any]:
        issues = []
        seen: dict[str, str] = {}
        duplicates = []
        for item in cases:
            name = (item.get("case_name") or "").strip()
            key = re.sub(r"\s+", "", name)
            if key and key in seen:
                duplicates.append({"id": item.get("id") or item.get("case_code"), "duplicate_of": seen[key], "name": name})
            elif key:
                seen[key] = item.get("id") or item.get("case_code") or name
            if not (item.get("precondition") or "").strip():
                issues.append({"id": item.get("case_code") or item.get("id"), "problem": "缺少前置条件"})
            if not (item.get("test_data") or "").strip() or item.get("test_data") in {"使用项目已有账号/接口数据", "需求缺失"}:
                issues.append({"id": item.get("case_code") or item.get("id"), "problem": "测试数据定义不明确"})
            steps = item.get("steps") or []
            if not steps:
                issues.append({"id": item.get("case_code") or item.get("id"), "problem": "缺少测试步骤"})
            blob = " ".join(
                (step.get("action") if isinstance(step, dict) else str(step)) or ""
                for step in steps
            )
            if any(token in blob for token in VAGUE):
                issues.append({"id": item.get("case_code") or item.get("id"), "problem": "步骤描述模糊，无法直接执行"})
            if not (item.get("expected_result") or "").strip():
                issues.append({"id": item.get("case_code") or item.get("id"), "problem": "缺少预期结果"})
        return {
            "duplicates": duplicates,
            "issues": issues,
            "executable": len(cases) - len({item.get("id") or item.get("case_code") for item in issues}),
            "summary": f"重复 {len(duplicates)}，可执行性问题 {len(issues)}。AI 生成不等于已评审。",
        }

    def check_coverage(self, user_id: int, project_id: int, extra: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        cases = (extra or []) + self.list_cases(user_id, project_id)
        req = self.requirements.get(user_id, project_id)
        design = self.designs.get(user_id, project_id)
        req_ids = [item.get("id") for item in (req.get("requirements") or []) if item.get("id")]
        ts_ids = [item.get("id") for item in (design.get("scenarios") or []) if item.get("id")]
        covered_req = set()
        covered_ts = set()
        for item in cases:
            covered_req.update(item.get("requirement_ids") or [])
            covered_ts.update(item.get("test_scenario_ids") or [])
        missing_req = [rid for rid in req_ids if rid not in covered_req]
        missing_ts = [tid for tid in ts_ids if tid not in covered_ts]
        types = {item.get("type") for item in cases if item.get("type")}
        return {
            "requirements_total": len(req_ids),
            "requirements_covered": len(req_ids) - len(missing_req),
            "requirement_rate": round(100 * (len(req_ids) - len(missing_req)) / len(req_ids), 1) if req_ids else None,
            "missing_requirements": missing_req,
            "scenarios_total": len(ts_ids),
            "scenarios_covered": len(ts_ids) - len(missing_ts),
            "missing_scenarios": missing_ts,
            "type_coverage": sorted(types),
            "missing_dimensions": [name for name, key in (("正常", "functional"), ("异常", "error"), ("边界", "boundary")) if key not in types and cases],
            "rows": [
                {
                    "req_id": item.get("req_id"),
                    "td_ids": item.get("td_ids") or [],
                    "ts_ids": item.get("ts_ids") or [],
                    "case_codes": [
                        row.get("case_code") for row in cases
                        if item.get("req_id") in (row.get("requirement_ids") or [])
                    ],
                    "covered": bool(item.get("covered") and any(item.get("req_id") in (row.get("requirement_ids") or []) for row in cases)),
                }
                for item in (design.get("coverage") or [])
            ],
        }

    def export_csv(self, user_id: int, project_id: int, case_ids: Optional[list[int]] = None) -> str:
        import csv
        import io
        cases = self.list_cases(user_id, project_id)
        wanted = set(case_ids or [])
        if wanted:
            cases = [item for item in cases if item.get("id") in wanted]
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["case_code", "case_name", "module", "type", "priority", "source_type", "review_status", "precondition", "test_data", "steps", "expected_result"])
        for item in cases:
            steps = " | ".join(
                f"{step.get('stepNo')}.{step.get('action')}[{step.get('data')}]->{step.get('expected')}"
                for step in (item.get("steps") or [])
            )
            writer.writerow([
                item.get("case_code"), item.get("case_name"), item.get("module"), item.get("type"),
                item.get("priority"), item.get("source_type"), item.get("review_status"),
                item.get("precondition"), item.get("test_data"), steps, item.get("expected_result"),
            ])
        return buf.getvalue()

    def statistics(self, cases: Optional[list[dict[str, Any]]] = None, user_id: int = 0, project_id: int = 0) -> dict[str, Any]:
        rows = cases if cases is not None else self.list_cases(user_id, project_id)
        stats = {
            "total": len(rows),
            "P0": 0, "P1": 0, "P2": 0, "P3": 0,
            "AI_GENERATED": 0, "PENDING_REVIEW": 0, "APPROVED": 0, "CHANGES_REQUIRED": 0, "DRAFT": 0, "DEPRECATED": 0,
            "modules": {},
            "types": {},
        }
        for item in rows:
            stats[item.get("priority") or "P1"] = stats.get(item.get("priority") or "P1", 0) + 1
            review = item.get("review_status") or "DRAFT"
            stats[review] = stats.get(review, 0) + 1
            module = item.get("module") or "未分组"
            stats["modules"][module] = stats["modules"].get(module, 0) + 1
            kind = item.get("type") or "functional"
            stats["types"][kind] = stats["types"].get(kind, 0) + 1
        return stats

    def _from_design(self, design: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        objects = {item.get("id"): item for item in (design.get("objects") or [])}
        scenarios = design.get("scenarios") or []
        wanted = set(payload.get("scenario_ids") or payload.get("td_ids") or [])
        if wanted:
            scenarios = [
                item for item in scenarios
                if item.get("id") in wanted or item.get("td_id") in wanted
            ]
        wanted_types = set(payload.get("types") or [])
        drafts = []
        for item in scenarios:
            td = objects.get(item.get("td_id")) or {}
            drafts.extend(self._cases_from_scenario(item, td, design, wanted_types))
        if not drafts:
            for td in objects.values():
                if wanted and td.get("id") not in wanted:
                    continue
                drafts.append({
                    "case_name": f"{td.get('name')} 主路径",
                    "module": td.get("module") or "",
                    "precondition": "按测试对象前置准备",
                    "steps": [
                        {"action": "准备测试数据与账号", "data": "", "expected": "前置条件满足"},
                        {"action": f"执行 {td.get('name')}", "data": "", "expected": "按需求结果验证"},
                    ],
                    "test_data": self._design_data(design, td, {}),
                    "expected_result": "与测试对象预期一致",
                    "priority": td.get("priority") or "P1",
                    "type": "functional",
                    "requirement_ids": td.get("req_ids") or [],
                    "test_design_ids": [td.get("id")] if td.get("id") else [],
                    "test_scenario_ids": [],
                })
        return drafts

    def _cases_from_scenario(self, item: dict[str, Any], td: dict[str, Any], design: dict[str, Any], wanted_types: set[str]) -> list[dict[str, Any]]:
        case_type = DIM_TYPE.get(item.get("dimension") or "", "functional")
        data = self._design_data(design, td, item)
        primary = {
            "case_code": "",
            "case_name": item.get("name") or td.get("name") or "未命名场景",
            "module": td.get("module") or infer_module(item.get("name") or ""),
            "scenario": item.get("name"),
            "precondition": item.get("precondition") or "按测试设计前置条件准备",
            "steps": item.get("steps") or [
                {"action": "打开被测页面或接口", "data": "", "expected": "入口可用"},
                {"action": item.get("name") or "按场景执行", "data": data, "expected": item.get("expected") or "需求未定义，待确认"},
            ],
            "test_data": data,
            "expected_result": item.get("expected") or "需求未定义，待确认",
            "priority": item.get("priority") or td.get("priority") or "P1",
            "type": case_type,
            "tags": [item.get("dimension") or "", item.get("method") or ""],
            "requirement_ids": item.get("req_ids") or td.get("req_ids") or [],
            "test_design_ids": [td.get("id")] if td.get("id") else [],
            "test_scenario_ids": [item.get("id")] if item.get("id") else [],
            "risk_level": "高" if (item.get("priority") == "P0") else "中",
        }
        drafts = [primary]
        dim = item.get("dimension") or "normal"
        applicable = set(td.get("applicable") or [])
        blob = f"{item.get('name') or ''} {td.get('name') or ''} {td.get('module') or ''}"
        if dim not in {"normal", "functional", "interaction", ""}:
            return drafts
        extras = [
            ("error", "异常拒绝", "P1", f"对「{primary['case_name']}」提交非法/错误输入", "系统拒绝并提示，不产生脏数据或不安全状态"),
            ("boundary", "边界值", "P2", f"对「{primary['case_name']}」使用空值、超长或临界值", "按规则接受或明确拒绝，结果可核对"),
        ]
        if "permission" in applicable or "权限" in blob:
            extras.append(("permission", "无权限访问", "P0", f"使用无权限账号访问「{primary['case_name']}」", "页面与接口均拒绝，不泄露越权数据"))
        if "rule" in applicable or any(token in blob for token in ("规则", "过期", "锁定", "次数")):
            extras.append(("rule", "业务规则", "P1", f"触发「{primary['case_name']}」相关业务规则", "规则生效，结果与需求一致或标为待确认"))
        if "state" in applicable or any(token in blob for token in ("状态", "流转", "锁定")):
            extras.append(("state", "状态流转", "P1", f"在非法或临界状态下执行「{primary['case_name']}」", "状态迁移符合设计，非法流转被拒绝"))
        for case_type, suffix, priority, action, expected in extras:
            if wanted_types and case_type not in wanted_types:
                continue
            drafts.append({
                **primary,
                "case_name": f"{primary['case_name']} {suffix}",
                "type": case_type,
                "priority": priority,
                "steps": [
                    {"action": "准备对应异常或边界数据", "data": data, "expected": "测试数据可区分"},
                    {"action": action, "data": data, "expected": expected},
                ],
                "expected_result": expected,
                "tags": [*(primary.get("tags") or []), case_type],
            })
        return drafts

    def _design_data(self, design: dict[str, Any], td: dict[str, Any], item: dict[str, Any]) -> str:
        if item.get("data"):
            return str(item.get("data"))
        rows = [
            str(row.get("name") or row.get("item") or row.get("note") or "")
            for row in (design.get("data") or [])
            if (not row.get("td_id") or row.get("td_id") == td.get("id")) and (row.get("name") or row.get("item") or row.get("note"))
        ]
        return "；".join(rows[:6]) or "按测试设计数据要求准备"

    def _from_requirement(self, req: dict[str, Any], payload: dict[str, Any]) -> list[dict[str, Any]]:
        drafts = []
        functions = req.get("functions") or []
        requirements = req.get("requirements") or []
        if functions:
            for fn in functions:
                req_ids = [str(x) for x in (fn.get("sources") or []) if x]
                drafts.append({
                    "case_name": f"{fn.get('name') or '功能'} 正常路径",
                    "module": fn.get("module") or infer_module(fn.get("name") or ""),
                    "precondition": "；".join(fn.get("preconditions") or []) or "需求未给出前置条件",
                    "steps": [{"action": step, "data": "；".join(fn.get("inputs") or []), "expected": ""} for step in (fn.get("operations") or ["执行该功能"])],
                    "test_data": "；".join(fn.get("inputs") or []) or "需求缺失",
                    "expected_result": "；".join(fn.get("outputs") or []) or "需求未定义，待确认",
                    "priority": "P0",
                    "type": "functional",
                    "requirement_ids": req_ids,
                    "test_design_ids": [],
                    "test_scenario_ids": [],
                })
        for ex in req.get("exceptions") or []:
            if not ex.get("defined") and not ex.get("scenario"):
                continue
            drafts.append({
                "case_name": ex.get("scenario") or "异常场景",
                "module": infer_module(ex.get("scenario") or ""),
                "precondition": "按异常场景准备",
                "steps": [{"action": f"触发 {ex.get('scenario')}", "data": "", "expected": ex.get("requirement") or "需求未定义，待确认"}],
                "test_data": "按异常条件构造",
                "expected_result": ex.get("requirement") or "需求未定义，待确认",
                "priority": "P1" if ex.get("defined") else "P2",
                "type": "error" if "边界" not in (ex.get("scenario") or "") else "boundary",
                "requirement_ids": [str(x) for x in (ex.get("sources") or []) if x],
                "test_design_ids": [],
                "test_scenario_ids": [],
            })
        if not drafts and requirements:
            text = "\n".join(item.get("text") or "" for item in requirements)
            drafts = self._from_text(text, payload)
            for item, req_item in zip(drafts, requirements):
                item["requirement_ids"] = [req_item.get("id")] if req_item.get("id") else []
        return drafts

    def _from_text(self, text: str, payload: dict[str, Any], hint_name: str = "") -> list[dict[str, Any]]:
        module = payload.get("module") or infer_module(text or hint_name)
        drafts = build_professional_cases(module, text, case_types=payload.get("types") or None)
        for item in drafts:
            if item.get("test_data") in {None, "", "使用项目已有账号/接口数据"}:
                item["test_data"] = "按场景构造可区分的合法/非法输入；账号与环境在测试准备落实"
        extras = []
        mapping = (
            ("正常登录", "functional", "P0", ["打开登录页", "输入已注册账号和正确密码", "点击登录"], "进入首页，会话有效", "账号=test001；密码=正确密码"),
            ("错误密码", "error", "P1", ["打开登录页", "输入已存在账号和错误密码", "点击登录"], "提示密码错误，不进入系统", "账号=test001；密码=错误密码"),
            ("账号不存在", "error", "P1", ["打开登录页", "输入不存在的账号", "点击登录"], "提示账号不存在或登录失败，不泄露多余信息", "账号=missing_user；密码=任意"),
            ("账号锁定", "error", "P0", ["准备已锁定账号", "打开登录页", "输入锁定账号和正确密码", "点击登录"], "拒绝登录并提示账号锁定", "账号=locked_user；状态=locked"),
            ("验证码错误", "error", "P1", ["打开登录页", "输入账号密码和错误验证码", "提交"], "提示验证码错误，不进入系统", "验证码=错误值"),
            ("重复登录", "error", "P2", ["使用同一账号在已登录状态下再次登录"], "按需求处理多端/重复登录，需求未定义则标待确认", "账号=test001"),
        )
        for token, case_type, priority, steps, expected, data in mapping:
            if token in text and not any(token in (item.get("case_name") or "") for item in drafts + extras):
                extras.append({
                    "case_name": token,
                    "module": module,
                    "precondition": "被测登录服务可访问，测试账号按数据列准备",
                    "steps": [{"action": step, "data": data, "expected": ""} for step in steps],
                    "test_data": data,
                    "expected_result": expected,
                    "priority": priority,
                    "type": case_type,
                    "requirement_ids": [],
                    "test_design_ids": [],
                    "test_scenario_ids": [],
                })
        return drafts + extras

    def _workspace_task(self, user_id: int, project_id: int, name: str) -> dict[str, Any]:
        existing = self.tasks.list_tasks(user_id, project_id)
        for item in existing:
            if item.get("name") == "项目用例集":
                return item
        return self.tasks.create_task(user_id, project_id, "项目用例集", name, infer_module(name))

    def _save_cases(self, user_id: int, project_id: int, task_id: int, drafts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        existing = self.list_cases(user_id, project_id)
        start = len(existing)
        saved = []
        db = SessionLocal()
        try:
            task = self.tasks._get(db, user_id, project_id, task_id)
            point = self.tasks._ensure_point(db, user_id, task)
            for index, item in enumerate(drafts, start=1):
                row = TestCase(
                    user_id=user_id,
                    created_by=user_id,
                    project_id=project_id,
                    point_id=point.id,
                    case_name=(item.get("case_name") or "未命名用例")[:200],
                    priority=item.get("priority") or "P1",
                    type=item.get("type") or "functional",
                    status=item.get("status") or "draft",
                )
                db.add(row)
                db.flush()
                item["case_code"] = item.get("case_code") or f"TC-{start + index:04d}"
                self.tasks._apply_case(row, item, task_id, project_id)
                _write_meta(row, item)
                saved.append(serialize_workbench_case(row))
            db.commit()
            return saved
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _row(self, user_id: int, project_id: int, case_id: int, db=None) -> TestCase:
        own = db is None
        session = db or SessionLocal()
        try:
            row = session.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
            if not row or row.is_deleted:
                raise ValueError("用例不存在")
            return row
        finally:
            if own:
                session.close()
