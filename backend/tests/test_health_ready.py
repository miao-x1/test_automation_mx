"""P0-5: /health 存活 vs /ready 就绪。"""
from app.api import health as health_mod


async def test_liveness_does_not_probe_dependencies(monkeypatch):
    called = {"db": False, "milvus": False}

    def boom_db():
        called["db"] = True
        raise AssertionError("liveness must not probe database")

    def boom_milvus():
        called["milvus"] = True
        raise AssertionError("liveness must not probe milvus")

    monkeypatch.setattr(health_mod, "check_database", boom_db)
    monkeypatch.setattr(health_mod, "check_milvus", boom_milvus)

    result = await health_mod.health_check()
    assert result.status == "success"
    assert called == {"db": False, "milvus": False}


def test_ready_pass_when_db_and_milvus_ok(monkeypatch):
    monkeypatch.setattr(health_mod, "check_database", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_milvus", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_ai", lambda: {"status": "CONFIGURED"})
    payload = health_mod.build_readiness()
    assert payload["ready"] is True
    assert payload["ai_ready"] is True
    assert payload["checks"]["database"]["status"] == "PASS"
    assert payload["checks"]["milvus"]["status"] == "PASS"
    assert payload["checks"]["ai"]["status"] == "CONFIGURED"


def test_ready_fail_when_db_down(monkeypatch):
    monkeypatch.setattr(health_mod, "check_database", lambda: {"status": "FAIL", "error": "connection refused"})
    monkeypatch.setattr(health_mod, "check_milvus", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_ai", lambda: {"status": "CONFIGURED"})
    payload = health_mod.build_readiness()
    assert payload["ready"] is False
    assert payload["checks"]["database"]["status"] == "FAIL"


def test_ready_fail_when_milvus_down(monkeypatch):
    monkeypatch.setattr(health_mod, "check_database", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_milvus", lambda: {"status": "FAIL", "error": "unreachable"})
    monkeypatch.setattr(health_mod, "check_ai", lambda: {"status": "CONFIGURED"})
    payload = health_mod.build_readiness()
    assert payload["ready"] is False
    assert payload["checks"]["milvus"]["status"] == "FAIL"


def test_ai_missing_is_not_configured(monkeypatch):
    monkeypatch.setattr(health_mod, "check_database", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_milvus", lambda: {"status": "PASS"})
    monkeypatch.setattr(health_mod, "check_ai", lambda: {"status": "NOT_CONFIGURED"})
    payload = health_mod.build_readiness()
    assert payload["checks"]["ai"]["status"] == "NOT_CONFIGURED"
    assert payload["ai_ready"] is False
    # AI 缺失不能伪装成 AI 正常；DB/Milvus 仍决定 ready
    assert payload["ready"] is True


def test_check_ai_reads_settings(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "QWEN_API_KEY", "")
    assert health_mod.check_ai()["status"] == "NOT_CONFIGURED"
    monkeypatch.setattr(settings, "QWEN_API_KEY", "sk-real-dashscope-key")
    assert health_mod.check_ai()["status"] == "CONFIGURED"
