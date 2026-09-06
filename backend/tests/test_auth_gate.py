"""鉴权门禁与生产密钥自检。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")
os.environ.setdefault("AUTH_REQUIRED", "True")

from app.core.auth_gate import _is_public
from app.core.config import settings
from app.core.security_checks import _INSECURE_SECRET_KEYS, assert_production_secrets


def test_public_paths():
    assert _is_public("/health", "GET")
    assert _is_public("/api/health", "GET")
    assert _is_public("/ready", "GET")
    assert _is_public("/api/ready", "GET")
    assert _is_public("/auth/login", "POST")
    assert _is_public("/auth/public-config", "GET")
    assert _is_public("/auth/captcha", "GET")
    assert _is_public("/auth/sms/send", "POST")
    assert _is_public("/auth/password/reset", "POST")
    assert _is_public("/docs", "GET")
    assert _is_public("/fixtures/basic-web-app/", "GET")
    assert _is_public("/any", "OPTIONS")
    assert not _is_public("/tasks", "GET")
    assert not _is_public("/api/v1/task/run", "POST")


def test_docs_and_register_follow_env():
    assert settings.docs_enabled is True or settings.ENABLE_DOCS is True
    assert settings.register_enabled is True or settings.ALLOW_REGISTER is True


def test_insecure_keys_listed():
    assert "change-this-to-a-random-secret-key" in _INSECURE_SECRET_KEYS


def test_dev_secret_check_does_not_raise():
    assert_production_secrets()


def test_production_default_secret_fails(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "change-this-to-a-random-secret-key")
    monkeypatch.setattr(settings, "USE_SQLITE", True)
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "a-strong-neo4j-password-32chars!!")
    import pytest
    with pytest.raises(RuntimeError) as exc:
        assert_production_secrets()
    assert "SECRET_KEY" in str(exc.value)


def test_production_default_db_password_fails(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "a-strong-random-secret-key-32chars!!")
    monkeypatch.setattr(settings, "USE_SQLITE", False)
    monkeypatch.setattr(settings, "DB_PASSWORD", "magic1212")
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "a-strong-neo4j-password-32chars!!")
    import pytest
    with pytest.raises(RuntimeError) as exc:
        assert_production_secrets()
    assert "DB_PASSWORD" in str(exc.value)


def test_production_strong_secrets_ok(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "a-strong-random-secret-key-32chars!!")
    monkeypatch.setattr(settings, "USE_SQLITE", True)
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "a-strong-neo4j-password-32chars!!")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "sk-real-dashscope-key-for-prod")
    assert_production_secrets()


def test_production_missing_qwen_key_fails(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "SECRET_KEY", "a-strong-random-secret-key-32chars!!")
    monkeypatch.setattr(settings, "USE_SQLITE", True)
    monkeypatch.setattr(settings, "NEO4J_PASSWORD", "a-strong-neo4j-password-32chars!!")
    monkeypatch.setattr(settings, "QWEN_API_KEY", "")
    import pytest
    with pytest.raises(RuntimeError) as exc:
        assert_production_secrets()
    assert "QWEN_API_KEY" in str(exc.value)


if __name__ == "__main__":
    test_public_paths()
    test_docs_and_register_follow_env()
    test_insecure_keys_listed()
    test_dev_secret_check_does_not_raise()
    print("ok")
