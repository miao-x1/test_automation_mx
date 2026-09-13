"""项目级「测试设计结果」：必须基于需求分析，不重新理解需求，不生成用例。"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from app.llm import get_gateway
from app.services.project_memory import ProjectMemoryService
from app.services.requirement_analysis_doc import (
    RequirementAnalysisDocService,
    parse_json_object,
    strip_agent_tags,
    _run_async,
)

DOC_TITLE = "测试设计"
DOC_KIND = "test_design"
DOC_WORKSPACE = "design"
PRIORITIES = {"P0", "P1", "P2", "P3"}
DIMENSIONS = {
    "normal", "exception", "boundary", "rule", "permission", "state",
    "data", "interaction", "dependency", "repeat", "concurrency", "regression",
}
DIMENSION_LABEL = {
    "normal": "正常",
    "exception": "异常",
    "boundary": "边界",
    "rule": "业务规则",
    "permission": "权限",
    "state": "状态",
    "data": "数据",
    "interaction": "交互",
    "dependency": "依赖异常",
    "repeat": "重复操作",
    "concurrency": "并发",
    "regression": "回归影响",
}

SYSTEM_PROMPT = """你是专业测试设计师，不是需求分析师，也不是用例编写器。

任务：读取已经完成的「结构化需求分析结果」，设计测试人员在执行之前需要的完整测试设计。
只回答「针对这些需求，应该怎么设计测试」，禁止重新解读或改写需求，禁止输出完整测试用例、脚本或执行任务。

硬性规则：
1. 只能使用给定的需求分析结果。禁止脱离该结果重新理解需求，禁止要求用户再贴一份 PRD。
2. 每一个测试对象 TD-xxx、场景 TS-xxx 必须带 req_ids，能追溯到 REQ-xxx / FN-xxx / BR-xxx。
3. 禁止扩大测试范围。out_of_scope 必须尊重需求分析的非范围。
4. 禁止编造需求里没有的业务规则、数值边界、状态、权限或字段约束。需求缺失处标 missing，场景预期写「需求未定义，待确认」。
5. 不是每个功能都要上齐所有测试维度。根据需求判断 applicable / not_applicable，并说明原因。
6. 简单功能（如修改头像）不要强行做复杂并发、安全、状态机设计。
7. 测试方法必须说明「为什么这个需求适合这种方法」，不要为了展示而堆砌方法。
8. 测试数据必须具体（正常/异常/边界/空/重复/非法/最大/最小/特殊）。需求没给具体值时写「需求缺失」，不要编造。
9. 不要连续提问。最多 1～3 个可跳过的、会影响设计结论的问题。
10. 只输出一个 JSON 对象，不要 Markdown。

JSON 结构：
{
  "scope": {
    "core": [{"item":"","req_ids":["REQ-001"],"reason":"本次需求范围内"}],
    "related": [{"item":"","req_ids":[],"reason":"受本次需求影响"}],
    "regression": [{"item":"","req_ids":[],"reason":"建议回归，不扩大范围"}],
    "out_of_scope": [{"item":"","req_ids":[],"reason":"需求分析已排除"}]
  },
  "objects": [{
    "id":"TD-001","module":"模块","name":"测试对象",
    "req_ids":["REQ-001"],"fn_ids":["FN-001"],"priority":"P0",
    "applicable":["normal","exception","boundary"],
    "not_applicable":[{"dimension":"concurrency","reason":"需求未涉及"}]
  }],
  "scenarios": [{
    "id":"TS-001","td_id":"TD-001","req_ids":["REQ-001"],
    "dimension":"normal|exception|boundary|rule|permission|state|data|interaction|dependency|repeat|concurrency|regression",
    "name":"场景名","precondition":"","steps":["步骤"],"data":"","expected":"",
    "priority":"P0","method":"场景法|等价类|边界值|决策表|状态迁移|错误推测|角色权限矩阵|正交组合|因果关系"
  }],
  "methods": [{
    "id":"TM-001","name":"边界值","why":"原文给出了明确区间",
    "applied_to":["TD-001"],"req_ids":["REQ-002"],"examples":["仅使用原文出现的值"]
  }],
  "flows": [{
    "id":"TF-001","name":"","req_ids":[],"steps":[],
    "data_pass":"节点间数据传递","state_changes":[],
    "fail_impact":"前一步失败对下一步的影响","exit_midway":"","reenter":"","rollback":"","recovery":""
  }],
  "states": [{
    "id":"ST-001","req_ids":[],
    "legal":[{"from":"","to":"","condition":""}],
    "illegal":[{"from":"","to":"","reason":""}],
    "allowed_ops":[],"denied_ops":[],"repeat":"","concurrency":""
  }],
  "permissions": [{
    "role":"","req_ids":[],
    "view":true,"create":false,"update":false,"delete":false,
    "data_scope":"","page":"","button":"","api":"",
    "overreach":["越权/直接访问URL/直接调接口，仅当需求涉及权限时"]
  }],
  "data": [{
    "id":"DD-001","object":"","field":"","req_ids":[],
    "normal":"","invalid":"","boundary":"","empty":"","duplicate":"",
    "illegal":"","min":"","max":"","special":"",
    "source":"需求分析明确|需求缺失"
  }],
  "environment": [{"item":"","kind":"env|dependency|account|data|third_party","req_ids":[],"note":""}],
  "priorities": [{"td_id":"TD-001","priority":"P0","reason":"","req_ids":[]}],
  "coverage": [{"req_id":"REQ-001","td_ids":["TD-001"],"ts_ids":["TS-001"],"covered":true,"gap":""}],
  "risks": [{"id":"RSK-001","level":"高|中|低","point":"","focus":"","td_ids":[],"req_ids":[]}],
  "gaps": [{"id":"GAP-001","problem":"","impact":"","need_confirm":"","req_ids":[]}],
  "questions": [{"id":"Q1","question":"","skippable":true}]
}

有业务流程才输出 flows；有状态才输出 states；有角色才输出 permissions。
questions 最多 3 条。
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_counts() -> dict[str, int]:
    return {
        "objects": 0,
        "scenarios": 0,
        "methods": 0,
        "data": 0,
        "open_questions": 0,
        "high_priority": 0,
    }


def empty_document() -> dict[str, Any]:
    return {
        "status": "empty",
        "requirement_status": "empty",
        "requirement_completeness": 0,
        "completeness": 0,
        "counts": empty_counts(),
        "interaction": {
            "mode": "empty",
            "summary": "还没有测试设计。请先完成需求分析，再基于结构化结果做设计。",
            "questions": [],
        },
        "scope": {"core": [], "related": [], "regression": [], "out_of_scope": []},
        "objects": [],
        "scenarios": [],
        "methods": [],
        "flows": [],
        "states": [],
        "permissions": [],
        "data": [],
        "environment": [],
        "priorities": [],
        "coverage": [],
        "risks": [],
        "gaps": [],
        "questions": [],
        "task_input": "",
        "user_notes": "",
        "answers": [],
        "llm_used": False,
        "llm_error": None,
        "updated_at": None,
        "confirmed_at": None,
    }


def compact_requirement(req: dict[str, Any]) -> dict[str, Any]:
    overview = req.get("overview") or {}

    def field(key: str) -> str:
        value = overview.get(key)
        if isinstance(value, dict):
            return str(value.get("text") or "").strip()
        return str(value or "").strip()

    return {
        "status": req.get("status"),
        "completeness": req.get("completeness"),
        "overview": {
            "name": field("name"),
            "goal": field("goal"),
            "users": field("users"),
            "in_scope": field("in_scope"),
            "out_of_scope": field("out_of_scope"),
        },
        "requirements": req.get("requirements") or [],
        "functions": [
            {
                "id": item.get("id"),
                "module": item.get("module"),
                "name": item.get("name"),
                "description": item.get("description"),
                "inputs": item.get("inputs") or [],
                "preconditions": item.get("preconditions") or [],
                "operations": item.get("operations") or [],
                "outputs": item.get("outputs") or [],
                "rules": item.get("rules") or [],
                "sources": item.get("sources") or [],
            }
            for item in (req.get("functions") or [])
        ],
        "rules": req.get("rules") or [],
        "roles": req.get("roles") or [],
        "flows": req.get("flows") or [],
        "data": req.get("data") or [],
        "exceptions": req.get("exceptions") or [],
        "gaps": req.get("gaps") or [],
        "ambiguities": req.get("ambiguities") or [],
        "risks": req.get("risks") or [],
        "test_focus": req.get("test_focus") or [],
        "exceptions": req.get("exceptions") or [],
    }


def compute_counts(doc: dict[str, Any]) -> dict[str, int]:
    gaps = [item for item in (doc.get("gaps") or []) if not item.get("resolved")]
    questions = (doc.get("interaction") or {}).get("questions") or doc.get("questions") or []
    return {
        "objects": len(doc.get("objects") or []),
        "scenarios": len(doc.get("scenarios") or []),
        "methods": len(doc.get("methods") or []),
        "data": len(doc.get("data") or []),
        "open_questions": len(gaps) + len(questions),
        "high_priority": len([item for item in (doc.get("objects") or []) if item.get("priority") == "P0"]),
    }


def compute_completeness(doc: dict[str, Any]) -> int:
    scope = doc.get("scope") or {}
    score = 0
    if scope.get("core") or scope.get("out_of_scope"):
        score += 15
    if doc.get("objects"):
        score += 20
    if doc.get("scenarios"):
        score += 20
    if doc.get("methods"):
        score += 8
    if doc.get("data"):
        score += 8
    if doc.get("coverage"):
        score += 10
    if doc.get("priorities") or any(item.get("priority") for item in (doc.get("objects") or [])):
        score += 7
    if "gaps" in doc:
        score += 6
    if doc.get("flows") or doc.get("states") or doc.get("permissions"):
        score += 6
    open_q = compute_counts(doc)["open_questions"]
    score -= min(16, open_q * 2)
    return max(0, min(100, score))


def interaction_of(doc: dict[str, Any]) -> dict[str, Any]:
    counts = compute_counts(doc)
    questions = []
    for item in (doc.get("questions") or [])[:3]:
        question = (item.get("question") if isinstance(item, dict) else str(item)).strip()
        if question:
            questions.append({
                "id": item.get("id") if isinstance(item, dict) else f"Q{len(questions) + 1}",
                "question": question,
                "skippable": True,
            })
    if not questions:
        for item in (doc.get("gaps") or [])[:3]:
            text = item.get("need_confirm") or item.get("problem") or ""
            if text:
                questions.append({"id": item.get("id") or f"Q{len(questions) + 1}", "question": text, "skippable": True})
    objects = counts["objects"]
    scenarios = counts["scenarios"]
    open_q = counts["open_questions"]
    if objects and scenarios and open_q == 0:
        mode = "complete"
        summary = f"已完成测试设计，共 {objects} 个测试对象、{scenarios} 个测试场景，均可追溯到需求分析。"
    elif open_q <= 3:
        mode = "few_gaps"
        summary = f"已完成测试设计，共 {objects} 个测试对象、{scenarios} 个测试场景。另有 {open_q} 个关键问题，补充后可以提高准确度，也可以跳过。"
    else:
        mode = "vague"
        summary = f"已基于现有需求分析完成初步测试设计，共 {objects} 个测试对象、{scenarios} 个测试场景。当前有 {open_q} 个缺口，补充后可以提高设计完整度。"
    return {"mode": mode, "summary": summary, "questions": questions[:3]}


def _overview_text(overview: dict[str, Any], key: str) -> str:
    value = (overview or {}).get(key)
    if isinstance(value, dict):
        return str(value.get("text") or "").strip()
    return str(value or "").strip()


def requirement_brief(req: Optional[dict[str, Any]]) -> dict[str, Any]:
    req = req or {}
    if req.get("status") == "empty" or (not req.get("requirements") and not req.get("functions")):
        return {
            "available": False,
            "status": req.get("status") or "empty",
            "completeness": req.get("completeness") or 0,
            "name": "",
            "goal": "",
            "users": "",
            "in_scope": "",
            "out_of_scope": "",
            "requirements": [],
            "modules": [],
            "functions": [],
            "rules": [],
            "roles": [],
            "exceptions": [],
            "gaps": [],
            "risks": [],
            "data_fields": 0,
            "counts": req.get("counts") or {},
        }
    overview = req.get("overview") or {}
    modules = []
    for item in req.get("functions") or []:
        name = str(item.get("module") or "").strip()
        if name and name not in modules:
            modules.append(name)
    return {
        "available": True,
        "status": req.get("status") or "draft",
        "completeness": req.get("completeness") or 0,
        "name": _overview_text(overview, "name") or "未命名需求",
        "goal": _overview_text(overview, "goal"),
        "users": _overview_text(overview, "users"),
        "in_scope": _overview_text(overview, "in_scope"),
        "out_of_scope": _overview_text(overview, "out_of_scope"),
        "requirements": [
            {"id": item.get("id"), "text": item.get("text") or ""}
            for item in (req.get("requirements") or []) if item.get("id") or item.get("text")
        ],
        "modules": modules,
        "functions": [
            {
                "id": item.get("id"),
                "module": item.get("module") or "",
                "name": item.get("name") or "",
                "description": item.get("description") or "",
                "sources": item.get("sources") or [],
            }
            for item in (req.get("functions") or [])
        ],
        "rules": [
            {"id": item.get("id"), "statement": item.get("statement") or "", "sources": item.get("sources") or []}
            for item in (req.get("rules") or []) if item.get("statement")
        ],
        "roles": [
            {"id": item.get("id"), "name": item.get("name"), "can": item.get("can") or [], "cannot": item.get("cannot") or []}
            for item in (req.get("roles") or []) if item.get("name")
        ],
        "exceptions": [
            {"scenario": item.get("scenario"), "defined": bool(item.get("defined")), "requirement": item.get("requirement") or ""}
            for item in (req.get("exceptions") or []) if item.get("scenario")
        ],
        "gaps": [
            {"problem": item.get("problem") or item.get("item") or "", "need_confirm": item.get("need_confirm") or ""}
            for item in (req.get("gaps") or [])
        ],
        "risks": [
            {"level": item.get("level") or "中", "point": item.get("point") or ""}
            for item in (req.get("risks") or []) if item.get("point")
        ],
        "data_fields": len(req.get("data") or []),
        "counts": req.get("counts") or {},
    }


def source_index(req: Optional[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    req = req or {}
    index: dict[str, dict[str, Any]] = {}
    for item in req.get("requirements") or []:
        rid = str(item.get("id") or "").strip()
        if rid:
            index[rid] = {"kind": "requirement", "id": rid, "title": rid, "text": item.get("text") or "", "module": ""}
    for item in req.get("functions") or []:
        fid = str(item.get("id") or "").strip()
        if fid:
            index[fid] = {
                "kind": "function", "id": fid,
                "title": item.get("name") or fid,
                "text": item.get("description") or "",
                "module": item.get("module") or "",
            }
    for item in req.get("rules") or []:
        bid = str(item.get("id") or "").strip()
        if bid:
            index[bid] = {"kind": "rule", "id": bid, "title": bid, "text": item.get("statement") or "", "module": item.get("category") or ""}
    for item in req.get("roles") or []:
        role_id = str(item.get("id") or item.get("name") or "").strip()
        if role_id:
            index[role_id] = {"kind": "role", "id": role_id, "title": item.get("name") or role_id, "text": "；".join(item.get("can") or []), "module": ""}
    return index


def build_plan(doc: dict[str, Any], req: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    brief = requirement_brief(req)
    dims: list[str] = []
    for item in doc.get("scenarios") or []:
        dim = item.get("dimension")
        if dim and dim not in dims:
            dims.append(dim)
    for item in doc.get("objects") or []:
        for dim in item.get("applicable") or []:
            if dim not in dims:
                dims.append(dim)
    methods = [item.get("name") for item in (doc.get("methods") or []) if item.get("name")]
    priorities = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
    for item in doc.get("objects") or []:
        key = item.get("priority") if item.get("priority") in PRIORITIES else "P1"
        priorities[key] = priorities.get(key, 0) + 1
    objects = len(doc.get("objects") or [])
    scenarios = len(doc.get("scenarios") or [])
    if not brief.get("available"):
        headline = "还没有需求分析结果。测试设计必须先承接第一阶段，不能重新描述需求。"
        ready = False
    elif objects == 0:
        headline = f"已承接「{brief['name']}」，共 {len(brief.get('requirements') or [])} 条需求。生成设计后会给出对象、场景、方法和覆盖。"
        ready = False
    else:
        headline = (
            f"基于「{brief['name']}」，准备从 {len(dims) or 1} 个方面测试，"
            f"形成 {objects} 个测试对象、{scenarios} 个测试场景。"
        )
        ready = True
    return {
        "headline": headline,
        "ready": ready,
        "name": brief.get("name") or "",
        "aspects": [DIMENSION_LABEL.get(item, item) for item in dims],
        "aspect_keys": dims,
        "objects": objects,
        "scenarios": scenarios,
        "methods": methods,
        "boundaries": [item.get("name") for item in (doc.get("scenarios") or []) if item.get("dimension") == "boundary"],
        "roles": [item.get("role") for item in (doc.get("permissions") or []) if item.get("role")],
        "states": [item.get("id") for item in (doc.get("states") or [])],
        "data_fields": len(doc.get("data") or []),
        "priorities": priorities,
        "next": "确认后作为「测试用例」生成输入。本阶段不产出完整测试用例。",
    }


def to_case_input(doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "test_design_case_input",
        "note": "这是测试设计方案，供下一阶段生成测试用例。不是完整测试用例。",
        "status": doc.get("status"),
        "scope": doc.get("scope") or {},
        "objects": [
            {
                "id": item.get("id"),
                "module": item.get("module"),
                "name": item.get("name"),
                "priority": item.get("priority"),
                "req_ids": item.get("req_ids") or [],
                "fn_ids": item.get("fn_ids") or [],
                "applicable": item.get("applicable") or [],
            }
            for item in (doc.get("objects") or [])
        ],
        "scenarios": [
            {
                "id": item.get("id"),
                "td_id": item.get("td_id"),
                "req_ids": item.get("req_ids") or [],
                "dimension": item.get("dimension"),
                "name": item.get("name"),
                "precondition": item.get("precondition"),
                "steps": item.get("steps") or [],
                "data": item.get("data"),
                "expected": item.get("expected"),
                "priority": item.get("priority"),
                "method": item.get("method"),
            }
            for item in (doc.get("scenarios") or [])
        ],
        "data": doc.get("data") or [],
        "permissions": doc.get("permissions") or [],
        "gaps": [item for item in (doc.get("gaps") or []) if not item.get("resolved")],
    }


def attach_workbench(doc: dict[str, Any], req: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    req = req or {}
    doc["requirement_brief"] = requirement_brief(req)
    doc["source_index"] = source_index(req)
    doc["plan"] = build_plan(doc, req)
    doc["case_input"] = to_case_input(doc)
    doc["task_input"] = to_task_input(doc)
    return doc


def to_task_input(doc: dict[str, Any]) -> str:
    if not doc or doc.get("status") in {None, "empty"}:
        return ""
    lines = [
        "【已确认的测试设计，供测试用例生成使用，不是完整测试用例】",
        f"测试对象 {len(doc.get('objects') or [])} 个，场景 {len(doc.get('scenarios') or [])} 个。",
        "",
        "范围：",
    ]
    for item in ((doc.get("scope") or {}).get("core") or []):
        lines.append(f"- 核心：{item.get('item')} 来源:{','.join(item.get('req_ids') or [])}")
    for item in ((doc.get("scope") or {}).get("out_of_scope") or []):
        lines.append(f"- 不在范围：{item.get('item')}")
    lines.append("")
    lines.append("测试对象：")
    for item in doc.get("objects") or []:
        lines.append(
            f"- {item.get('id')} {item.get('module')}/{item.get('name')} "
            f"优先级:{item.get('priority')} 需求:{','.join(item.get('req_ids') or [])}"
        )
    lines.append("")
    lines.append("测试场景：")
    for item in doc.get("scenarios") or []:
        lines.append(
            f"- {item.get('id')} [{DIMENSION_LABEL.get(item.get('dimension') or '', item.get('dimension'))}] "
            f"{item.get('name')} → {item.get('td_id')} 需求:{','.join(item.get('req_ids') or [])}"
        )
    lines.append("")
    lines.append("测试数据：")
    for item in doc.get("data") or []:
        lines.append(f"- {item.get('object')}.{item.get('field')} 正常:{item.get('normal') or '需求缺失'} 边界:{item.get('boundary') or '需求缺失'}")
    lines.append("")
    lines.append("待确认：")
    for item in doc.get("gaps") or []:
        if not item.get("resolved"):
            lines.append(f"- {item.get('problem')} → {item.get('need_confirm')}")
    return "\n".join(lines).strip()


def _as_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    return [value] if value else []


def _scope_items(items: Any) -> list[dict[str, Any]]:
    out = []
    for item in items or []:
        if isinstance(item, str):
            text = item.strip()
            if text:
                out.append({"item": text, "req_ids": [], "reason": ""})
            continue
        if not isinstance(item, dict):
            continue
        text = str(item.get("item") or item.get("name") or "").strip()
        if not text:
            continue
        out.append({
            "item": text,
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "reason": str(item.get("reason") or ""),
        })
    return out


def normalize_document(raw: dict[str, Any], requirement: Optional[dict[str, Any]] = None, previous: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    doc = empty_document()
    prev = previous or {}
    req = requirement or {}
    doc["requirement_status"] = req.get("status") or prev.get("requirement_status") or "empty"
    doc["requirement_completeness"] = req.get("completeness") or prev.get("requirement_completeness") or 0
    doc["user_notes"] = raw.get("user_notes") if raw.get("user_notes") is not None else prev.get("user_notes") or ""
    doc["answers"] = raw.get("answers") or prev.get("answers") or []
    scope = raw.get("scope") if isinstance(raw.get("scope"), dict) else {}
    doc["scope"] = {
        "core": _scope_items(scope.get("core")),
        "related": _scope_items(scope.get("related")),
        "regression": _scope_items(scope.get("regression")),
        "out_of_scope": _scope_items(scope.get("out_of_scope")),
    }
    objects = []
    for index, item in enumerate(raw.get("objects") or [], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        tid = str(item.get("id") or f"TD-{index:03d}")
        if not tid.startswith("TD-"):
            tid = f"TD-{index:03d}"
        applicable = [d for d in _as_list(item.get("applicable")) if d in DIMENSIONS]
        not_app = []
        for row in item.get("not_applicable") or []:
            if isinstance(row, dict) and row.get("dimension"):
                not_app.append({"dimension": row.get("dimension"), "reason": row.get("reason") or "需求未涉及"})
            elif isinstance(row, str):
                not_app.append({"dimension": row, "reason": "需求未涉及"})
        priority = item.get("priority") if item.get("priority") in PRIORITIES else "P1"
        objects.append({
            "id": tid,
            "module": str(item.get("module") or ""),
            "name": name,
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "fn_ids": [str(x) for x in _as_list(item.get("fn_ids")) if x],
            "priority": priority,
            "applicable": applicable or ["normal", "exception"],
            "not_applicable": not_app,
        })
    doc["objects"] = objects
    object_ids = {item["id"] for item in objects}
    scenarios = []
    for index, item in enumerate(raw.get("scenarios") or [], start=1):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        sid = str(item.get("id") or f"TS-{index:03d}")
        if not sid.startswith("TS-"):
            sid = f"TS-{index:03d}"
        td_id = str(item.get("td_id") or "")
        if td_id and td_id not in object_ids and objects:
            td_id = objects[0]["id"]
        dimension = item.get("dimension") if item.get("dimension") in DIMENSIONS else "normal"
        scenarios.append({
            "id": sid,
            "td_id": td_id,
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "dimension": dimension,
            "name": name,
            "precondition": str(item.get("precondition") or ""),
            "steps": [str(x) for x in _as_list(item.get("steps")) if x],
            "data": str(item.get("data") or ""),
            "expected": str(item.get("expected") or "需求未定义，待确认"),
            "priority": item.get("priority") if item.get("priority") in PRIORITIES else "P1",
            "method": str(item.get("method") or ""),
        })
    doc["scenarios"] = scenarios
    methods = []
    for index, item in enumerate(raw.get("methods") or [], start=1):
        if not isinstance(item, dict) or not item.get("name"):
            continue
        methods.append({
            "id": str(item.get("id") or f"TM-{index:03d}"),
            "name": str(item.get("name")),
            "why": str(item.get("why") or ""),
            "applied_to": [str(x) for x in _as_list(item.get("applied_to")) if x],
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "examples": [str(x) for x in _as_list(item.get("examples")) if x],
        })
    doc["methods"] = methods
    flows = []
    for index, item in enumerate(raw.get("flows") or [], start=1):
        if not isinstance(item, dict):
            continue
        flows.append({
            "id": str(item.get("id") or f"TF-{index:03d}"),
            "name": str(item.get("name") or f"流程{index}"),
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "steps": [str(x) for x in _as_list(item.get("steps")) if x],
            "data_pass": str(item.get("data_pass") or ""),
            "state_changes": _as_list(item.get("state_changes")),
            "fail_impact": str(item.get("fail_impact") or ""),
            "exit_midway": str(item.get("exit_midway") or ""),
            "reenter": str(item.get("reenter") or ""),
            "rollback": str(item.get("rollback") or ""),
            "recovery": str(item.get("recovery") or ""),
        })
    doc["flows"] = flows
    states = []
    for index, item in enumerate(raw.get("states") or [], start=1):
        if not isinstance(item, dict):
            continue
        states.append({
            "id": str(item.get("id") or f"ST-{index:03d}"),
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "legal": [row for row in (item.get("legal") or []) if isinstance(row, dict)],
            "illegal": [row for row in (item.get("illegal") or []) if isinstance(row, dict)],
            "allowed_ops": _as_list(item.get("allowed_ops")),
            "denied_ops": _as_list(item.get("denied_ops")),
            "repeat": str(item.get("repeat") or ""),
            "concurrency": str(item.get("concurrency") or ""),
        })
    doc["states"] = states
    permissions = []
    for item in raw.get("permissions") or []:
        if not isinstance(item, dict) or not item.get("role"):
            continue
        permissions.append({
            "role": str(item.get("role")),
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "view": bool(item.get("view")),
            "create": bool(item.get("create")),
            "update": bool(item.get("update")),
            "delete": bool(item.get("delete")),
            "data_scope": str(item.get("data_scope") or "需求缺失"),
            "page": str(item.get("page") or ""),
            "button": str(item.get("button") or ""),
            "api": str(item.get("api") or ""),
            "overreach": [str(x) for x in _as_list(item.get("overreach")) if x],
        })
    doc["permissions"] = permissions
    data_rows = []
    for index, item in enumerate(raw.get("data") or [], start=1):
        if not isinstance(item, dict):
            continue
        if not item.get("object") and not item.get("field"):
            continue
        row = {
            "id": str(item.get("id") or f"DD-{index:03d}"),
            "object": str(item.get("object") or ""),
            "field": str(item.get("field") or ""),
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            "source": str(item.get("source") or "需求缺失"),
        }
        for key in ("normal", "invalid", "boundary", "empty", "duplicate", "illegal", "min", "max", "special"):
            value = str(item.get(key) or "").strip()
            row[key] = value or "需求缺失"
        data_rows.append(row)
    doc["data"] = data_rows
    environment = []
    for item in raw.get("environment") or []:
        if isinstance(item, dict) and item.get("item"):
            environment.append({
                "item": str(item.get("item")),
                "kind": str(item.get("kind") or "env"),
                "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
                "note": str(item.get("note") or ""),
            })
    doc["environment"] = environment
    priorities = []
    for item in raw.get("priorities") or []:
        if isinstance(item, dict) and item.get("td_id"):
            priorities.append({
                "td_id": str(item.get("td_id")),
                "priority": item.get("priority") if item.get("priority") in PRIORITIES else "P1",
                "reason": str(item.get("reason") or ""),
                "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
            })
    doc["priorities"] = priorities
    coverage = []
    seen_req = set()
    for item in raw.get("coverage") or []:
        if isinstance(item, dict) and item.get("req_id"):
            rid = str(item.get("req_id"))
            seen_req.add(rid)
            coverage.append({
                "req_id": rid,
                "td_ids": [str(x) for x in _as_list(item.get("td_ids")) if x],
                "ts_ids": [str(x) for x in _as_list(item.get("ts_ids")) if x],
                "covered": bool(item.get("covered") or item.get("td_ids") or item.get("ts_ids")),
                "gap": str(item.get("gap") or ""),
            })
    for item in req.get("requirements") or []:
        rid = str(item.get("id") or "").strip()
        if not rid or rid in seen_req:
            continue
        td_ids = [row["id"] for row in objects if rid in (row.get("req_ids") or [])]
        ts_ids = [row["id"] for row in scenarios if rid in (row.get("req_ids") or [])]
        coverage.append({
            "req_id": rid,
            "td_ids": td_ids,
            "ts_ids": ts_ids,
            "covered": bool(td_ids or ts_ids),
            "gap": "" if (td_ids or ts_ids) else "尚未对应测试对象或场景",
        })
    doc["coverage"] = coverage
    risks = []
    for index, item in enumerate(raw.get("risks") or [], start=1):
        if not isinstance(item, dict) or not item.get("point"):
            continue
        level = item.get("level") or "中"
        risks.append({
            "id": str(item.get("id") or f"RSK-{index:03d}"),
            "level": level if level in {"高", "中", "低"} else "中",
            "point": str(item.get("point")),
            "focus": str(item.get("focus") or ""),
            "td_ids": [str(x) for x in _as_list(item.get("td_ids")) if x],
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
        })
    doc["risks"] = risks
    gaps = []
    for index, item in enumerate(raw.get("gaps") or [], start=1):
        if not isinstance(item, dict) or not item.get("problem"):
            continue
        gaps.append({
            "id": str(item.get("id") or f"GAP-{index:03d}"),
            "problem": str(item.get("problem")),
            "impact": str(item.get("impact") or ""),
            "need_confirm": str(item.get("need_confirm") or ""),
            "req_ids": [str(x) for x in _as_list(item.get("req_ids")) if x],
        })
    doc["gaps"] = gaps
    doc["questions"] = raw.get("questions") or []
    doc["interaction"] = interaction_of(doc)
    doc["counts"] = compute_counts(doc)
    doc["completeness"] = compute_completeness(doc)
    doc["task_input"] = to_task_input(doc)
    attach_workbench(doc, req)
    doc["llm_used"] = bool(raw.get("llm_used"))
    doc["llm_error"] = raw.get("llm_error")
    doc["status"] = raw.get("status") or prev.get("status") or "draft"
    if doc["status"] not in {"empty", "draft", "confirmed"}:
        doc["status"] = "draft"
    doc["updated_at"] = raw.get("updated_at") or _now()
    doc["confirmed_at"] = raw.get("confirmed_at") or prev.get("confirmed_at")
    return doc


def fallback_from_requirement(req: dict[str, Any], reason: str) -> dict[str, Any]:
    functions = req.get("functions") or []
    requirements = req.get("requirements") or []
    overview = req.get("overview") or {}
    objects = []
    scenarios = []
    coverage = []
    for index, fn in enumerate(functions, start=1):
        tid = f"TD-{index:03d}"
        req_ids = [str(x) for x in (fn.get("sources") or []) if x]
        if not req_ids and requirements:
            req_ids = [requirements[min(index - 1, len(requirements) - 1)].get("id")]
        objects.append({
            "id": tid,
            "module": fn.get("module") or "",
            "name": fn.get("name") or fn.get("description") or f"功能{index}",
            "req_ids": req_ids,
            "fn_ids": [fn.get("id")] if fn.get("id") else [],
            "priority": "P0" if index == 1 else "P1",
            "applicable": ["normal", "exception", "boundary"],
            "not_applicable": [{"dimension": "concurrency", "reason": "需求未明确涉及，不扩大设计"}],
        })
        scenarios.append({
            "id": f"TS-{len(scenarios) + 1:03d}",
            "td_id": tid,
            "req_ids": req_ids,
            "dimension": "normal",
            "name": f"{fn.get('name') or '功能'} 正常路径",
            "precondition": "；".join(fn.get("preconditions") or []) or "需求缺失",
            "steps": fn.get("operations") or [],
            "data": "；".join(fn.get("inputs") or []) or "需求缺失",
            "expected": "；".join(fn.get("outputs") or []) or "需求未定义，待确认",
            "priority": "P0",
            "method": "场景法",
        })
        for ex in req.get("exceptions") or []:
            if not ex.get("defined"):
                continue
            scenarios.append({
                "id": f"TS-{len(scenarios) + 1:03d}",
                "td_id": tid,
                "req_ids": req_ids,
                "dimension": "exception",
                "name": f"{ex.get('scenario')}（需求已定义）",
                "precondition": "",
                "steps": [],
                "data": "",
                "expected": ex.get("requirement") or "按需求已定义处理",
                "priority": "P1",
                "method": "错误推测",
            })
        coverage.append({
            "req_id": (req_ids or [f"REQ-{index:03d}"])[0],
            "td_ids": [tid],
            "ts_ids": [item["id"] for item in scenarios if item.get("td_id") == tid],
            "covered": True,
            "gap": "",
        })
    if not objects and requirements:
        for index, item in enumerate(requirements[:20], start=1):
            tid = f"TD-{index:03d}"
            objects.append({
                "id": tid,
                "module": "",
                "name": (item.get("text") or "")[:40] or item.get("id"),
                "req_ids": [item.get("id")],
                "fn_ids": [],
                "priority": "P1",
                "applicable": ["normal"],
                "not_applicable": [],
            })
            scenarios.append({
                "id": f"TS-{index:03d}",
                "td_id": tid,
                "req_ids": [item.get("id")],
                "dimension": "normal",
                "name": (item.get("text") or "")[:40],
                "expected": "需求未定义，待确认",
                "priority": "P1",
                "method": "场景法",
            })
            coverage.append({"req_id": item.get("id"), "td_ids": [tid], "ts_ids": [f"TS-{index:03d}"], "covered": True, "gap": ""})
    in_scope = overview.get("in_scope")
    out_scope = overview.get("out_of_scope")
    in_text = in_scope.get("text") if isinstance(in_scope, dict) else str(in_scope or "")
    out_text = out_scope.get("text") if isinstance(out_scope, dict) else str(out_scope or "")
    data_rows = []
    for index, item in enumerate(req.get("data") or [], start=1):
        data_rows.append({
            "object": item.get("object"),
            "field": item.get("field"),
            "req_ids": item.get("sources") or [],
            "normal": "需求缺失" if (item.get("type") in {None, "", "需求缺失"}) else "按需求已给类型构造",
            "source": "需求分析",
        })
    permissions = []
    for role in req.get("roles") or []:
        permissions.append({
            "role": role.get("name"),
            "req_ids": role.get("sources") or [],
            "view": "查看" in " ".join(role.get("can") or []) or True,
            "create": any("新增" in x or "创建" in x for x in (role.get("can") or [])),
            "update": any("修改" in x or "编辑" in x for x in (role.get("can") or [])),
            "delete": any("删除" in x for x in (role.get("can") or [])),
            "data_scope": role.get("data_scope") or "需求缺失",
            "overreach": ["越权访问待需求确认"] if (role.get("cannot") or role.get("evidence_kind") == "missing") else [],
        })
    raw = {
        "scope": {
            "core": [{"item": item["name"], "req_ids": item["req_ids"], "reason": "来自需求分析功能拆解"} for item in objects],
            "related": [],
            "regression": [],
            "out_of_scope": [{"item": out_text, "req_ids": [], "reason": "需求分析已排除"}] if out_text else [],
        },
        "objects": objects,
        "scenarios": scenarios,
        "methods": [{
            "name": "场景法",
            "why": "当前仅完成基于需求功能的诚实拆解，未编造额外测试方法",
            "applied_to": [item["id"] for item in objects[:3]],
            "req_ids": [],
            "examples": [],
        }] if objects else [],
        "flows": [
            {
                "name": item.get("name"),
                "req_ids": item.get("sources") or [],
                "steps": item.get("steps") or [],
                "data_pass": "需求未说明节点数据传递" if not item.get("steps") else "",
            }
            for item in (req.get("flows") or [])
        ],
        "states": [],
        "permissions": permissions,
        "data": data_rows,
        "environment": [],
        "priorities": [{"td_id": item["id"], "priority": item["priority"], "reason": "按功能顺序初排", "req_ids": item["req_ids"]} for item in objects],
        "coverage": coverage,
        "risks": [
            {"point": item.get("point"), "level": item.get("level"), "focus": item.get("focus"), "req_ids": item.get("sources") or []}
            for item in (req.get("risks") or []) if item.get("point")
        ],
        "gaps": (req.get("gaps") or []) + [{
            "problem": "模型未能完成完整测试设计",
            "impact": "场景维度可能不完整，但不编造需求外规则",
            "need_confirm": reason,
            "req_ids": [],
        }],
        "questions": [{"id": "Q1", "question": "是否按当前需求分析确认测试范围后重新设计？", "skippable": True}],
        "llm_used": False,
        "llm_error": reason,
        "status": "draft",
    }
    if in_text and not raw["scope"]["core"]:
        raw["scope"]["core"] = [{"item": in_text, "req_ids": [], "reason": "需求分析范围"}]
    return normalize_document(raw, req)


class TestDesignDocService:
    def __init__(self, memory: Optional[ProjectMemoryService] = None, requirements: Optional[RequirementAnalysisDocService] = None):
        self.memory = memory or ProjectMemoryService()
        self.requirements = requirements or RequirementAnalysisDocService(self.memory)

    def requirement_of(self, user_id: int, project_id: int) -> dict[str, Any]:
        return self.requirements.get(user_id, project_id)

    def get(self, user_id: int, project_id: int) -> dict[str, Any]:
        row = None
        if hasattr(self.memory, "get_by_title"):
            row = self.memory.get_by_title(user_id, project_id, DOC_KIND, DOC_TITLE)
        if not row:
            return attach_workbench(empty_document(), self.requirement_of(user_id, project_id))
        try:
            raw = json.loads(row.get("content") or "")
            if not isinstance(raw, dict):
                return empty_document()
        except Exception:
            return empty_document()
        req = self.requirement_of(user_id, project_id)
        doc = normalize_document(raw, req, raw)
        extra = row.get("extra") or {}
        if extra.get("status"):
            doc["status"] = extra["status"]
        if extra.get("confirmed_at"):
            doc["confirmed_at"] = extra["confirmed_at"]
        doc["updated_at"] = row.get("updated_at") or doc.get("updated_at")
        return attach_workbench(doc, req)

    def design(self, user_id: int, project_id: int, answers: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        req = self.requirement_of(user_id, project_id)
        if req.get("status") == "empty" or (not req.get("requirements") and not req.get("functions")):
            raise ValueError("请先完成需求分析。测试设计必须读取第一阶段的结构化结果，不能重新理解需求。")
        previous = self.get(user_id, project_id)
        try:
            raw = self._design_with_llm(req, answers=answers)
            raw["llm_used"] = True
            raw["llm_error"] = None
            raw["answers"] = answers or previous.get("answers") or []
            raw["status"] = "draft"
            doc = normalize_document(raw, req, previous)
        except Exception as exc:
            doc = fallback_from_requirement(req, str(exc))
            doc["answers"] = answers or previous.get("answers") or []
        self._save(user_id, project_id, doc)
        return doc

    def save_edits(self, user_id: int, project_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        current = self.get(user_id, project_id)
        if current.get("status") == "empty" and not current.get("objects"):
            raise ValueError("还没有可修改的测试设计")
        merged = dict(current)
        for key in ("scope", "objects", "scenarios", "methods", "flows", "states", "permissions", "data", "environment", "priorities", "coverage", "risks", "gaps", "questions", "user_notes", "answers"):
            if key in patch:
                merged[key] = patch[key]
        merged["status"] = "draft" if merged.get("status") == "empty" else merged.get("status") or "draft"
        if merged["status"] != "confirmed":
            merged["confirmed_at"] = None
        req = self.requirement_of(user_id, project_id)
        doc = normalize_document(merged, req, current)
        self._save(user_id, project_id, doc)
        return doc

    def confirm(self, user_id: int, project_id: int) -> dict[str, Any]:
        current = self.get(user_id, project_id)
        if current.get("status") == "empty" or not current.get("objects"):
            raise ValueError("请先完成测试设计再确认")
        current["status"] = "confirmed"
        current["confirmed_at"] = _now()
        req = self.requirement_of(user_id, project_id)
        doc = normalize_document(current, req, current)
        self._save(user_id, project_id, doc)
        self.memory.remember(
            user_id, project_id,
            kind="test_design",
            title="测试设计（已确认）",
            content=doc["task_input"],
            workspace=DOC_WORKSPACE,
            extra={"from": "test_design", "completeness": doc["completeness"]},
        )
        self.memory.remember(
            user_id, project_id,
            kind="confirmed",
            title="测试设计已确认",
            content=doc["interaction"]["summary"],
            workspace=DOC_WORKSPACE,
            extra={"completeness": doc["completeness"], "counts": doc["counts"]},
        )
        return doc

    def design_from_question(self, user_id: int, project_id: int, question: str) -> dict[str, Any]:
        strip_agent_tags(question)
        return self.design(user_id, project_id)

    def _save(self, user_id: int, project_id: int, doc: dict[str, Any]) -> None:
        self.memory.remember(
            user_id, project_id,
            kind=DOC_KIND,
            title=DOC_TITLE,
            content=json.dumps(doc, ensure_ascii=False),
            workspace=DOC_WORKSPACE,
            extra={
                "status": doc.get("status"),
                "completeness": doc.get("completeness"),
                "counts": doc.get("counts"),
                "confirmed_at": doc.get("confirmed_at"),
            },
        )

    def _design_with_llm(self, req: dict[str, Any], answers: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
        packed = compact_requirement(req)
        extra = ""
        if answers:
            extra = "\n".join(
                f"用户补充 {item.get('id') or ''}：{item.get('answer') or ''}"
                for item in answers if item.get("answer")
            )
        user_prompt = (
            "下面是第一阶段已经产出的结构化需求分析结果。请只基于它做测试设计，不要重新分析需求。\n\n"
            f"{json.dumps(packed, ensure_ascii=False)[:40000]}"
        )
        if extra:
            user_prompt += f"\n\n【用户补充】\n{extra}"

        async def _call() -> str:
            gateway = get_gateway()
            return await gateway.chat(
                agent_name="test_design",
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=8192,
                timeout=120,
            )

        content = _run_async(_call())
        return parse_json_object(content)
