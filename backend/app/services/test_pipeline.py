"""测试准备 → 执行 → 缺陷 → 验证 → 回归 → 报告。真实落库，不虚构执行结果。"""
from __future__ import annotations

import csv
import io
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.project_test_task import ProjectTestTask
from app.models.test_case import TestCase
from app.models.test_environment import TestEnvironment
from app.services.project_memory import ProjectMemoryService
from app.services.test_design_doc import TestDesignDocService

DOC = {
    "prep": ("test_prep", "测试准备"),
    "run": ("test_run", "测试执行"),
    "defect": ("defect", "缺陷管理"),
    "regression": ("regression", "回归测试"),
    "report": ("test_report", "测试报告"),
}
RUN_STATUSES = {"PASS", "FAIL", "BLOCKED", "SKIPPED", "NOT_EXECUTED"}
BUG_STATUSES = {
    "NEW", "ASSIGNED", "IN_PROGRESS", "FIXED", "REOPENED",
    "VERIFIED", "CLOSED", "REJECTED", "DUPLICATE",
}
CHECK_STATUSES = {"PASS", "FAIL", "UNKNOWN"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_id(items: list[dict[str, Any]], prefix: str, width: int = 4) -> str:
    highest = 0
    for item in items:
        match = re.search(rf"{re.escape(prefix)}-(\d+)", str(item.get("id") or ""))
        if match:
            highest = max(highest, int(match.group(1)))
    return f"{prefix}-{highest + 1:0{width}d}"


def _empty_prep() -> dict[str, Any]:
    return {
        "status": "empty",
        "datasets": [],
        "accounts": [],
        "env_checks": [],
        "dependencies": [],
        "issues": [],
        "updated_at": None,
    }


def _empty_runs() -> dict[str, Any]:
    return {"status": "empty", "batches": [], "updated_at": None}


def _empty_defects() -> dict[str, Any]:
    return {"status": "empty", "bugs": [], "updated_at": None}


def _empty_regs() -> dict[str, Any]:
    return {"status": "empty", "batches": [], "updated_at": None}


def _empty_reports() -> dict[str, Any]:
    return {"status": "empty", "reports": [], "updated_at": None}


def _purpose_of(case: dict[str, Any]) -> str:
    blob = f"{case.get('case_name') or ''} {case.get('scenario') or ''} {case.get('test_data') or ''}"
    mapping = (
        ("禁用", "禁用账号"),
        ("锁定", "锁定账号"),
        ("错误密码", "错误密码"),
        ("密码错误", "错误密码"),
        ("不存在", "不存在账号"),
        ("空", "空数据"),
        ("下架", "下架商品"),
        ("库存", "库存为 0 商品"),
        ("登录", "正常账号"),
        ("订单", "正常商品"),
    )
    for token, purpose in mapping:
        if token in blob:
            return purpose
    return (case.get("case_name") or case.get("scenario") or "用例数据")[:40]


def _infer_fields(purpose: str, index: int) -> list[dict[str, str]]:
    if "账号" in purpose or "密码" in purpose or "登录" in purpose:
        user = f"user_{index:04d}"
        if "不存在" in purpose:
            return [{"field": "username", "value": f"missing_{user}"}, {"field": "password", "value": "Wrong!234"}]
        if "错误密码" in purpose:
            return [{"field": "username", "value": user}, {"field": "password", "value": "bad_password"}]
        if "禁用" in purpose:
            return [{"field": "username", "value": f"disabled_{user}"}, {"field": "password", "value": "Test!234"}, {"field": "status", "value": "disabled"}]
        if "锁定" in purpose:
            return [{"field": "username", "value": f"locked_{user}"}, {"field": "password", "value": "Test!234"}, {"field": "status", "value": "locked"}]
        return [{"field": "username", "value": user}, {"field": "password", "value": "Test!234"}, {"field": "status", "value": "active"}]
    if "商品" in purpose or "订单" in purpose:
        sku = f"SKU-{index:04d}"
        if "下架" in purpose:
            return [{"field": "sku", "value": sku}, {"field": "status", "value": "off_shelf"}]
        if "库存" in purpose:
            return [{"field": "sku", "value": sku}, {"field": "stock", "value": "0"}]
        return [{"field": "sku", "value": sku}, {"field": "stock", "value": "10"}, {"field": "price", "value": "99.00"}]
    return [{"field": "payload", "value": f"{purpose}-{index:04d}"}]


def _http_check(url: str) -> tuple[str, str]:
    if not url or not str(url).strip():
        return "UNKNOWN", "未配置地址"
    target = str(url).strip()
    if not target.startswith(("http://", "https://")):
        return "UNKNOWN", "地址不是 http/https，未探测"
    try:
        req = urllib.request.Request(target, method="GET", headers={"User-Agent": "ui-automation-env-check"})
        with urllib.request.urlopen(req, timeout=4) as resp:
            code = getattr(resp, "status", 0) or 0
            if 200 <= code < 500:
                return "PASS", f"HTTP {code}"
            return "FAIL", f"HTTP {code}"
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return "PASS", f"HTTP {exc.code}（服务可达）"
        return "FAIL", f"HTTP {exc.code}"
    except Exception as exc:
        return "FAIL", str(exc)[:160]


class TestPipelineService:
    def __init__(self, memory: Optional[ProjectMemoryService] = None):
        self.memory = memory or ProjectMemoryService()
        self.designs = TestDesignDocService(self.memory)

    def list_cases(self, user_id: int, project_id: int) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            task_ids = [
                row.id for row in db.query(ProjectTestTask.id).filter(
                    ProjectTestTask.user_id == user_id,
                    ProjectTestTask.project_id == project_id,
                ).all()
            ]
            q = db.query(TestCase).filter(TestCase.user_id == user_id, TestCase.is_deleted == False)  # noqa: E712
            clauses = []
            if hasattr(TestCase, "project_id"):
                clauses.append(TestCase.project_id == project_id)
            if task_ids and hasattr(TestCase, "test_task_id"):
                clauses.append(TestCase.test_task_id.in_(task_ids))
            if clauses:
                from sqlalchemy import or_
                q = q.filter(or_(*clauses))
            rows = q.order_by(TestCase.id.asc()).all()
            from app.services.case_workbench import serialize_workbench_case
            return [serialize_workbench_case(row) for row in rows]
        finally:
            db.close()

    def _downstream_cases(self, user_id: int, project_id: int) -> list[dict[str, Any]]:
        cases = self.list_cases(user_id, project_id)
        approved = [item for item in cases if item.get("review_status") == "APPROVED"]
        return approved or cases

    def snapshot(self, user_id: int, project_id: int) -> dict[str, Any]:
        prep = self.get_prep(user_id, project_id)
        runs = self.get_runs(user_id, project_id)
        defects = self.get_defects(user_id, project_id)
        regs = self.get_regressions(user_id, project_id)
        reports = self.get_reports(user_id, project_id)
        cases = self.list_cases(user_id, project_id)
        return {
            "cases": len(cases),
            "prep": self._prep_summary(prep),
            "runs": self._run_summary(runs),
            "defects": self._bug_summary(defects),
            "regressions": self._reg_summary(regs),
            "reports": len(reports.get("reports") or []),
        }

    def get_prep(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self._load(user_id, project_id, "prep", _empty_prep)

    def get_runs(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self._load(user_id, project_id, "run", _empty_runs)

    def get_defects(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self._load(user_id, project_id, "defect", _empty_defects)

    def get_regressions(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self._load(user_id, project_id, "regression", _empty_regs)

    def get_reports(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self._load(user_id, project_id, "report", _empty_reports)

    def generate_data(self, user_id: int, project_id: int, count: int = 20) -> dict[str, Any]:
        count = max(1, min(int(count or 20), 500))
        cases = self._downstream_cases(user_id, project_id)
        if not cases:
            raise ValueError("还没有测试用例。请先在「测试用例」中生成或录入用例，再批量生成测试数据。")
        design = self.designs.get(user_id, project_id)
        prep = self.get_prep(user_id, project_id)
        created = []
        for index in range(1, count + 1):
            case = cases[(index - 1) % len(cases)]
            purpose = _purpose_of(case)
            data_id = _next_id(prep["datasets"] + created, "DATA")
            fields = _infer_fields(purpose, index)
            if case.get("test_data") and "DATA-" not in str(case.get("test_data")):
                fields.append({"field": "from_case", "value": str(case["test_data"])[:200]})
            row = {
                "id": data_id,
                "data_type": purpose,
                "fields": fields,
                "purpose": purpose,
                "case_id": case.get("id"),
                "case_code": case.get("case_code"),
                "scenario": case.get("scenario") or case.get("case_name"),
                "req_ids": self._req_ids_for_case(design, case),
                "td_ids": [],
                "created_at": _now(),
                "created_status": "generated",
                "provisioned": False,
                "note": "平台内生成的测试数据，尚未写入被测系统",
            }
            created.append(row)
        prep["datasets"].extend(created)
        self._link_cases_to_data(user_id, project_id, created)
        self._refresh_prep_status(prep)
        self._save(user_id, project_id, "prep", prep)
        return {"created": created, "count": len(created), "prep": prep}

    def generate_accounts(self, user_id: int, project_id: int, count: int = 10, roles: Optional[list[str]] = None) -> dict[str, Any]:
        count = max(1, min(int(count or 10), 200))
        if not roles:
            blob = " ".join(
                f"{item.get('precondition') or ''} {item.get('test_data') or ''} {item.get('case_name') or ''}"
                for item in self._downstream_cases(user_id, project_id)
            )
            guessed = []
            for token in ("管理员", "普通用户", "运营人员", "访客"):
                if token in blob:
                    guessed.append(token)
            roles = guessed or ["普通用户", "管理员", "运营人员", "访客"]
        roles = [item for item in roles if str(item).strip()]
        if not roles:
            roles = ["普通用户"]
        prep = self.get_prep(user_id, project_id)
        created = []
        for index in range(1, count + 1):
            role = roles[(index - 1) % len(roles)]
            acc_id = _next_id(prep["accounts"] + created, "ACC")
            created.append({
                "id": acc_id,
                "username": f"test_{re.sub(r'[^A-Za-z0-9]+', '_', role)}_{index:03d}",
                "password": f"Test!{index:04d}",
                "role": role,
                "status": "pending_create",
                "purpose": f"{role} 测试账号",
                "provisioned": False,
                "note": "待在实际系统中创建。平台没有把账号写入被测系统。",
                "created_at": _now(),
            })
        prep["accounts"].extend(created)
        self._refresh_prep_status(prep)
        self._save(user_id, project_id, "prep", prep)
        return {"created": created, "count": len(created), "prep": prep}

    def account_batch(self, user_id: int, project_id: int, ids: list[str], action: str) -> dict[str, Any]:
        prep = self.get_prep(user_id, project_id)
        wanted = set(ids or [])
        if not wanted:
            raise ValueError("请选择要处理的账号")
        mapping = {"enable": "enabled", "disable": "disabled", "recycle": "recycled"}
        if action not in mapping:
            raise ValueError("仅支持 enable / disable / recycle")
        changed = []
        kept = []
        for item in prep["accounts"]:
            if item.get("id") not in wanted:
                kept.append(item)
                continue
            if action == "recycle":
                item["status"] = "recycled"
                changed.append(item)
                continue
            item["status"] = mapping[action]
            item["note"] = f"仅更新准备清单状态为 {item['status']}，未操作真实系统"
            changed.append(item)
            kept.append(item)
        prep["accounts"] = kept
        self._refresh_prep_status(prep)
        self._save(user_id, project_id, "prep", prep)
        return {"changed": len(changed), "action": action, "prep": prep}

    def export_accounts(self, user_id: int, project_id: int) -> str:
        prep = self.get_prep(user_id, project_id)
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["id", "username", "password", "role", "status", "purpose", "note"])
        for item in prep.get("accounts") or []:
            writer.writerow([item.get("id"), item.get("username"), item.get("password"), item.get("role"), item.get("status"), item.get("purpose"), item.get("note")])
        return buf.getvalue()

    def check_environment(self, user_id: int, project_id: int) -> dict[str, Any]:
        prep = self.get_prep(user_id, project_id)
        design = self.designs.get(user_id, project_id)
        checks = []
        deps = []
        db = SessionLocal()
        try:
            envs = db.query(TestEnvironment).filter(
                TestEnvironment.project_id == project_id,
                TestEnvironment.is_deleted == False,  # noqa: E712
            ).all()
        finally:
            db.close()
        if not envs:
            checks.append({"item": "测试环境地址", "status": "UNKNOWN", "detail": "项目还没有配置测试环境"})
        for env in envs:
            for label, url in (("Web", getattr(env, "web_url", None) or env.base_url), ("API", getattr(env, "api_url", None))):
                status, detail = _http_check(url or "")
                checks.append({
                    "item": f"{env.display_name or env.name} {label}",
                    "status": status,
                    "detail": detail,
                    "url": url or "",
                })
                if url:
                    deps.append({"name": f"{env.name} {label}", "kind": "service", "ref": url})
        checks.append({
            "item": "测试数据",
            "status": "PASS" if prep.get("datasets") else "FAIL",
            "detail": f"已生成 {len(prep.get('datasets') or [])} 条" if prep.get("datasets") else "尚未生成测试数据",
        })
        checks.append({
            "item": "测试账号清单",
            "status": "PASS" if prep.get("accounts") else "UNKNOWN",
            "detail": f"清单 {len(prep.get('accounts') or [])} 个，均未写入真实系统" if prep.get("accounts") else "尚未生成账号清单",
        })
        checks.append({
            "item": "测试账号已在系统创建",
            "status": "UNKNOWN",
            "detail": "平台不能确认真实系统里是否已创建这些账号，不能记为 PASS",
        })
        checks.append({"item": "浏览器 / 设备", "status": "UNKNOWN", "detail": "未接入设备探测，不能记为 PASS"})
        checks.append({"item": "数据库依赖", "status": "UNKNOWN", "detail": "未配置或未探测数据库"})
        checks.append({"item": "第三方服务", "status": "UNKNOWN", "detail": "需求/设计未给出可探测地址" if not (design.get("environment") or []) else "仅记录设计中的依赖，未探测"})
        for item in design.get("environment") or []:
            deps.append({"name": item.get("item"), "kind": item.get("kind") or "dependency", "ref": item.get("note") or ""})
        prep["env_checks"] = checks
        prep["dependencies"] = deps
        self._refresh_prep_status(prep)
        self._save(user_id, project_id, "prep", prep)
        return prep

    def create_run_batch(self, user_id: int, project_id: int, case_ids: Optional[list[int]] = None, env: str = "") -> dict[str, Any]:
        cases = self.list_cases(user_id, project_id)
        if not cases:
            raise ValueError("还没有测试用例，无法创建执行批次")
        wanted = set(int(x) for x in (case_ids or []) if x)
        selected = [item for item in cases if not wanted or item.get("id") in wanted]
        if not wanted:
            approved = [item for item in selected if item.get("review_status") == "APPROVED"]
            selected = approved or selected
        if not selected:
            raise ValueError("没有选中可执行的测试用例")
        prep = self.get_prep(user_id, project_id)
        data_by_case = {}
        for row in prep.get("datasets") or []:
            data_by_case.setdefault(row.get("case_id"), row)
        runs = self.get_runs(user_id, project_id)
        batch_id = _next_id(runs["batches"], "EXEC-BATCH", 3)
        results = []
        for case in selected:
            data = data_by_case.get(case.get("id"))
            results.append({
                "id": _next_id(results, "EXEC"),
                "case_id": case.get("id"),
                "case_code": case.get("case_code"),
                "case_name": case.get("case_name"),
                "module": case.get("module"),
                "scenario": case.get("scenario"),
                "data_id": (data or {}).get("id"),
                "data": (data or {}).get("fields") or case.get("test_data") or "",
                "expected": case.get("expected_result") or "",
                "steps": case.get("steps") or [],
                "actual": "",
                "status": "NOT_EXECUTED",
                "executor": "",
                "executed_at": None,
                "env": env,
                "bug_id": None,
            })
        batch = {
            "id": batch_id,
            "created_at": _now(),
            "env": env,
            "status": "open",
            "results": results,
            "stats": self._stats([item["status"] for item in results]),
        }
        runs["batches"].insert(0, batch)
        runs["status"] = "draft"
        runs["updated_at"] = _now()
        self._save(user_id, project_id, "run", runs)
        return batch

    def record_results(
        self,
        user_id: int,
        project_id: int,
        batch_id: str,
        updates: list[dict[str, Any]],
        executor: str = "",
    ) -> dict[str, Any]:
        if not updates:
            raise ValueError("请选择要记录的执行结果")
        runs = self.get_runs(user_id, project_id)
        batch = self._find(runs["batches"], batch_id)
        if not batch:
            raise ValueError("执行批次不存在")
        by_id = {item.get("id"): item for item in updates}
        changed = 0
        for row in batch["results"]:
            patch = by_id.get(row["id"])
            if not patch:
                continue
            status = str(patch.get("status") or "").upper()
            if status not in RUN_STATUSES:
                raise ValueError(f"无效执行状态：{status}")
            if status in {"PASS", "FAIL"} and not str(patch.get("actual") or row.get("actual") or "").strip():
                raise ValueError(f"{row['id']} 标记 {status} 必须填写实际结果，不能由系统自动通过")
            row["status"] = status
            if patch.get("actual") is not None:
                row["actual"] = str(patch.get("actual") or "")
            row["executor"] = executor or row.get("executor") or "tester"
            row["executed_at"] = _now()
            changed += 1
        if changed == 0:
            raise ValueError("没有匹配到执行记录")
        batch["stats"] = self._stats([item["status"] for item in batch["results"]])
        if batch["stats"]["NOT_EXECUTED"] == 0:
            batch["status"] = "closed"
        runs["updated_at"] = _now()
        self._save(user_id, project_id, "run", runs)
        return batch

    def draft_bugs_from_fails(self, user_id: int, project_id: int, batch_id: Optional[str] = None) -> dict[str, Any]:
        runs = self.get_runs(user_id, project_id)
        batches = [self._find(runs["batches"], batch_id)] if batch_id else runs["batches"]
        batches = [item for item in batches if item]
        fails = []
        for batch in batches:
            for row in batch.get("results") or []:
                if row.get("status") == "FAIL":
                    fails.append((batch, row))
        if not fails:
            raise ValueError("没有 FAIL 的执行记录，不能凭空生成缺陷")
        defects = self.get_defects(user_id, project_id)
        created = []
        for batch, row in fails:
            if any(bug.get("exec_id") == row["id"] for bug in defects["bugs"]):
                continue
            dup = self._maybe_duplicate(defects["bugs"], row)
            bug_id = _next_id(defects["bugs"] + created, "BUG", 3)
            created.append({
                "id": bug_id,
                "title": f"{row.get('case_code') or ''} {row.get('case_name') or ''} 失败".strip(),
                "module": row.get("module") or "",
                "req_ids": [],
                "td_ids": [],
                "case_id": row.get("case_id"),
                "case_code": row.get("case_code"),
                "exec_id": row["id"],
                "batch_id": batch["id"],
                "env": row.get("env") or batch.get("env") or "",
                "precondition": "",
                "steps": row.get("steps") or [],
                "expected": row.get("expected") or "",
                "actual": row.get("actual") or "执行失败，待补充实际现象",
                "severity": "major",
                "priority": "P1",
                "assignee": "",
                "status": "NEW",
                "duplicate_of": dup,
                "attachments": [],
                "verifications": [],
                "draft": True,
                "created_at": _now(),
                "updated_at": _now(),
            })
            row["bug_id"] = bug_id
        defects["bugs"].extend(created)
        defects["status"] = "draft"
        defects["updated_at"] = _now()
        self._save(user_id, project_id, "defect", defects)
        self._save(user_id, project_id, "run", runs)
        return {"created": created, "count": len(created), "defects": defects}

    def submit_bug(self, user_id: int, project_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        defects = self.get_defects(user_id, project_id)
        bug_id = payload.get("id") or _next_id(defects["bugs"], "BUG", 3)
        existing = self._find(defects["bugs"], bug_id)
        row = existing or {"id": bug_id, "created_at": _now(), "verifications": [], "attachments": []}
        for key in ("title", "module", "env", "precondition", "expected", "actual", "severity", "priority", "assignee"):
            if key in payload:
                row[key] = payload[key]
        if "steps" in payload:
            row["steps"] = payload["steps"]
        row["case_id"] = payload.get("case_id") or row.get("case_id")
        row["case_code"] = payload.get("case_code") or row.get("case_code")
        row["exec_id"] = payload.get("exec_id") or row.get("exec_id")
        row["batch_id"] = payload.get("batch_id") or row.get("batch_id")
        row["req_ids"] = payload.get("req_ids") or row.get("req_ids") or []
        row["td_ids"] = payload.get("td_ids") or row.get("td_ids") or []
        if payload.get("status"):
            status = str(payload["status"]).upper()
            if status not in BUG_STATUSES:
                raise ValueError("无效缺陷状态")
            if status in {"VERIFIED", "CLOSED"} and not row.get("verifications"):
                raise ValueError("开发标记 FIXED 不等于验证通过。必须先做缺陷验证。")
            row["status"] = status
        else:
            row["status"] = row.get("status") or "NEW"
        row["draft"] = False
        row["updated_at"] = _now()
        if not existing:
            if not row.get("title") or not row.get("actual"):
                raise ValueError("提交缺陷需要标题和实际结果")
            defects["bugs"].append(row)
        defects["status"] = "open"
        defects["updated_at"] = _now()
        self._save(user_id, project_id, "defect", defects)
        return row

    def verify_bug(self, user_id: int, project_id: int, bug_id: str, result: str, actual: str, evidence: Optional[list] = None, executor: str = "") -> dict[str, Any]:
        defects = self.get_defects(user_id, project_id)
        bug = self._find(defects["bugs"], bug_id)
        if not bug:
            raise ValueError("缺陷不存在")
        status = str(result or "").upper()
        if status not in {"PASS", "FAIL"}:
            raise ValueError("验证结果只能是 PASS 或 FAIL")
        if not (actual or "").strip():
            raise ValueError("验证必须填写实际结果，不能只改状态")
        ver_id = _next_id(bug.get("verifications") or [], "VER", 3)
        record = {
            "id": ver_id,
            "result": status,
            "actual": actual.strip(),
            "evidence": evidence or [],
            "executor": executor or "tester",
            "verified_at": _now(),
            "data_id": None,
            "env": bug.get("env") or "",
            "steps": bug.get("steps") or [],
            "expected": bug.get("expected") or "",
        }
        bug.setdefault("verifications", []).append(record)
        bug["status"] = "VERIFIED" if status == "PASS" else "REOPENED"
        bug["updated_at"] = _now()
        if status == "PASS":
            record["note"] = "测试验证通过，不是开发自行关闭"
        defects["updated_at"] = _now()
        self._save(user_id, project_id, "defect", defects)
        return {"bug": bug, "verification": record}

    def recommend_regression(self, user_id: int, project_id: int, bug_ids: list[str]) -> dict[str, Any]:
        defects = self.get_defects(user_id, project_id)
        cases = self.list_cases(user_id, project_id)
        bugs = [item for item in defects["bugs"] if item.get("id") in set(bug_ids or [])]
        if not bugs:
            raise ValueError("请选择要回归的缺陷")
        modules = {str(item.get("module") or "") for item in bugs if item.get("module")}
        codes = {str(item.get("case_code") or "") for item in bugs}
        recommended = []
        seen = set()
        for case in cases:
            key = case.get("id")
            hit = case.get("case_code") in codes or (case.get("module") and case.get("module") in modules)
            if hit and key not in seen:
                seen.add(key)
                recommended.append(case)
        return {"bugs": [item["id"] for item in bugs], "cases": recommended, "reason": "按缺陷模块和原失败用例去重推荐，不扩大到无关功能"}

    def create_regression(self, user_id: int, project_id: int, bug_ids: list[str], version: str = "") -> dict[str, Any]:
        rec = self.recommend_regression(user_id, project_id, bug_ids)
        if not rec["cases"]:
            raise ValueError("没有可回归的测试用例")
        regs = self.get_regressions(user_id, project_id)
        batch_id = _next_id(regs["batches"], "REG", 3)
        results = []
        for case in rec["cases"]:
            results.append({
                "id": _next_id(results, "RE"),
                "case_id": case.get("id"),
                "case_code": case.get("case_code"),
                "case_name": case.get("case_name"),
                "module": case.get("module"),
                "status": "NOT_EXECUTED",
                "actual": "",
                "executed_at": None,
            })
        batch = {
            "id": batch_id,
            "reason": f"验证缺陷 {', '.join(rec['bugs'])}",
            "version": version or "",
            "bug_ids": rec["bugs"],
            "created_at": _now(),
            "results": results,
            "stats": self._stats([item["status"] for item in results]),
            "fix_verify": "UNKNOWN",
            "risk": "中",
        }
        regs["batches"].insert(0, batch)
        regs["status"] = "open"
        regs["updated_at"] = _now()
        self._save(user_id, project_id, "regression", regs)
        return batch

    def record_regression(self, user_id: int, project_id: int, batch_id: str, updates: list[dict[str, Any]]) -> dict[str, Any]:
        if not updates:
            raise ValueError("请选择要记录的回归结果")
        regs = self.get_regressions(user_id, project_id)
        batch = self._find(regs["batches"], batch_id)
        if not batch:
            raise ValueError("回归批次不存在")
        by_id = {item.get("id"): item for item in updates}
        for row in batch["results"]:
            patch = by_id.get(row["id"])
            if not patch:
                continue
            status = str(patch.get("status") or "").upper()
            if status not in RUN_STATUSES:
                raise ValueError(f"无效状态：{status}")
            if status in {"PASS", "FAIL"} and not str(patch.get("actual") or row.get("actual") or "").strip():
                raise ValueError(f"{row['id']} 标记 {status} 必须填写实际结果")
            row["status"] = status
            if patch.get("actual") is not None:
                row["actual"] = str(patch.get("actual") or "")
            row["executed_at"] = _now()
        batch["stats"] = self._stats([item["status"] for item in batch["results"]])
        fail = batch["stats"]["FAIL"]
        blocked = batch["stats"]["BLOCKED"]
        pending = batch["stats"]["NOT_EXECUTED"]
        if fail:
            batch["fix_verify"] = "FAIL"
            batch["risk"] = "高"
        elif pending:
            batch["fix_verify"] = "UNKNOWN"
            batch["risk"] = "中"
        elif blocked:
            batch["fix_verify"] = "UNKNOWN"
            batch["risk"] = "中"
        else:
            batch["fix_verify"] = "PASS"
            batch["risk"] = "低"
        regs["updated_at"] = _now()
        self._save(user_id, project_id, "regression", regs)
        return batch

    def generate_report(self, user_id: int, project_id: int) -> dict[str, Any]:
        cases = self.list_cases(user_id, project_id)
        prep = self.get_prep(user_id, project_id)
        runs = self.get_runs(user_id, project_id)
        defects = self.get_defects(user_id, project_id)
        regs = self.get_regressions(user_id, project_id)
        run_stats = self._run_summary(runs)
        bug_stats = self._bug_summary(defects)
        executed = int(run_stats.get("total") or 0) - int(run_stats.get("NOT_EXECUTED") or 0)
        run_stats["executed"] = executed
        run_stats["pass_rate_of_executed"] = round(100 * run_stats["PASS"] / executed, 1) if executed else None
        reports = self.get_reports(user_id, project_id)
        report_id = _next_id(reports["reports"], "RPT", 3)
        report = {
            "id": report_id,
            "created_at": _now(),
            "cases": len(cases),
            "prep": self._prep_summary(prep),
            "execution": run_stats,
            "defects": bug_stats,
            "regression": self._reg_summary(regs),
            "conclusion": self._report_conclusion(run_stats, bug_stats, prep),
            "honesty": [
                "未执行不计入通过",
                "UNKNOWN 环境检查不记为 PASS",
                "开发标记 FIXED 不等于测试验证通过",
                "没有真实执行时不能出具通过结论",
            ],
            "trace": {
                "prep_data": len(prep.get("datasets") or []),
                "prep_accounts": len(prep.get("accounts") or []),
                "batches": [item.get("id") for item in (runs.get("batches") or [])],
                "bugs": [item.get("id") for item in (defects.get("bugs") or [])],
                "regs": [item.get("id") for item in (regs.get("batches") or [])],
            },
        }
        reports["reports"].insert(0, report)
        reports["status"] = "ready"
        reports["updated_at"] = _now()
        self._save(user_id, project_id, "report", reports)
        return report

    def _load(self, user_id: int, project_id: int, key: str, factory) -> dict[str, Any]:
        kind, title = DOC[key]
        row = self.memory.get_by_title(user_id, project_id, kind, title) if hasattr(self.memory, "get_by_title") else None
        if not row:
            return factory()
        try:
            data = json.loads(row.get("content") or "")
            return data if isinstance(data, dict) else factory()
        except Exception:
            return factory()

    def _save(self, user_id: int, project_id: int, key: str, doc: dict[str, Any]) -> None:
        kind, title = DOC[key]
        workspace = "execute" if key != "prep" else "design"
        self.memory.remember(
            user_id, project_id, kind=kind, title=title,
            content=json.dumps(doc, ensure_ascii=False),
            workspace=workspace,
            extra={"status": doc.get("status"), "updated_at": doc.get("updated_at")},
        )

    def _link_cases_to_data(self, user_id: int, project_id: int, created: list[dict[str, Any]]) -> None:
        db = SessionLocal()
        try:
            for row in created:
                case_id = row.get("case_id")
                if not case_id:
                    continue
                case = db.query(TestCase).filter(TestCase.id == case_id, TestCase.user_id == user_id).first()
                if not case:
                    continue
                current = getattr(case, "test_data", None) or ""
                token = row["id"]
                if token not in current:
                    case.test_data = f"{current} | {token}".strip(" |") if current else token
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    def _req_ids_for_case(self, design: dict[str, Any], case: dict[str, Any]) -> list[str]:
        ids = [str(item) for item in (case.get("requirement_ids") or []) if item]
        blob = f"{case.get('case_name') or ''} {case.get('scenario') or ''} {case.get('module') or ''}"
        for item in design.get("objects") or []:
            if item.get("name") and item.get("name") in blob:
                ids.extend(item.get("req_ids") or [])
        return list(dict.fromkeys(ids))

    def _refresh_prep_status(self, prep: dict[str, Any]) -> None:
        issues = []
        for item in prep.get("env_checks") or []:
            if item.get("status") == "FAIL":
                issues.append(f"{item.get('item')} 检查失败：{item.get('detail')}")
            if item.get("status") == "UNKNOWN":
                issues.append(f"{item.get('item')} 未知：{item.get('detail')}")
        if not prep.get("datasets"):
            issues.append("还没有测试数据")
        prep["issues"] = issues
        checks = prep.get("env_checks") or []
        has_fail = any(item.get("status") == "FAIL" for item in checks)
        has_unknown = any(item.get("status") == "UNKNOWN" for item in checks)
        if prep.get("datasets") and checks and not has_fail and not has_unknown:
            prep["status"] = "ready"
        elif prep.get("datasets") or prep.get("accounts") or checks:
            prep["status"] = "partial"
        else:
            prep["status"] = "empty"
        prep["updated_at"] = _now()

    def _find(self, items: list[dict[str, Any]], item_id: str) -> Optional[dict[str, Any]]:
        return next((item for item in items if item.get("id") == item_id), None)

    def _stats(self, statuses: list[str]) -> dict[str, int]:
        out = {key: 0 for key in RUN_STATUSES}
        out["total"] = len(statuses)
        for status in statuses:
            out[status] = out.get(status, 0) + 1
        return out

    def _prep_summary(self, prep: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": prep.get("status"),
            "data": len(prep.get("datasets") or []),
            "accounts": len(prep.get("accounts") or []),
            "checks": len(prep.get("env_checks") or []),
            "issues": len(prep.get("issues") or []),
        }

    def _run_summary(self, runs: dict[str, Any]) -> dict[str, Any]:
        rows = []
        for batch in runs.get("batches") or []:
            rows.extend(item.get("status") for item in (batch.get("results") or []))
        stats = self._stats(rows)
        stats["batches"] = len(runs.get("batches") or [])
        return stats

    def _bug_summary(self, defects: dict[str, Any]) -> dict[str, Any]:
        bugs = defects.get("bugs") or []
        return {
            "total": len(bugs),
            "open": len([item for item in bugs if item.get("status") in {"NEW", "ASSIGNED", "IN_PROGRESS", "REOPENED", "FIXED"}]),
            "verified": len([item for item in bugs if item.get("status") in {"VERIFIED", "CLOSED"}]),
            "draft": len([item for item in bugs if item.get("draft")]),
        }

    def _reg_summary(self, regs: dict[str, Any]) -> dict[str, Any]:
        batches = regs.get("batches") or []
        rows = []
        for batch in batches:
            rows.extend(item.get("status") for item in (batch.get("results") or []))
        stats = self._stats(rows)
        stats["batches"] = len(batches)
        return stats

    def _maybe_duplicate(self, bugs: list[dict[str, Any]], row: dict[str, Any]) -> Optional[str]:
        title = (row.get("case_name") or "").strip()
        module = (row.get("module") or "").strip()
        for bug in bugs:
            if bug.get("status") in {"REJECTED", "DUPLICATE"}:
                continue
            if module and bug.get("module") == module and title and title in (bug.get("title") or ""):
                return bug.get("id")
        return None

    def _report_conclusion(self, run_stats: dict[str, Any], bug_stats: dict[str, Any], prep: dict[str, Any]) -> str:
        if not run_stats.get("total"):
            return "还没有真实执行记录，不能出具通过结论。"
        if run_stats.get("NOT_EXECUTED"):
            return f"仍有 {run_stats['NOT_EXECUTED']} 条未执行，报告只汇总已记录结果，不把未执行算作通过。"
        parts = [
            f"执行 {run_stats['total']}，PASS {run_stats['PASS']}，FAIL {run_stats['FAIL']}，BLOCKED {run_stats['BLOCKED']}，SKIPPED {run_stats['SKIPPED']}。",
            f"缺陷 {bug_stats['total']}，其中仍开放 {bug_stats['open']}，已验证 {bug_stats['verified']}。",
        ]
        if prep.get("issues"):
            parts.append(f"准备问题 {len(prep['issues'])} 项仍在清单中。")
        return "".join(parts)
