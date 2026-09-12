"""把导入的代码项目建成可复用索引，避免每次问答全量扫描。"""
from __future__ import annotations

import ast
import io
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.db.database import SessionLocal
from app.models.project_explorer import ProjectCodeIndex, ProjectSource
from app.models.team import Project

SKIP_DIRS = {
    ".git", "node_modules", "dist", "build", "venv", ".venv", "__pycache__",
    ".next", "coverage", "vendor", ".idea", ".vscode", "target", "bin", "obj",
}
CODE_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".vue": "vue",
    ".go": "go", ".java": "java",
}
MAX_FILES = 800
MAX_BYTES = 180_000

FN_RE = re.compile(
    r"^(?:export\s+)?(?:async\s+)?(?:function|const|let|var)\s+([A-Za-z_][\w]*)",
    re.M,
)
CLASS_RE = re.compile(r"^(?:export\s+)?class\s+([A-Za-z_][\w]*)", re.M)
ROUTE_RE = re.compile(
    r"""(?:@router\.(get|post|put|delete|patch)\(|app\.(get|post|put|delete|patch)\(|(?:fetch|axios)\.(get|post|put|delete|patch)\()\s*['\"]([^'\"]+)['\"]""",
    re.I,
)
FETCH_RE = re.compile(r"""(?:fetch|axios)\(\s*['\"]([^'\"]+)['\"][^)]*(?:method\s*:\s*['\"](\w+)['\"])?""", re.I)
IMPORT_RE = re.compile(r"""(?:from\s+['\"]([^'\"]+)['\"]|import\s+['\"]([^'\"]+)['\"]|from\s+([\w.]+)\s+import)""")
ELEMENT_RE = re.compile(
    r"<(button|input|select|textarea|form|table|a|Modal|Select|Input|Button|Table|Menu|Link)\b([^>]*)>",
    re.I,
)
HANDLER_RE = re.compile(r"""on(?:Click|Change|Submit|Press)=\{([A-Za-z_][\w]*)\}""", re.I)
GIT_HOSTS = {
    "github.com": "github",
    "www.github.com": "github",
    "gitlab.com": "gitlab",
    "www.gitlab.com": "gitlab",
    "gitee.com": "gitee",
    "www.gitee.com": "gitee",
}


def parse_git_url(url: str) -> dict[str, str]:
    raw = (url or "").strip()
    if not raw:
        raise ValueError("请输入 Git 仓库地址")
    if raw.endswith(".git"):
        raw = raw[:-4]
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    kind = GIT_HOSTS.get(host)
    if not kind:
        raise ValueError("目前支持 GitHub / GitLab / Gitee，其他仓库请上传 ZIP")
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError("Git 地址格式无效")
    owner, name = parts[0], parts[1]
    branch = "main"
    if kind == "gitlab" and "/-/" in parsed.path:
        after = parsed.path.split("/-/")[-1]
        segs = [p for p in after.split("/") if p]
        if segs and segs[0] in {"tree", "blob"} and len(segs) > 1:
            branch = segs[1]
    elif len(parts) >= 4 and parts[2] in {"tree", "blob"}:
        branch = parts[3]
    return {
        "host": kind,
        "owner": owner,
        "name": name,
        "branch": branch,
        "url": f"{parsed.scheme or 'https'}://{host}/{owner}/{name}",
    }


def parse_github_url(url: str) -> dict[str, str]:
    meta = parse_git_url(url)
    if meta["host"] != "github":
        raise ValueError("只支持 GitHub 仓库地址")
    return meta


def _iter_files(root: Path):
    count = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() not in CODE_EXT:
            continue
        if path.stat().st_size > MAX_BYTES:
            continue
        count += 1
        if count > MAX_FILES:
            break
        yield path


def _module_name(rel: str) -> str:
    parts = Path(rel).with_suffix("").parts
    if not parts:
        return rel
    if parts[0] in {"src", "app", "frontend", "backend"}:
        return "/".join(parts[:3]) if len(parts) > 2 else "/".join(parts)
    return "/".join(parts[:2])


def _index_python(text: str, rel: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return items
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            args = ""
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = "(" + ", ".join(a.arg for a in node.args.args) + ")"
            items.append({
                "kind": kind,
                "name": node.name,
                "path": rel,
                "line_start": getattr(node, "lineno", None),
                "line_end": getattr(node, "end_lineno", None),
                "signature": f"{node.name}{args}",
                "snippet": "\n".join(text.splitlines()[max((node.lineno or 1) - 1, 0): (node.end_lineno or node.lineno or 1)][:12]),
            })
            if node.name.lower() in {"login", "authenticate", "signin"} or "login" in node.name.lower():
                items[-1]["kind"] = items[-1]["kind"]
    return items


def _index_script(text: str, rel: str) -> list[dict[str, Any]]:
    items = []
    for match in CLASS_RE.finditer(text):
        line = text[:match.start()].count("\n") + 1
        items.append({
            "kind": "component" if match.group(1)[0].isupper() else "class",
            "name": match.group(1),
            "path": rel,
            "line_start": line,
            "line_end": line + 8,
            "signature": match.group(1),
            "snippet": "\n".join(text.splitlines()[line - 1:line + 8]),
        })
    for match in FN_RE.finditer(text):
        line = text[:match.start()].count("\n") + 1
        name = match.group(1)
        items.append({
            "kind": "component" if name[0].isupper() else "function",
            "name": name,
            "path": rel,
            "line_start": line,
            "line_end": line + 8,
            "signature": name,
            "snippet": "\n".join(text.splitlines()[line - 1:line + 8]),
        })
    return items


def _index_apis(text: str, rel: str) -> list[dict[str, Any]]:
    items = []
    seen = set()
    for match in ROUTE_RE.finditer(text):
        method = next((g for g in match.groups()[:-1] if g), "GET")
        route = match.group(match.lastindex)
        line = text[:match.start()].count("\n") + 1
        key = f"{method.upper()} {route}"
        if key in seen:
            continue
        seen.add(key)
        items.append({
            "kind": "api",
            "name": key,
            "path": rel,
            "line_start": line,
            "line_end": line,
            "signature": key,
            "snippet": "\n".join(text.splitlines()[line - 1:line + 3]),
            "extra": {"method": method.upper(), "route": route},
        })
    for match in FETCH_RE.finditer(text):
        route = match.group(1)
        method = (match.group(2) or "GET").upper()
        if not route.startswith("/") and "://" not in route:
            continue
        key = f"{method} {route}"
        if key in seen:
            continue
        seen.add(key)
        line = text[:match.start()].count("\n") + 1
        items.append({
            "kind": "api",
            "name": key,
            "path": rel,
            "line_start": line,
            "line_end": line,
            "signature": key,
            "snippet": "\n".join(text.splitlines()[line - 1:line + 3]),
            "extra": {"method": method, "route": route},
        })
    return items


def _is_page_path(rel: str) -> bool:
    lowered = rel.replace("\\", "/")
    return bool(re.search(r"(?:pages|views|screens)/.+\.(tsx|jsx|vue)$", lowered, re.I) or re.search(r"Page\.(tsx|jsx|vue)$", lowered))


def _guess_route(rel: str) -> str:
    stem = Path(rel).stem
    stem = re.sub(r"(Page|View|Screen)$", "", stem)
    kebab = re.sub(r"([a-z])([A-Z])", r"\1-\2", stem).replace("_", "-").lower()
    return f"/{kebab}" if kebab else "/"


def _index_page(text: str, rel: str, lang: str) -> list[dict[str, Any]]:
    if not _is_page_path(rel):
        return []
    name = Path(rel).stem
    elements = _index_elements(text, rel, name)
    return [{
        "kind": "page",
        "name": name,
        "path": rel,
        "language": lang,
        "module": _module_name(rel),
        "line_start": 1,
        "line_end": text.count("\n") + 1,
        "signature": _guess_route(rel),
        "snippet": "\n".join(text.splitlines()[:10]),
        "extra": {"route": _guess_route(rel), "element_count": len(elements), "purpose": f"{name} 页面"},
    }] + elements


def _index_elements(text: str, rel: str, page_name: str) -> list[dict[str, Any]]:
    items = []
    for match in ELEMENT_RE.finditer(text):
        tag = match.group(1)
        attrs = match.group(2) or ""
        line = text[:match.start()].count("\n") + 1
        label = _attr(attrs, "placeholder") or _attr(attrs, "aria-label") or _attr(attrs, "name") or tag
        inner = text[match.end():match.end() + 80]
        text_label = re.match(r"([^<{]{1,24})", inner)
        if text_label and text_label.group(1).strip():
            label = text_label.group(1).strip()
        handlers = HANDLER_RE.findall(attrs) or HANDLER_RE.findall(text[max(0, match.start() - 80):match.end() + 80])
        items.append({
            "kind": "element",
            "name": label[:80],
            "path": rel,
            "language": CODE_EXT.get(Path(rel).suffix.lower()),
            "module": _module_name(rel),
            "line_start": line,
            "line_end": line,
            "signature": f"<{tag}> {label}",
            "snippet": "\n".join(text.splitlines()[line - 1:line + 2]),
            "extra": {
                "tag": tag.lower(),
                "page": page_name,
                "handler": handlers[0] if handlers else None,
                "events": handlers,
                "locator": f"{rel}:{line}:{tag}",
            },
        })
    return items[:40]


def _attr(attrs: str, key: str) -> Optional[str]:
    match = re.search(rf"""{key}\s*=\s*['\"]([^'\"]+)['\"]""", attrs, re.I)
    return match.group(1) if match else None


def index_tree(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    files: list[dict[str, Any]] = []
    languages: dict[str, int] = {}
    for path in _iter_files(root):
        rel = path.relative_to(root).as_posix()
        lang = CODE_EXT[path.suffix.lower()]
        languages[lang] = languages.get(lang, 0) + 1
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        imports = [a or b or c for a, b, c in IMPORT_RE.findall(text)][:20]
        files.append({
            "kind": "file",
            "name": path.name,
            "path": rel,
            "language": lang,
            "module": _module_name(rel),
            "line_start": 1,
            "line_end": text.count("\n") + 1,
            "signature": rel,
            "snippet": "\n".join(text.splitlines()[:8]),
            "extra": {"imports": imports},
        })
        files.append({
            "kind": "module",
            "name": _module_name(rel),
            "path": rel,
            "language": lang,
            "module": _module_name(rel),
            "line_start": 1,
            "signature": _module_name(rel),
            "snippet": rel,
        })
        if lang == "python":
            files.extend(_index_python(text, rel))
        else:
            files.extend(_index_script(text, rel))
        files.extend(_index_page(text, rel, lang))
        for item in _index_apis(text, rel):
            item["language"] = lang
            item["module"] = _module_name(rel)
            files.append(item)
    overview = {
        "file_count": sum(1 for item in files if item["kind"] == "file"),
        "symbol_count": sum(1 for item in files if item["kind"] != "file"),
        "page_count": sum(1 for item in files if item["kind"] == "page"),
        "api_count": sum(1 for item in files if item["kind"] == "api"),
        "element_count": sum(1 for item in files if item["kind"] == "element"),
        "languages": languages,
        "modules": sorted({item["module"] for item in files if item.get("module")}),
        "apis": [item["name"] for item in files if item["kind"] == "api"][:40],
        "stack": _guess_stack(languages, files),
    }
    return files, overview


def _guess_stack(languages: dict[str, int], files: list[dict[str, Any]]) -> list[str]:
    stack = []
    if languages.get("python"):
        stack.append("Python")
    if languages.get("typescript") or languages.get("javascript"):
        stack.append("TypeScript/JavaScript")
    joined = " ".join(item.get("path", "") for item in files)
    if "playwright" in joined.lower() or any("playwright" in (item.get("snippet") or "").lower() for item in files[:30]):
        stack.append("Playwright")
    if "fastapi" in joined.lower() or any("@router" in (item.get("snippet") or "") for item in files):
        stack.append("FastAPI")
    if "react" in joined.lower() or any(item["kind"] == "component" for item in files):
        stack.append("React")
    return stack or list(languages)


def _git_zip_urls(meta: dict[str, str], branch: str) -> list[str]:
    owner, name, host = meta["owner"], meta["name"], meta.get("host") or "github"
    if host == "github":
        return [f"https://codeload.github.com/{owner}/{name}/zip/refs/heads/{branch}"]
    if host == "gitlab":
        return [f"https://gitlab.com/{owner}/{name}/-/archive/{branch}/{name}-{branch}.zip"]
    if host == "gitee":
        return [f"https://gitee.com/{owner}/{name}/repository/archive/{branch}.zip"]
    return []


def download_git_zip(meta: dict[str, str], dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    last_error = None
    for branch in (meta.get("branch") or "main", "main", "master"):
        for url in _git_zip_urls(meta, branch):
            try:
                req = Request(url, headers={"User-Agent": "ui-automation-project-explorer"})
                with urlopen(req, timeout=40) as resp:
                    payload = resp.read()
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    zf.extractall(dest)
                roots = [p for p in dest.iterdir() if p.is_dir()]
                meta["branch"] = branch
                return roots[0] if roots else dest
            except Exception as exc:  # noqa: BLE001
                last_error = exc
    raise ValueError(f"无法下载 Git 仓库：{last_error}")


def download_github_zip(meta: dict[str, str], dest: Path) -> Path:
    return download_git_zip(meta, dest)


class ProjectIndexer:
    def import_github(self, user_id: int, project_id: int, repo_url: str) -> dict[str, Any]:
        return self.import_git(user_id, project_id, repo_url)

    def import_git(self, user_id: int, project_id: int, repo_url: str) -> dict[str, Any]:
        meta = parse_git_url(repo_url)
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError("项目不存在")
            root = Path("data") / "project_sources" / str(user_id) / str(project_id)
            self._clear_dir(root)
            code_root = download_git_zip(meta, root)
            return self._persist(db, user_id, project, meta["host"], meta["url"], meta, code_root)
        finally:
            db.close()

    def import_archive(self, user_id: int, project_id: int, filename: str, payload: bytes) -> dict[str, Any]:
        if not payload:
            raise ValueError("上传文件为空")
        if len(payload) > 40 * 1024 * 1024:
            raise ValueError("ZIP 不能超过 40MB")
        if not (filename or "").lower().endswith(".zip"):
            raise ValueError("只支持 ZIP 项目包")
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError("项目不存在")
            root = Path("data") / "project_sources" / str(user_id) / str(project_id)
            self._clear_dir(root)
            root.mkdir(parents=True, exist_ok=True)
            try:
                with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                    zf.extractall(root)
            except zipfile.BadZipFile as exc:
                raise ValueError("ZIP 文件损坏") from exc
            roots = [p for p in root.iterdir() if p.is_dir() and p.name not in SKIP_DIRS]
            code_root = roots[0] if len(roots) == 1 else root
            meta = {"owner": "upload", "name": Path(filename).stem, "branch": "", "url": filename, "host": "archive"}
            return self._persist(db, user_id, project, "archive", filename, meta, code_root)
        finally:
            db.close()

    @staticmethod
    def _clear_dir(root: Path) -> None:
        if not root.exists():
            return
        for child in root.rglob("*"):
            if child.is_file():
                child.unlink(missing_ok=True)

    def import_sample(self, user_id: int, project_id: int) -> dict[str, Any]:
        root = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample_codebase"
        return self.import_local(user_id, project_id, str(root))

    def import_local(self, user_id: int, project_id: int, local_path: str) -> dict[str, Any]:
        root = Path(local_path).resolve()
        allowed = [
            (Path(__file__).resolve().parents[2] / "tests" / "fixtures").resolve(),
            (Path("data") / "project_sources").resolve(),
        ]
        if not any(str(root).startswith(str(prefix)) for prefix in allowed):
            raise ValueError("本地导入仅允许测试夹具或已下载的项目快照")
        if not root.exists() or not root.is_dir():
            raise ValueError("本地目录不存在")
        db = SessionLocal()
        try:
            project = db.query(Project).filter(Project.id == project_id).first()
            if not project:
                raise ValueError("项目不存在")
            meta = {"owner": "local", "name": root.name, "branch": "", "url": str(root)}
            return self._persist(db, user_id, project, "local", str(root), meta, root)
        finally:
            db.close()

    def _persist(self, db, user_id: int, project: Project, source_type: str, repo_url: str, meta: dict[str, str], code_root: Path) -> dict[str, Any]:
        items, overview = index_tree(code_root)
        existing = db.query(ProjectSource).filter(
            ProjectSource.user_id == user_id,
            ProjectSource.project_id == project.id,
        ).first()
        existing_files = existing.file_count if existing else 0
        if overview["file_count"] == 0 and existing_files:
            raise ValueError("该仓库没有可索引的代码文件，已保留现有项目理解")
        db.query(ProjectCodeIndex).filter(
            ProjectCodeIndex.user_id == user_id,
            ProjectCodeIndex.project_id == project.id,
        ).delete()
        source = existing
        if not source:
            source = ProjectSource(user_id=user_id, created_by=user_id, project_id=project.id, organization_id=project.organization_id)
            db.add(source)
        from app.services.project_understanding import ProjectUnderstandingService, compile_understanding
        brain = ProjectUnderstandingService()
        understanding = compile_understanding(
            items,
            cases=brain._load_cases(db, user_id, project.id),
            assets=brain._load_assets(db, user_id, project.id),
            project_name=project.name or meta.get("name") or "",
            repo_url=repo_url,
            stack=overview.get("stack") or [],
        )
        overview["understanding"] = understanding
        overview["analysis_steps"] = understanding.get("steps")
        source.source_type = source_type
        source.repo_url = repo_url
        source.repo_owner = meta.get("owner")
        source.repo_name = meta.get("name")
        source.default_branch = meta.get("branch")
        source.local_path = str(code_root)
        source.status = understanding.get("status") or ("ready" if overview["file_count"] else "empty")
        source.file_count = overview["file_count"]
        source.symbol_count = overview["symbol_count"]
        source.overview_json = json.dumps(overview, ensure_ascii=False)
        for item in items:
            extra = item.get("extra")
            db.add(ProjectCodeIndex(
                user_id=user_id,
                created_by=user_id,
                organization_id=project.organization_id,
                project_id=project.id,
                kind=item["kind"],
                name=item["name"][:255],
                path=item["path"][:512],
                language=item.get("language"),
                module=item.get("module"),
                line_start=item.get("line_start"),
                line_end=item.get("line_end"),
                signature=(item.get("signature") or "")[:512],
                snippet=(item.get("snippet") or "")[:2000],
                extra_json=json.dumps(extra, ensure_ascii=False) if extra else None,
            ))
        db.commit()
        return {
            "imported": True,
            "source_type": source.source_type,
            "repo_url": source.repo_url,
            "repo_name": source.repo_name,
            "branch": source.default_branch,
            "file_count": source.file_count,
            "symbol_count": source.symbol_count,
            "status": source.status,
            "progress": understanding.get("progress"),
            "overview": overview,
            **understanding,
        }

    def analyze(self, user_id: int, project_id: int, mode: str = "incremental") -> dict[str, Any]:
        from app.services.project_understanding import ProjectUnderstandingService
        if mode != "full":
            return ProjectUnderstandingService().snapshot(user_id, project_id, refresh=True)
        db = SessionLocal()
        try:
            source = db.query(ProjectSource).filter(
                ProjectSource.user_id == user_id,
                ProjectSource.project_id == project_id,
            ).first()
            if not source:
                raise ValueError("还没有导入项目")
            project = db.query(Project).filter(Project.id == project_id).first()
            if source.local_path and Path(source.local_path).exists():
                meta = {
                    "owner": source.repo_owner or "local",
                    "name": source.repo_name or Path(source.local_path).name,
                    "branch": source.default_branch or "",
                    "url": source.repo_url or source.local_path,
                    "host": source.source_type or "local",
                }
                return self._persist(db, user_id, project, source.source_type or "local", source.repo_url or source.local_path, meta, Path(source.local_path))
        finally:
            db.close()
        return ProjectUnderstandingService().snapshot(user_id, project_id, refresh=True)

    def read_file(self, user_id: int, project_id: int, rel_path: str) -> dict[str, Any]:
        rel = (rel_path or "").replace("\\", "/").lstrip("/")
        if not rel or ".." in rel.split("/"):
            raise ValueError("非法文件路径")
        db = SessionLocal()
        try:
            source = db.query(ProjectSource).filter(
                ProjectSource.user_id == user_id,
                ProjectSource.project_id == project_id,
            ).first()
            if not source or not source.local_path:
                raise ValueError("还没有导入项目源码")
            root = Path(source.local_path).resolve()
            target = (root / rel).resolve()
            if not str(target).startswith(str(root)):
                raise ValueError("非法文件路径")
            if not target.is_file():
                raise ValueError("文件不存在")
            text = target.read_text(encoding="utf-8", errors="ignore")
            if len(text) > 80_000:
                text = text[:80_000] + "\n/* truncated */"
            return {"path": rel, "content": text, "language": CODE_EXT.get(target.suffix.lower())}
        finally:
            db.close()

    def overview(self, user_id: int, project_id: int) -> dict[str, Any]:
        db = SessionLocal()
        try:
            source = db.query(ProjectSource).filter(
                ProjectSource.user_id == user_id,
                ProjectSource.project_id == project_id,
            ).first()
            if not source:
                return {"imported": False}
            overview = json.loads(source.overview_json or "{}")
            understanding = overview.get("understanding") if isinstance(overview, dict) else {}
            return {
                "imported": True,
                "source_type": source.source_type,
                "repo_url": source.repo_url,
                "repo_name": source.repo_name,
                "branch": source.default_branch,
                "file_count": source.file_count,
                "symbol_count": source.symbol_count,
                "status": source.status,
                "progress": (understanding or {}).get("progress"),
                "project_type": (understanding or {}).get("project", {}).get("type"),
                "overview": overview,
                "updated_at": source.updated_at.isoformat() if source.updated_at else None,
            }
        finally:
            db.close()

    def query_index(
        self,
        user_id: int,
        project_id: int,
        *,
        keyword: Optional[str] = None,
        kind: Optional[str] = None,
        path: Optional[str] = None,
        limit: int = 40,
    ) -> list[dict[str, Any]]:
        db = SessionLocal()
        try:
            q = db.query(ProjectCodeIndex).filter(
                ProjectCodeIndex.user_id == user_id,
                ProjectCodeIndex.project_id == project_id,
            )
            if kind:
                q = q.filter(ProjectCodeIndex.kind == kind)
            if path:
                q = q.filter(ProjectCodeIndex.path == path)
            if keyword:
                like = f"%{keyword.strip()}%"
                q = q.filter(
                    (ProjectCodeIndex.name.like(like))
                    | (ProjectCodeIndex.path.like(like))
                    | (ProjectCodeIndex.signature.like(like))
                    | (ProjectCodeIndex.snippet.like(like))
                    | (ProjectCodeIndex.module.like(like))
                )
            rows = q.order_by(ProjectCodeIndex.kind.asc(), ProjectCodeIndex.path.asc()).limit(limit).all()
            return [self._row(row) for row in rows]
        finally:
            db.close()

    @staticmethod
    def _row(row: ProjectCodeIndex) -> dict[str, Any]:
        extra = {}
        if row.extra_json:
            try:
                extra = json.loads(row.extra_json)
            except Exception:
                extra = {}
        return {
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
        }
