from pathlib import Path

from app.services.project_agent import ProjectAgentService, _keywords
from app.services.project_indexer import ProjectIndexer, index_tree, parse_github_url, parse_git_url
from app.services.project_memory import ProjectMemoryService
from app.services.project_understanding import compile_understanding


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_codebase"


def test_keywords_expand_login():
    words = _keywords("登录功能在哪里？")
    assert "login" in words
    assert "authenticate" in words


def test_parse_github_url():
    meta = parse_github_url("https://github.com/octocat/Hello-World")
    assert meta["owner"] == "octocat"
    assert meta["name"] == "Hello-World"


def test_parse_git_hosts():
    gitlab = parse_git_url("https://gitlab.com/group/demo")
    assert gitlab["host"] == "gitlab"
    assert gitlab["name"] == "demo"
    gitee = parse_git_url("https://gitee.com/foo/bar")
    assert gitee["host"] == "gitee"
    try:
        parse_git_url("https://example.com/foo/bar")
        raise AssertionError("should reject unknown host")
    except ValueError as exc:
        assert "GitHub" in str(exc) or "ZIP" in str(exc)


def test_index_tree_locates_login():
    items, overview = index_tree(FIXTURE)
    paths = {item["path"] for item in items}
    assert "frontend/src/pages/LoginPage.tsx" in paths
    assert "backend/app/services/auth_service.py" in paths
    names = {item["name"] for item in items}
    assert "LoginPage" in names or "handleLogin" in names
    assert "authenticate" in names
    assert any(item["kind"] == "api" and "/auth/login" in item["name"] for item in items)
    assert overview["file_count"] >= 3
    assert any(item["kind"] == "page" and item["name"] == "LoginPage" for item in items)
    assert any(item["kind"] == "element" for item in items)
    knowledge = compile_understanding(items, project_name="示例登录", repo_url="sample")
    assert knowledge["scale"]["pages"] >= 1
    assert knowledge["pages"][0]["route"] == "/login"
    assert any("登录" in item["name"] for item in knowledge["features"])
    assert knowledge["apis"]
    assert knowledge["flows"]
    assert knowledge["architecture"]


def test_memory_rejects_unknown_kind():
    memory = ProjectMemoryService()
    try:
        memory.remember(1, 1, kind="not-a-kind", title="x", content="y")
        raise AssertionError("should reject")
    except ValueError as exc:
        assert "未知" in str(exc)


def test_agent_answers_from_index_not_full_rescan():
    indexer = ProjectIndexer()
    items, _ = index_tree(FIXTURE)
    login = [item for item in items if "authenticate" in item["name"] or item["name"] == "LoginPage"]
    assert login

    class FakeIndexer:
        def query_index(self, user_id, project_id, keyword=None, kind=None, path=None, limit=40):
            return [item for item in items if keyword and keyword.lower() in (item["name"] + item["path"]).lower()][:limit]

    class FakeMemory:
        def search(self, *args, **kwargs):
            return [{"kind": "conclusion", "title": "登录定位", "content": "authenticate @ backend/app/services/auth_service.py"}]
        def remember(self, *args, **kwargs):
            return {}

    agent = ProjectAgentService()
    agent.indexer = FakeIndexer()
    agent.memory = FakeMemory()
    agent.assets.create_asset = lambda *args, **kwargs: {"id": 1, "name": "登录 测试点", "stage_name": "测试设计"}
    result = agent.ask(1, 1, "登录功能在哪里？", workspace="understand")
    assert "auth_service.py" in result["answer"] or any("auth_service.py" in (h.get("path") or "") for h in result["locations"])
    assert "没有重新扫描整个仓库" in result["answer"]
    design = agent.ask(1, 1, "帮我设计登录测试", workspace="design")
    assert design["memory_used"]
    assert "登录定位" in design["answer"] or design["actions"]


def test_index_and_memory_isolated_by_user_and_project(tmp_path, monkeypatch):
    import os
    import sys
    import importlib
    import pkgutil

    os.environ.setdefault("USE_SQLITE", "True")
    os.environ.setdefault("AUTH_REQUIRED", "True")
    backend_dir = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(backend_dir))

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from app.core.auth import create_access_token, hash_password
    from app.db.database import Base, get_db
    from app.models.user import User, UserRole
    from app.models.team import Organization, OrganizationMember, OrgRole, Project, ProjectMember, ProjectRole
    import app.models as models_pkg

    for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
        if not modname.startswith("_"):
            importlib.import_module(f"app.models.{modname}")

    engine = create_engine(f"sqlite:///{tmp_path / 'explorer.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    import app.api.project_explorer as explorer_api
    import app.services.project_indexer as indexer_mod
    import app.services.project_memory as memory_mod
    import app.services.workspace_service as workspace_svc

    monkeypatch.setattr(explorer_api, "SessionLocal", Session)
    monkeypatch.setattr(indexer_mod, "SessionLocal", Session)
    monkeypatch.setattr(memory_mod, "SessionLocal", Session)
    if hasattr(workspace_svc, "SessionLocal"):
        monkeypatch.setattr(workspace_svc, "SessionLocal", Session, raising=False)

    app = FastAPI()
    app.include_router(explorer_api.router, prefix="/project-explorer")
    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)

    db = Session()
    alice = User(username="alice", email="alice@example.com", hashed_password=hash_password("x"), display_name="alice", role=UserRole.USER, is_active=True)
    bob = User(username="bob", email="bob@example.com", hashed_password=hash_password("x"), display_name="bob", role=UserRole.USER, is_active=True)
    db.add_all([alice, bob])
    db.commit()
    db.refresh(alice)
    db.refresh(bob)
    org_a = Organization(name="A空间", owner_id=alice.id, is_personal=True)
    org_b = Organization(name="B空间", owner_id=bob.id, is_personal=True)
    db.add_all([org_a, org_b])
    db.commit()
    db.refresh(org_a)
    db.refresh(org_b)
    db.add_all([
        OrganizationMember(organization_id=org_a.id, user_id=alice.id, role=OrgRole.OWNER),
        OrganizationMember(organization_id=org_b.id, user_id=bob.id, role=OrgRole.OWNER),
    ])
    proj_a = Project(organization_id=org_a.id, name="A项目", created_by=alice.id, is_default=True)
    proj_b = Project(organization_id=org_b.id, name="B项目", created_by=bob.id, is_default=True)
    db.add_all([proj_a, proj_b])
    db.commit()
    db.refresh(proj_a)
    db.refresh(proj_b)
    db.add_all([
        ProjectMember(project_id=proj_a.id, user_id=alice.id, role=ProjectRole.PROJECT_ADMIN),
        ProjectMember(project_id=proj_b.id, user_id=bob.id, role=ProjectRole.PROJECT_ADMIN),
    ])
    db.commit()
    alice_id, bob_id, proj_a_id, proj_b_id = alice.id, bob.id, proj_a.id, proj_b.id
    db.close()

    indexer = indexer_mod.ProjectIndexer()
    indexed = indexer.import_sample(alice_id, proj_a_id)
    assert indexed["imported"] is True
    assert indexer.query_index(alice_id, proj_a_id, keyword="login")
    assert indexer.query_index(bob_id, proj_a_id, keyword="login") == []
    assert indexer.query_index(alice_id, proj_b_id, keyword="login") == []

    memory = memory_mod.ProjectMemoryService()
    memory.remember(alice_id, proj_a_id, kind="conclusion", title="登录定位", content="auth.py")
    assert memory.snapshot(alice_id, proj_a_id)["conclusions"]
    assert memory.snapshot(bob_id, proj_a_id)["conclusions"] == []
    assert memory.snapshot(alice_id, proj_b_id)["conclusions"] == []

    alice_h = {"Authorization": f"Bearer {create_access_token({'sub': str(alice_id)})}"}
    bob_h = {"Authorization": f"Bearer {create_access_token({'sub': str(bob_id)})}"}
    ok = client.get("/project-explorer/overview", params={"project_id": proj_a_id}, headers=alice_h)
    assert ok.status_code == 200
    forbidden = client.get("/project-explorer/overview", params={"project_id": proj_a_id}, headers=bob_h)
    assert forbidden.status_code == 403
    mem_forbidden = client.get("/project-explorer/memory", params={"project_id": proj_a_id}, headers=bob_h)
    assert mem_forbidden.status_code == 403
