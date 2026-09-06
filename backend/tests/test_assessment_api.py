"""效能测评 API：项目隔离、权限、真实采集可注入。"""
import os
import sys
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


def _fake_collect(url: str):
    return {
        "page": {
            "ttfb_ms": 120,
            "dom_ready_ms": 800,
            "load_complete_ms": 1400,
            "fcp_ms": 900,
            "lcp_ms": 1500,
        },
        "network": {
            "total_requests": 6,
            "failed_requests": [],
            "avg_duration_ms": 80,
            "by_resource_type": {"script": {"count": 2, "duration_ms": 200}},
            "slowest_requests": [],
        },
    }


def _build_client(tmp_path: Path, monkeypatch):
    import importlib
    import pkgutil
    import app.models as models_pkg

    for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
        if not modname.startswith("_"):
            importlib.import_module(f"app.models.{modname}")

    db_path = tmp_path / "assess.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    import app.domains.performance.cdp_collector as cdp
    from app.api.workspace import router as workspace_router
    from app.api.assessment import router as assessment_router

    monkeypatch.setattr(cdp, "collect_browser_performance", _fake_collect)

    app = FastAPI()
    app.include_router(workspace_router)
    app.include_router(assessment_router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), Session


def _user(db, name: str) -> User:
    user = User(
        username=name,
        email=f"{name}@example.com",
        hashed_password=hash_password("pass123"),
        display_name=name,
        role=UserRole.USER,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


def test_assessment_permissions_and_isolation(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    owner = _user(db, "owner")
    tester = _user(db, "tester")
    reporter = _user(db, "reporter")
    viewer = _user(db, "viewer")
    outsider = _user(db, "outsider")
    ids = [owner.id, tester.id, reporter.id, viewer.id, outsider.id]
    db.close()
    owner_h, tester_h, reporter_h, viewer_h, other_h = [_auth(i) for i in ids]

    org = client.post("/organizations", headers=owner_h, json={"name": "质量团队"}).json()["data"]["organization"]["id"]
    shop = client.post("/projects", headers=owner_h, json={"organization_id": org, "name": "商城系统"}).json()["data"]["id"]
    erp = client.post("/projects", headers=owner_h, json={"organization_id": org, "name": "ERP系统"}).json()["data"]["id"]
    client.post(f"/projects/{shop}/members", headers=owner_h, json={"username": "tester", "role": "TESTER"})
    client.post(f"/projects/{shop}/members", headers=owner_h, json={"username": "reporter", "role": "REPORTER"})
    client.post(f"/projects/{shop}/members", headers=owner_h, json={"username": "viewer", "role": "VIEWER"})

    missing = client.post(f"/projects/{shop}/assessments", headers=tester_h, json={"name": "空测评"})
    assert missing.status_code == 400

    created = client.post(f"/projects/{shop}/assessments", headers=tester_h, json={
        "name": "首页效能",
        "target_url": "http://127.0.0.1:8000/fixtures/basic-web-app/",
        "rounds": 1,
    })
    assert created.status_code == 200
    aid = created.json()["data"]["id"]
    assert created.json()["data"]["project_id"] == shop

    reporter_create = client.post(f"/projects/{shop}/assessments", headers=reporter_h, json={
        "name": "记者不能创建",
        "target_url": "http://127.0.0.1:8000/fixtures/basic-web-app/",
    })
    assert reporter_create.status_code == 403

    viewer_list = client.get(f"/projects/{shop}/assessments", headers=viewer_h)
    assert viewer_list.status_code == 403

    other_list = client.get(f"/projects/{shop}/assessments", headers=other_h)
    assert other_list.status_code == 403

    erp_list = client.get(f"/projects/{erp}/assessments", headers=tester_h)
    assert erp_list.status_code == 403

    listed = client.get(f"/projects/{shop}/assessments", headers=reporter_h)
    assert listed.status_code == 200
    assert listed.json()["data"]["items"][0]["id"] == aid

    ran = client.post(f"/projects/{shop}/assessments/{aid}/run", headers=tester_h)
    assert ran.status_code == 200
    data = ran.json()["data"]
    assert data["status"] == "SUCCESS"
    assert data["score_total"] is not None
    assert data["score_page"] == 100
    assert data["score_network"] is None
    assert any("暂不支持" in item or "xhr/fetch" in item for item in (data["report"].get("unsupported") or []))

    reporter_run = client.post(f"/projects/{shop}/assessments/{aid}/run", headers=reporter_h)
    assert reporter_run.status_code == 403

    tester_delete = client.delete(f"/projects/{shop}/assessments/{aid}", headers=tester_h)
    assert tester_delete.status_code == 403

    owner_delete = client.delete(f"/projects/{shop}/assessments/{aid}", headers=owner_h)
    assert owner_delete.status_code == 200
