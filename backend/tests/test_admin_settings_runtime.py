"""P1-5: 后台保存的 Qwen Key 必须注入 settings，不能只写 JSON。"""
import json

from app.core.config import settings


def test_apply_persisted_key_updates_settings(tmp_path, monkeypatch):
    from app.api import admin as admin_mod

    settings_file = tmp_path / "system_settings.json"
    settings_file.write_text(json.dumps({"qwen_api_key": "sk-from-admin-json"}), encoding="utf-8")
    monkeypatch.setattr(admin_mod, "_SETTINGS_FILE", str(settings_file))
    monkeypatch.setattr(settings, "QWEN_API_KEY", "")

    admin_mod.apply_persisted_llm_settings()
    assert settings.QWEN_API_KEY == "sk-from-admin-json"
    assert settings.ai_configured is True


def test_llm_config_reads_runtime_settings(monkeypatch):
    from app.core.llm import _get_llm_config

    monkeypatch.setattr(settings, "QWEN_API_KEY", "sk-runtime-injected")
    cfg = _get_llm_config()
    assert cfg["api_key"] == "sk-runtime-injected"
