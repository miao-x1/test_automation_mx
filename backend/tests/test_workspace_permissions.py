"""团队 / 项目权限与数据隔离。"""
import os
import sys
import tempfile
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("AUTH_REQUIRED", "True")

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.auth import create_access_token, hash_password
from app.db.database import Base, get_db
from app.models.user import User, UserRole
from app.models.team import ProjectRole


def _build_client(tmp_path: Path, monkeypatch):
    import importlib
    import pkgutil
    import app.models as models_pkg

    for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
        if not modname.startswith("_"):
            importlib.import_module(f"app.models.{modname}")

    db_path = tmp_path / "team.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    from app.api.workspace import router as workspace_router
    from app.api.requirement import router as requirement_router
    from app.api import execution as execution_mod
    import app.api.requirement as requirement_mod
    import app.services.workspace_service as workspace_svc

    monkeypatch.setattr(requirement_mod, "SessionLocal", Session)
    monkeypatch.setattr(workspace_svc, "SessionLocal", getattr(workspace_svc, "SessionLocal", Session), raising=False)

    app = FastAPI()
    app.include_router(workspace_router)
    app.include_router(requirement_router, prefix="/requirement")
    app.include_router(execution_mod.router, prefix="/executions")
    app.dependency_overrides[get_db] = override_db

    return TestClient(app), Session


def _user(db, name: str, email: str | None = None) -> User:
    user = User(
        username=name,
        email=email or f"{name}@example.com",
        hashed_password=hash_password("pass123"),
        display_name=name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user: User | int) -> dict:
    user_id = user if isinstance(user, int) else user.id
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


def test_owner_admin_member_and_project_isolation(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    owner = _user(db, "alice")
    tester = _user(db, "bob")
    stranger = _user(db, "carol")
    viewer = _user(db, "dave")
    owner_id, tester_id, stranger_id, viewer_id = owner.id, tester.id, stranger.id, viewer.id
    db.close()

    alice = _auth(owner_id)
    bob = _auth(tester_id)
    carol = _auth(stranger_id)
    dave = _auth(viewer_id)

    ws = client.get("/workspace", headers=alice)
    assert ws.status_code == 200
    default_id = ws.json()["data"]["default_project_id"]
    assert default_id

    team = client.post("/organizations", headers=alice, json={"name": "AI测试团队", "description": "协作"})
    assert team.status_code == 200
    org_id = team.json()["data"]["organization"]["id"]

    shop = client.post("/projects", headers=alice, json={
        "organization_id": org_id,
        "name": "商城系统",
    })
    assert shop.status_code == 200
    shop_id = shop.json()["data"]["id"]

    erp = client.post("/projects", headers=alice, json={
        "organization_id": org_id,
        "name": "ERP系统",
    })
    assert erp.status_code == 200
    erp_id = erp.json()["data"]["id"]

    invite = client.post(f"/organizations/{org_id}/invites", headers=alice, json={
        "email": "bob@example.com",
        "role": "MEMBER",
        "project_id": shop_id,
        "project_role": ProjectRole.TESTER,
    })
    assert invite.status_code == 200
    token = invite.json()["data"]["token"]
    accepted = client.post("/invites/accept", headers=bob, json={"token": token})
    assert accepted.status_code == 200

    client.post(f"/projects/{shop_id}/members", headers=alice, json={
        "username": "dave",
        "role": ProjectRole.VIEWER,
    })

    shop_ok = client.get(f"/projects/{shop_id}", headers=bob)
    assert shop_ok.status_code == 200
    assert shop_ok.json()["data"]["can_run"] is True
    assert shop_ok.json()["data"]["can_admin"] is False

    shop_denied = client.get(f"/projects/{shop_id}", headers=carol)
    assert shop_denied.status_code == 403

    erp_denied = client.get(f"/projects/{erp_id}", headers=bob)
    assert erp_denied.status_code == 403

    delete_denied = client.delete(f"/projects/{shop_id}", headers=bob)
    assert delete_denied.status_code == 403

    member_denied = client.post(f"/projects/{shop_id}/members", headers=bob, json={
        "username": "carol",
        "role": ProjectRole.TESTER,
    })
    assert member_denied.status_code == 403

    created = client.post("/requirement/create", headers=alice, json={
        "requirement": "打开 http://127.0.0.1:8000/fixtures/basic-web-app/ 并登录",
        "project_id": shop_id,
    })
    assert created.status_code == 200
    assert created.json()["data"]["project_id"] == shop_id
    req_id = created.json()["data"]["id"]

    bob_can_see = client.get(f"/requirement/{req_id}", headers=bob)
    assert bob_can_see.status_code == 200

    carol_req = client.get(f"/requirement/{req_id}", headers=carol)
    assert carol_req.status_code == 403

    shop_list = client.get("/requirement/list", headers=bob, params={"project_id": shop_id})
    assert shop_list.status_code == 200
    assert any(item["id"] == req_id for item in shop_list.json()["data"]["items"])

    erp_list = client.get("/requirement/list", headers=alice, params={"project_id": erp_id})
    assert erp_list.status_code == 200
    assert all(item["id"] != req_id for item in erp_list.json()["data"]["items"])

    bob_erp_list = client.get("/requirement/list", headers=bob, params={"project_id": erp_id})
    assert bob_erp_list.status_code == 403

    viewer_create = client.post("/requirement/create", headers=dave, json={
        "requirement": "打开 http://127.0.0.1:8000/fixtures/basic-web-app/ 查看订单",
        "project_id": shop_id,
    })
    assert viewer_create.status_code == 403

    detail = client.get(f"/requirement/{req_id}", headers=alice)
    task_id = detail.json()["data"]["task_id"]
    viewer_exec = client.post(f"/executions/{task_id}/execute", headers=dave)
    assert viewer_exec.status_code == 403
    tester_exec = client.post(f"/executions/{task_id}/execute", headers=bob)
    assert tester_exec.status_code != 403

    org_detail = client.get(f"/organizations/{org_id}", headers=alice)
    assert org_detail.status_code == 200
    roles = {m["username"]: m["role"] for m in org_detail.json()["data"]["members"]}
    assert roles["alice"] == "OWNER"
    assert roles["bob"] == "MEMBER"

    member_create = client.post("/projects", headers=bob, json={
        "organization_id": org_id,
        "name": "会员不能建项目",
    })
    assert member_create.status_code == 403
    client.patch(f"/organizations/{org_id}/members/{tester_id}", headers=alice, json={"role": "ADMIN"})
    admin_create = client.post("/projects", headers=bob, json={
        "organization_id": org_id,
        "name": "管理项目",
    })
    assert admin_create.status_code == 200


def test_auto_bind_default_project(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    user = _user(db, "solo")
    user_id = user.id
    db.close()
    headers = _auth(user_id)

    created = client.post("/requirement/create", headers=headers, json={
        "requirement": "打开 http://127.0.0.1:8000/fixtures/basic-web-app/ 登录",
    })
    assert created.status_code == 200, created.text
    assert created.json()["data"]["project_id"]

    listed = client.get("/requirement/list", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] == 1


def test_create_requires_url_or_screenshot(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    user = _user(db, "visual")
    user_id = user.id
    db.close()
    headers = _auth(user_id)

    empty = client.post("/requirement/create", headers=headers, json={
        "requirement": "检查登录按钮是否可见",
    })
    assert empty.status_code == 400

    with_image = client.post("/requirement/create", headers=headers, json={
        "requirement": "检查登录按钮是否可见",
        "image_paths": ["requirement_images/demo.png"],
    })
    assert with_image.status_code == 200
    assert with_image.json()["data"]["id"]


def test_jobs_pipeline_and_guest_reporter(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    owner = _user(db, "owner")
    reporter = _user(db, "reporter")
    guest = _user(db, "guest")
    outsider = _user(db, "outsider")
    owner_id, reporter_id, guest_id, outsider_id = owner.id, reporter.id, guest.id, outsider.id
    db.close()
    alice = _auth(owner_id)
    report = _auth(reporter_id)
    guest_h = _auth(guest_id)
    other = _auth(outsider_id)

    org = client.post("/organizations", headers=alice, json={"name": "质量团队"}).json()["data"]["organization"]["id"]
    shop = client.post("/projects", headers=alice, json={"organization_id": org, "name": "商城系统"}).json()["data"]["id"]
    erp = client.post("/projects", headers=alice, json={"organization_id": org, "name": "ERP系统"}).json()["data"]["id"]

    client.post(f"/projects/{shop}/members", headers=alice, json={"username": "reporter", "role": "REPORTER"})
    client.post(f"/projects/{shop}/members", headers=alice, json={"username": "guest", "role": "VIEWER"})

    patched = client.patch(f"/organizations/{org}", headers=alice, json={"name": "AI测试团队", "description": "质量协作"})
    assert patched.status_code == 200
    assert patched.json()["data"]["name"] == "AI测试团队"

    created = client.post("/requirement/create", headers=alice, json={
        "requirement": "打开 http://127.0.0.1:8000/fixtures/basic-web-app/ 登录",
        "project_id": shop,
    })
    assert created.status_code == 200
    assert created.json()["data"]["job_id"]

    dash = client.get("/workspace", headers=alice)
    assert dash.status_code == 200
    assert dash.json()["data"]["recent_jobs"]

    jobs = client.get(f"/projects/{shop}/jobs", headers=alice)
    assert jobs.status_code == 200
    job_id = jobs.json()["data"]["items"][0]["id"]

    assert client.get(f"/projects/{shop}/jobs", headers=report).status_code == 200
    assert client.get(f"/projects/{shop}/jobs", headers=guest_h).status_code == 403
    assert client.get(f"/projects/{shop}", headers=guest_h).status_code == 200
    assert client.get(f"/projects/{shop}/jobs", headers=other).status_code == 403
    assert client.get(f"/projects/{erp}/jobs", headers=report).status_code == 403

    pipe = client.post(f"/projects/{shop}/pipelines", headers=report, json={"name": "核心回归", "job_ids": [job_id]})
    assert pipe.status_code == 403
    pipe = client.post(f"/projects/{shop}/pipelines", headers=alice, json={"name": "核心回归", "job_ids": [job_id]})
    assert pipe.status_code == 200
    pipe_id = pipe.json()["data"]["id"]

    run = client.post(f"/projects/{shop}/pipelines/{pipe_id}/run", headers=alice)
    assert run.status_code == 200
    body = run.json()["data"]
    assert body["title"].startswith("Regression #")
    assert body["failed_count"] >= 1
    assert client.post(f"/projects/{shop}/pipelines/{pipe_id}/run", headers=report).status_code == 403
    assert client.post(f"/projects/{erp}/pipelines/{pipe_id}/run", headers=alice).status_code == 404
