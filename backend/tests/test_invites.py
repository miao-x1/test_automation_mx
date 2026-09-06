"""邀请：正常 / 重复 / 已加入 / 不存在用户 / 过期 / 拒绝 / 取消。"""
import os
import sys
from datetime import datetime, timedelta
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
from app.models.team import OrganizationInvite
from app.models.user import User, UserRole


def _build_client(tmp_path: Path, monkeypatch):
    import importlib
    import pkgutil
    import app.models as models_pkg

    for _, modname, _ in pkgutil.iter_modules(models_pkg.__path__):
        if not modname.startswith("_"):
            importlib.import_module(f"app.models.{modname}")

    db_path = tmp_path / "invite.db"
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

    app = FastAPI()
    app.include_router(workspace_router)
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


def _auth(user_id: int) -> dict:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user_id)})}"}


def test_invite_lifecycle(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    owner = _user(db, "owner")
    member = _user(db, "member")
    other = _user(db, "other")
    owner_id, member_id, other_id = owner.id, member.id, other.id
    db.close()

    owner_h = _auth(owner_id)
    member_h = _auth(member_id)
    other_h = _auth(other_id)

    org = client.post("/organizations", headers=owner_h, json={"name": "AI测试团队", "avatar": "https://example.com/a.png"})
    assert org.status_code == 200
    org_id = org.json()["data"]["organization"]["id"]
    assert org.json()["data"]["organization"]["my_role"] == "OWNER"
    assert org.json()["data"]["organization"]["member_count"] == 1

    # 正常邀请未注册邮箱：不伪造成功加入，只生成邀请
    ghost = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "nobody@example.com"})
    assert ghost.status_code == 200
    assert ghost.json()["data"]["token"]

    invite = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "member@example.com"})
    assert invite.status_code == 200
    token = invite.json()["data"]["token"]

    dup = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "member@example.com"})
    assert dup.status_code == 400
    assert "未使用的邀请" in dup.json()["detail"]

    peek = client.get(f"/invites/{token}", headers=member_h)
    assert peek.status_code == 200
    assert peek.json()["data"]["status"] == "pending"

    accepted = client.post("/invites/accept", headers=member_h, json={"token": token})
    assert accepted.status_code == 200

    again_member = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "member@example.com"})
    assert again_member.status_code == 400
    assert "已在团队中" in again_member.json()["detail"]

    listed = client.get(f"/organizations/{org_id}/invites", headers=owner_h)
    assert listed.status_code == 200
    assert any(item["status"] == "accepted" for item in listed.json()["data"]["items"])

    # 邮箱不一致不能接受
    mismatch = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "member@example.com"})
    assert mismatch.status_code == 400

    fresh = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "other@example.com"})
    assert fresh.status_code == 200
    wrong = client.post("/invites/accept", headers=member_h, json={"token": fresh.json()["data"]["token"]})
    assert wrong.status_code == 403

    # 拒绝
    declined_token = fresh.json()["data"]["token"]
    declined = client.post("/invites/decline", headers=other_h, json={"token": declined_token})
    assert declined.status_code == 200
    after_decline = client.post("/invites/accept", headers=other_h, json={"token": declined_token})
    assert after_decline.status_code == 400

    # 取消
    cancelable = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "cancelme@example.com"})
    invite_id = None
    listed = client.get(f"/organizations/{org_id}/invites", headers=owner_h).json()["data"]["items"]
    for item in listed:
        if item["email"] == "cancelme@example.com":
            invite_id = item["id"]
            cancel_token = item["token"]
    assert invite_id
    assert client.delete(f"/organizations/{org_id}/invites/{invite_id}", headers=owner_h).status_code == 200
    assert client.post("/invites/accept", headers=other_h, json={"token": cancel_token}).status_code == 400

    # 过期
    expired = client.post(f"/organizations/{org_id}/invites", headers=owner_h, json={"email": "late@example.com"})
    expired_token = expired.json()["data"]["token"]
    db = Session()
    row = db.query(OrganizationInvite).filter(OrganizationInvite.token == expired_token).first()
    row.expires_at = datetime.now() - timedelta(days=1)
    db.commit()
    db.close()
    late_user = client.post("/organizations", headers=other_h, json={"name": "无关"})
    assert late_user.status_code == 200
    expired_accept = client.post("/invites/accept", headers=_auth(other_id), json={"token": expired_token})
    # other@example.com 与 late@example.com 不一致，先应邮箱校验或过期
    assert expired_accept.status_code in {400, 403}

    db = Session()
    late = _user(db, "late", "late@example.com")
    late_id = late.id
    db.close()
    expired_accept = client.post("/invites/accept", headers=_auth(late_id), json={"token": expired_token})
    assert expired_accept.status_code == 400
    assert "过期" in expired_accept.json()["detail"]


def test_member_cannot_see_unauthorized_org_projects(tmp_path, monkeypatch):
    client, Session = _build_client(tmp_path, monkeypatch)
    db = Session()
    owner = _user(db, "alice")
    bob = _user(db, "bob")
    owner_id, bob_id = owner.id, bob.id
    db.close()
    alice = _auth(owner_id)
    bob_h = _auth(bob_id)

    org_id = client.post("/organizations", headers=alice, json={"name": "隔离团队"}).json()["data"]["organization"]["id"]
    shop = client.post("/projects", headers=alice, json={"organization_id": org_id, "name": "商城系统"}).json()["data"]["id"]
    client.post("/projects", headers=alice, json={"organization_id": org_id, "name": "支付系统"})
    token = client.post(f"/organizations/{org_id}/invites", headers=alice, json={
        "email": "bob@example.com",
        "project_id": shop,
        "project_role": "TESTER",
    }).json()["data"]["token"]
    assert client.post("/invites/accept", headers=bob_h, json={"token": token}).status_code == 200
    detail = client.get(f"/organizations/{org_id}", headers=bob_h)
    names = [p["name"] for p in detail.json()["data"]["projects"]]
    assert "商城系统" in names
    assert "支付系统" not in names
