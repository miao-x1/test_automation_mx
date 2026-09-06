"""生产启动时的密钥自检：开发可警告，生产必须失败。"""
import os

from app.core.config import settings
from app.core.logger import log

_INSECURE_SECRET_KEYS = {
    "test-automation-secret-key-change-in-production",
    "change-this-to-a-random-secret-key",
    "CHANGE-ME-TO-A-RANDOM-64-CHAR-STRING",
    "dev-secret-key-change-in-production",
    "secret",
    "123456",
    "change-me",
    "dev-secret",
    "changeme",
}

_INSECURE_DB_PASSWORDS = {
    "",
    "magic1212",
    "root",
    "password",
    "123456",
    "admin",
}

_INSECURE_NEO4J_PASSWORDS = {
    "",
    "neo4j",
    "neo4j_secure_password",
    "password",
    "123456",
}

_INSECURE_MINIO = {"minioadmin", "minioadmin123"}


def _collect_production_secret_errors() -> list[str]:
    errors: list[str] = []
    secret = (settings.SECRET_KEY or "").strip()
    if secret in _INSECURE_SECRET_KEYS or len(secret) < 32:
        errors.append("SECRET_KEY（必须至少 32 位随机值，禁止 secret/change-me 等默认值）")

    if not settings.USE_SQLITE:
        if (settings.DB_PASSWORD or "") in _INSECURE_DB_PASSWORDS:
            errors.append("DB_PASSWORD（禁止为空或使用 magic1212/root/password 等默认密码）")

    if (settings.NEO4J_PASSWORD or "") in _INSECURE_NEO4J_PASSWORDS:
        errors.append("NEO4J_PASSWORD（禁止 neo4j / neo4j_secure_password 等默认密码）")

    minio_access = os.getenv("MINIO_ACCESS_KEY", "")
    minio_secret = os.getenv("MINIO_SECRET_KEY", "")
    if minio_access in _INSECURE_MINIO or minio_secret in _INSECURE_MINIO:
        errors.append("MINIO_ACCESS_KEY/MINIO_SECRET_KEY（禁止 minioadmin）")

    if not settings.ai_configured:
        errors.append("QWEN_API_KEY（生产环境必须配置真实 DashScope Key，禁止空值或示例占位）")

    return errors


def assert_production_secrets() -> None:
    if not settings.is_production:
        if settings.SECRET_KEY in _INSECURE_SECRET_KEYS:
            log.warning("当前使用默认 SECRET_KEY，仅可用于本地开发")
        if not settings.ai_configured:
            log.warning("QWEN_API_KEY 未配置：APP 可启动，但 AI_READY=false，Agent/LLM 将返回真实失败")
        return

    errors = _collect_production_secret_errors()
    if errors:
        raise RuntimeError(
            "生产环境拒绝启动：关键 Secret 缺失或仍为默认值。请配置: " + "；".join(errors)
        )
