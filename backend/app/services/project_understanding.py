"""把代码索引编译成项目理解知识，供页面 / 功能 / 模块 / 接口 / 流程 / 测试关联使用。"""
from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any, Optional

from app.db.database import SessionLocal
from app.models.project_explorer import ProjectCodeIndex, ProjectSource
from app.models.team import Project

ANALYSIS_STEPS = [
    ("structure", "项目结构"),
    ("stack", "技术栈"),
    ("frontend", "前端页面"),
    ("api", "API"),
    ("components", "组件"),
    ("elements", "页面元素"),
    ("code", "代码关系"),
    ("modules", "模块关系"),
    ("flows", "业务流程"),
    ("tests", "测试关联"),
]

FEATURE_HINTS = [
    ("login", "用户登录", "用户"),
    ("signin", "用户登录", "用户"),
    ("authenticate", "用户认证", "用户"),
    ("logout", "退出登录", "用户"),
    ("register", "用户注册", "用户"),
    ("signup", "用户注册", "用户"),
    ("project", "项目管理", "项目"),
    ("testcase", "测试用例", "测试"),
    ("test_case", "测试用例", "测试"),
    ("execution", "测试执行", "测试"),
    ("report", "测试报告", "报告"),
    ("asset", "资产管理", "资产"),
    ("agent", "AI Agent", "AI"),
]

CN_LABELS = {
    "login": "登录",
    "signin": "登录",
    "authenticate": "认证",
    "logout": "退出登录",
    "register": "注册",
    "signup": "注册",
    "auth": "认证",
    "user": "用户",
    "project": "项目",
    "home": "首页",
    "dashboard": "工作台",
}


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (text or "").lower())


def _humanize(name: str) -> str:
    raw = re.sub(r"(Page|View|Screen|Controller|Service|Handler)$", "", name or "")
    key = raw.lower()
    if key in CN_LABELS:
        return CN_LABELS[key]
    for hint, label in CN_LABELS.items():
        if hint in key:
            return label
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw).replace("_", " ").strip()
    return spaced or name or "未命名"


def _guess_route(path: str, name: str) -> str:
    stem = re.sub(r"(Page|View|Screen)$", "", name or "")
    if not stem:
        stem = path.rsplit("/", 1)[-1].split(".")[0]
    kebab = re.sub(r"([a-z])([A-Z])", r"\1-\2", stem).replace("_", "-").lower()
    return f"/{kebab}" if kebab else "/"


def _match_hint(text: str) -> Optional[tuple[str, str, str]]:
    blob = _norm(text)
    for key, title, module in FEATURE_HINTS:
        if key in blob:
            return key, title, module
    return None


def _load_extra(item: dict[str, Any]) -> dict[str, Any]:
    extra = item.get("extra") or {}
    if isinstance(extra, str):
        try:
            extra = json.loads(extra)
        except Exception:
            extra = {}
    return extra if isinstance(extra, dict) else {}


def compile_understanding(
    items: list[dict[str, Any]],
    *,
    cases: Optional[list[dict[str, Any]]] = None,
    assets: Optional[list[dict[str, Any]]] = None,
    project_name: str = "",
    repo_url: str = "",
    stack: Optional[list[str]] = None,
) -> dict[str, Any]:
    cases = cases or []
    assets = assets or []
    files = [i for i in items if i.get("kind") == "file"]
    pages = [i for i in items if i.get("kind") == "page"]
    elements = [i for i in items if i.get("kind") == "element"]
    components = [i for i in items if i.get("kind") == "component"]
    functions = [i for i in items if i.get("kind") in {"function", "class"}]
    apis = [i for i in items if i.get("kind") == "api"]
    modules = sorted({i.get("module") for i in items if i.get("module")})

    if not pages:
        for item in files:
            path = item.get("path") or ""
            if _is_page_path(path):
                pages.append({
                    **item,
                    "kind": "page",
                    "name": path.rsplit("/", 1)[-1].split(".")[0],
                    "extra": {"route": _guess_route(path, path.rsplit("/", 1)[-1].split(".")[0])},
                })

    languages = defaultdict(int)
    loc = 0
    for item in files:
        languages[item.get("language") or "other"] += 1
        loc += max(int(item.get("line_end") or 1) - int(item.get("line_start") or 1) + 1, 1)

    stack = list(stack or [])
    if not stack:
        if languages.get("python"):
            stack.append("Python")
        if languages.get("typescript") or languages.get("javascript"):
            stack.append("TypeScript/JavaScript")
        joined = " ".join((i.get("path") or "") + " " + (i.get("snippet") or "") for i in items[:80])
        if "fastapi" in joined.lower() or "@router" in joined:
            stack.append("FastAPI")
        if "react" in joined.lower() or components:
            stack.append("React")

    frontend_fw = next((s for s in stack if s in {"React", "Vue", "TypeScript/JavaScript"}), stack[0] if stack else "-")
    backend_fw = next((s for s in stack if s in {"FastAPI", "Python", "Django", "Spring"}), "-")
    database = "SQLAlchemy / MySQL" if any("model" in (i.get("path") or "").lower() for i in files) else "-"
    build = "Vite / npm" if any(i.get("language") in {"typescript", "javascript"} for i in files) else ("pip / Python" if languages.get("python") else "-")

    project_type = "API"
    if any(i.get("language") in {"typescript", "javascript", "vue"} for i in files) and apis:
        project_type = "全栈"
    elif any(i.get("language") in {"typescript", "javascript", "vue"} for i in files):
        project_type = "Web"
    elif apis:
        project_type = "API"

    page_rows = []
    for page in pages:
        extra = _load_extra(page)
        page_elements = [e for e in elements if e.get("path") == page.get("path")]
        page_apis = [a for a in apis if a.get("path") == page.get("path") or _shares_token(page.get("name"), a.get("name"))]
        page_fns = [f for f in functions if f.get("path") == page.get("path")]
        title = _humanize(page.get("name") or "")
        page_cases = _related_cases(title + " " + (page.get("name") or ""), cases)
        page_rows.append({
            "id": _norm(page.get("path") or page.get("name") or title) or title,
            "name": title,
            "raw_name": page.get("name"),
            "route": extra.get("route") or _guess_route(page.get("path") or "", page.get("name") or ""),
            "type": "页面",
            "module": _module_label(page.get("module") or ""),
            "path": page.get("path"),
            "purpose": extra.get("purpose") or f"{title}页面，入口文件 {(page.get('path') or '-')}",
            "element_count": len(page_elements) or int(extra.get("element_count") or 0),
            "status": "已分析" if page_elements or page_fns or page_apis else "已识别",
            "elements": [_element_row(e) for e in page_elements],
            "behaviors": _page_behaviors(page_fns, page_apis),
            "apis": [a.get("name") for a in page_apis],
            "functions": [f.get("name") for f in page_fns],
            "cases": page_cases,
        })

    feature_map: dict[str, dict[str, Any]] = {}
    for seed in pages + apis + functions:
        hint = _match_hint(" ".join([seed.get("name") or "", seed.get("path") or "", seed.get("signature") or ""]))
        if not hint:
            continue
        key, title, module = hint
        row = feature_map.setdefault(key, {
            "id": key,
            "name": title,
            "description": f"从代码中识别到的「{title}」能力",
            "module": module,
            "entry_page": None,
            "pages": [],
            "apis": [],
            "files": [],
            "functions": [],
            "components": [],
            "chain": [],
        })
        path = seed.get("path")
        if path and path not in row["files"]:
            row["files"].append(path)
        if seed.get("kind") == "page":
            label = _humanize(seed.get("name") or "")
            row["entry_page"] = row["entry_page"] or label
            if label not in row["pages"]:
                row["pages"].append(label)
        if seed.get("kind") == "api" and seed.get("name") not in row["apis"]:
            row["apis"].append(seed.get("name"))
        if seed.get("kind") in {"function", "class", "component"} and seed.get("name") not in row["functions"]:
            row["functions"].append(seed.get("name"))
        if seed.get("kind") == "component" and seed.get("name") not in row["components"]:
            row["components"].append(seed.get("name"))

    features = []
    for row in feature_map.values():
        related = _related_cases(row["name"] + " " + " ".join(row["apis"]), cases)
        auto = [c for c in related if "auto" in (c.get("type") or "") or "playwright" in (c.get("tags") or "").lower()]
        row["cases"] = related
        row["coverage"] = {
            "total": len(related),
            "automated": len(auto),
            "manual": max(len(related) - len(auto), 0),
            "rate": int(round(100 * len(related) / max(len(related) + (0 if related else 1), 1))) if related else 0,
        }
        row["chain"] = _feature_chain(row, items)
        features.append(row)

    module_rows = []
    for module in modules:
        related = [i for i in items if i.get("module") == module]
        page_names = [_humanize(i.get("name") or "") for i in related if i.get("kind") == "page"]
        api_names = [i.get("name") for i in related if i.get("kind") == "api"]
        file_names = [i.get("path") for i in related if i.get("kind") == "file"]
        feature_names = [f["name"] for f in features if module in (f.get("files") or []) or f["module"] in (module or "")]
        if not feature_names:
            feature_names = [f["name"] for f in features if any(p in module for p in (f.get("files") or []))]
        module_cases = _related_cases(module + " " + " ".join(page_names + api_names), cases)
        module_rows.append({
            "id": module,
            "name": _module_label(module),
            "path": module,
            "duty": f"覆盖 {len(file_names)} 个文件" + (f"，包含 {', '.join(page_names[:3])}" if page_names else ""),
            "page_count": len(set(page_names)),
            "feature_count": len(set(feature_names)),
            "api_count": len(api_names),
            "file_count": len(file_names),
            "test_count": len(module_cases),
            "pages": sorted(set(page_names)),
            "features": sorted(set(feature_names)),
            "apis": api_names,
            "files": file_names,
            "cases": module_cases,
        })

    api_rows = []
    for api in apis:
        extra = _load_extra(api)
        callers = [i for i in items if i.get("kind") in {"page", "function", "component"} and (
            extra.get("route") and extra.get("route") in ((i.get("snippet") or "") + (i.get("signature") or ""))
            or _shares_token(api.get("name"), i.get("name"))
        )]
        impl = next((i for i in functions if i.get("path") == api.get("path")), None)
        service = next((i for i in functions if "service" in (i.get("path") or "").lower() and _shares_token(api.get("name"), i.get("name"))), None)
        related = _related_cases(api.get("name") or "", cases)
        api_rows.append({
            "id": _norm(api.get("name") or api.get("path") or ""),
            "name": api.get("name"),
            "method": extra.get("method") or (api.get("name") or "GET").split(" ", 1)[0],
            "path": extra.get("route") or "",
            "file": api.get("path"),
            "line": api.get("line_start"),
            "module": _module_label(api.get("module") or ""),
            "feature": next((f["name"] for f in features if api.get("name") in f["apis"]), _humanize(api.get("name") or "")),
            "frontend_calls": len(callers),
            "callers": [{"name": c.get("name"), "path": c.get("path"), "kind": c.get("kind")} for c in callers[:12]],
            "controller": impl.get("name") if impl else None,
            "service": service.get("name") if service else None,
            "service_file": service.get("path") if service else None,
            "snippet": api.get("snippet"),
            "cases": related,
            "coverage": len(related),
        })

    file_rows = []
    for item in files:
        related_feature = next((f["name"] for f in features if item.get("path") in f["files"]), None)
        file_rows.append({
            "id": item.get("path"),
            "path": item.get("path"),
            "name": item.get("name"),
            "type": item.get("language") or "file",
            "module": _module_label(item.get("module") or ""),
            "feature": related_feature or _humanize(item.get("name") or ""),
            "lines": max(int(item.get("line_end") or 1), 1),
            "snippet": item.get("snippet"),
        })

    flows = _build_flows(page_rows, features, api_rows)
    architecture = _build_architecture(files, apis, functions, stack)

    steps = []
    counts = {
        "structure": len(files),
        "stack": len(stack),
        "frontend": len(page_rows),
        "api": len(api_rows),
        "components": len(components),
        "elements": len(elements),
        "code": len(functions),
        "modules": len(module_rows),
        "flows": len(flows),
        "tests": len(cases) + len(assets),
    }
    done = 0
    for key, label in ANALYSIS_STEPS:
        value = counts[key]
        status = "done" if value else "empty"
        if status == "done":
            done += 1
        steps.append({"key": key, "label": label, "status": status, "count": value})

    total = len(ANALYSIS_STEPS)
    progress = int(round(100 * done / total)) if total else 0
    if not files:
        analysis_status = "empty"
    elif done < total:
        analysis_status = "partial"
    else:
        analysis_status = "ready"

    return {
        "status": analysis_status,
        "progress": progress,
        "steps": steps,
        "project": {
            "name": project_name,
            "description": f"已从 {repo_url or '本地快照'} 解析出可测试的项目知识",
            "type": project_type,
            "stack": stack,
            "frontend": frontend_fw,
            "backend": backend_fw,
            "database": database,
            "build": build,
            "repo_url": repo_url,
        },
        "scale": {
            "pages": len(page_rows),
            "features": len(features),
            "modules": len(module_rows),
            "components": len(components),
            "apis": len(api_rows),
            "files": len(files),
            "loc": loc,
            "cases": len(cases),
            "assets": len(assets),
        },
        "pages": page_rows,
        "features": features,
        "modules": module_rows,
        "apis": api_rows,
        "files": file_rows,
        "elements": [_element_row(e) for e in elements],
        "flows": flows,
        "architecture": architecture,
        "coverage": _coverage_board(page_rows, features, api_rows, cases, assets),
    }


def _is_page_path(path: str) -> bool:
    lowered = (path or "").replace("\\", "/")
    return bool(re.search(r"(?:pages|views|screens)/.+\.(tsx|jsx|vue)$", lowered, re.I) or re.search(r"Page\.(tsx|jsx|vue)$", lowered))


def _module_label(module: str) -> str:
    if not module:
        return "未分组"
    tail = module.rstrip("/").split("/")[-1]
    return CN_LABELS.get(tail.lower(), tail)


def _shares_token(left: Optional[str], right: Optional[str]) -> bool:
    a = set(re.findall(r"[a-z]{3,}", (left or "").lower()))
    b = set(re.findall(r"[a-z]{3,}", (right or "").lower()))
    return bool(a & b)


def _element_row(item: dict[str, Any]) -> dict[str, Any]:
    extra = _load_extra(item)
    return {
        "id": item.get("id") or f"{item.get('path')}:{item.get('line_start')}:{item.get('name')}",
        "name": item.get("name"),
        "type": extra.get("tag") or item.get("kind"),
        "path": item.get("path"),
        "line": item.get("line_start"),
        "page": extra.get("page") or item.get("path"),
        "component": extra.get("component"),
        "events": extra.get("events") or [],
        "handler": extra.get("handler"),
        "api": extra.get("api"),
        "locator": extra.get("locator") or item.get("signature"),
        "snippet": item.get("snippet"),
    }


def _page_behaviors(functions: list[dict[str, Any]], apis: list[dict[str, Any]]) -> list[str]:
    steps = []
    for fn in functions:
        steps.append(f"触发 {fn.get('name')}")
    for api in apis:
        steps.append(f"调用 {api.get('name')}")
    if not steps:
        return ["打开页面", "与表单或按钮交互", "等待页面反馈"]
    return steps


def _feature_chain(feature: dict[str, Any], items: list[dict[str, Any]]) -> list[dict[str, str]]:
    chain = [{"layer": "用户操作", "name": feature["name"]}]
    if feature.get("entry_page"):
        chain.append({"layer": "页面", "name": feature["entry_page"]})
    if feature.get("components"):
        chain.append({"layer": "组件", "name": feature["components"][0]})
    handlers = [n for n in feature.get("functions") or [] if n.lower().startswith("handle") or "login" in n.lower()]
    if handlers:
        chain.append({"layer": "事件 / 前端函数", "name": handlers[0]})
    if feature.get("apis"):
        chain.append({"layer": "API", "name": feature["apis"][0]})
    backend = next((i for i in items if i.get("kind") in {"function", "class"} and "service" in (i.get("path") or "").lower() and _shares_token(feature["name"], i.get("name"))), None)
    if backend:
        chain.append({"layer": "Service", "name": backend.get("name") or "", "path": backend.get("path") or ""})
    db = next((i for i in items if "model" in (i.get("path") or "").lower()), None)
    if db:
        chain.append({"layer": "Database", "name": db.get("name") or db.get("path") or ""})
    return chain


def _build_flows(pages: list[dict[str, Any]], features: list[dict[str, Any]], apis: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not pages and not features:
        return []
    steps = []
    login = next((p for p in pages if "登录" in p["name"] or "login" in (p.get("raw_name") or "").lower()), None)
    if login:
        steps.append({"name": "登录", "page": login["name"], "path": login.get("path"), "apis": login.get("apis") or [], "elements": [e["name"] for e in login.get("elements") or []]})
    for page in pages:
        if login and page["id"] == login["id"]:
            continue
        steps.append({"name": page["name"], "page": page["name"], "path": page.get("path"), "apis": page.get("apis") or [], "elements": [e["name"] for e in page.get("elements") or []]})
    if not steps:
        for feat in features[:5]:
            steps.append({"name": feat["name"], "page": feat.get("entry_page"), "path": (feat.get("files") or [None])[0], "apis": feat.get("apis") or [], "elements": []})
    return [{
        "id": "primary",
        "name": "核心用户路径",
        "steps": steps[:8],
        "apis": [a["name"] for a in apis[:8]],
    }]


def _build_architecture(files: list[dict[str, Any]], apis: list[dict[str, Any]], functions: list[dict[str, Any]], stack: list[str]) -> list[dict[str, Any]]:
    nodes = []
    if any((f.get("language") in {"typescript", "javascript", "vue"}) or "frontend" in (f.get("path") or "") for f in files):
        nodes.append({"id": "frontend", "name": "前端", "detail": next((s for s in stack if s in {"React", "TypeScript/JavaScript", "Vue"}), "Frontend")})
    if apis:
        nodes.append({"id": "api", "name": "API", "detail": f"{len(apis)} 个接口"})
    if any("service" in (f.get("path") or "").lower() for f in files + functions):
        nodes.append({"id": "service", "name": "业务服务", "detail": "Service / Domain"})
    if any("model" in (f.get("path") or "").lower() for f in files):
        nodes.append({"id": "database", "name": "数据库", "detail": "Models"})
    if any(re.search(r"\b(agent|llm|openai|rag)\b", (f.get("path") or ""), re.I) for f in files):
        nodes.append({"id": "ai", "name": "AI / 外部服务", "detail": "Agent / LLM"})
    if not nodes:
        nodes.append({"id": "code", "name": "代码仓库", "detail": f"{len(files)} 个文件"})
    return nodes


def _related_cases(text: str, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    blob = _norm(text)
    hits = []
    for case in cases:
        hay = _norm(" ".join([
            str(case.get("name") or ""),
            str(case.get("module") or ""),
            str(case.get("tags") or ""),
            str(case.get("scenario") or ""),
        ]))
        if blob and (blob in hay or hay in blob or any(token and token in hay for token in re.findall(r"[a-z\u4e00-\u9fff]{2,}", blob)[:4])):
            hits.append(case)
    return hits[:20]


def _coverage_board(pages, features, apis, cases, assets) -> dict[str, Any]:
    return {
        "pages": [{"name": p["name"], "total": len(p.get("cases") or []), "covered": len(p.get("cases") or []), "missing": 0 if p.get("cases") else 1} for p in pages],
        "features": [{"name": f["name"], **f.get("coverage", {})} for f in features],
        "apis": [{"name": a["name"], "total": a.get("coverage") or 0} for a in apis],
        "summary": {
            "cases": len(cases),
            "assets": len(assets),
            "pages_covered": sum(1 for p in pages if p.get("cases")),
            "features_covered": sum(1 for f in features if (f.get("coverage") or {}).get("total")),
        },
    }


class ProjectUnderstandingService:
    def snapshot(self, user_id: int, project_id: int, *, refresh: bool = False) -> dict[str, Any]:
        db = SessionLocal()
        try:
            source = db.query(ProjectSource).filter(
                ProjectSource.user_id == user_id,
                ProjectSource.project_id == project_id,
            ).first()
            project = db.query(Project).filter(Project.id == project_id).first()
            if not source:
                return {"imported": False, "status": "empty", "progress": 0, "steps": [
                    {"key": key, "label": label, "status": "empty", "count": 0} for key, label in ANALYSIS_STEPS
                ]}
            overview = {}
            if source.overview_json:
                try:
                    overview = json.loads(source.overview_json)
                except Exception:
                    overview = {}
            understanding = overview.get("understanding") if isinstance(overview, dict) else None
            if refresh or not understanding:
                understanding = self._compile_from_db(db, user_id, project_id, project, source)
                overview["understanding"] = understanding
                overview["analysis_steps"] = understanding.get("steps")
                source.overview_json = json.dumps(overview, ensure_ascii=False)
                source.status = understanding.get("status") or source.status
                db.commit()
            return {
                "imported": True,
                "source_type": source.source_type,
                "repo_url": source.repo_url,
                "repo_name": source.repo_name,
                "branch": source.default_branch,
                "file_count": source.file_count,
                "symbol_count": source.symbol_count,
                "updated_at": source.updated_at.isoformat() if source.updated_at else None,
                **understanding,
            }
        finally:
            db.close()

    def _compile_from_db(self, db, user_id: int, project_id: int, project, source) -> dict[str, Any]:
        rows = db.query(ProjectCodeIndex).filter(
            ProjectCodeIndex.user_id == user_id,
            ProjectCodeIndex.project_id == project_id,
        ).all()
        items = []
        for row in rows:
            extra = {}
            if row.extra_json:
                try:
                    extra = json.loads(row.extra_json)
                except Exception:
                    extra = {}
            items.append({
                "id": row.id,
                "kind": row.kind,
                "name": row.name,
                "path": row.path,
                "module": row.module,
                "language": row.language,
                "line_start": row.line_start,
                "line_end": row.line_end,
                "signature": row.signature,
                "snippet": row.snippet,
                "extra": extra,
            })
        cases = self._load_cases(db, user_id, project_id)
        assets = self._load_assets(db, user_id, project_id)
        overview = {}
        if source.overview_json:
            try:
                overview = json.loads(source.overview_json)
            except Exception:
                overview = {}
        return compile_understanding(
            items,
            cases=cases,
            assets=assets,
            project_name=(project.name if project else "") or source.repo_name or "",
            repo_url=source.repo_url or "",
            stack=(overview.get("stack") if isinstance(overview, dict) else None) or [],
        )

    @staticmethod
    def _load_cases(db, user_id: int, project_id: int) -> list[dict[str, Any]]:
        try:
            from app.models.test_case import TestCase
            rows = db.query(TestCase).filter(
                TestCase.user_id == user_id,
                TestCase.project_id == project_id,
            ).limit(200).all()
            return [{
                "id": row.id,
                "name": row.case_name,
                "code": getattr(row, "case_code", None),
                "module": getattr(row, "module", None),
                "scenario": getattr(row, "scenario", None),
                "tags": getattr(row, "tags", None) or "",
                "type": row.type,
                "status": row.status,
            } for row in rows]
        except Exception:
            return []

    @staticmethod
    def _load_assets(db, user_id: int, project_id: int) -> list[dict[str, Any]]:
        try:
            from app.models.test_asset import TestAsset
            rows = db.query(TestAsset).filter(
                TestAsset.user_id == user_id,
                TestAsset.project_id == project_id,
            ).limit(200).all()
            return [{"id": row.id, "name": getattr(row, "name", None) or getattr(row, "title", ""), "type": getattr(row, "asset_type", "")} for row in rows]
        except Exception:
            return []
