"""Create gitignored deploy/docker/.env from local configured sources + generated values.

Never prints secret values. Never writes to git-tracked files.
"""
from __future__ import annotations

import secrets
import string
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = Path(__file__).resolve().parent / ".env.production"
RUNTIME = Path(__file__).resolve().parent / ".env"
ROOT_ENV = ROOT / ".env"

FORBIDDEN = {
    "CHANGE-ME-TO-A-RANDOM-64-CHAR-STRING",
    "change-this-to-a-random-secret-key",
    "CHANGE-ME",
    "change-me",
    "changeme",
    "magic1212",
    "password",
    "neo4j",
    "neo4j_secure_password",
    "minioadmin",
    "minioadmin123",
    "sk-your-dashscope-api-key",
    "sk-your-deepseek-api-key",
    "sk-your-openai-api-key",
    "test-automation-secret-key-change-in-production",
    "dev-secret-key-change-in-production",
    "secret",
    "123456",
    "admin",
    "root",
}


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def usable(name: str, value: str) -> bool:
    v = (value or "").strip()
    if not v or v in FORBIDDEN or v.lower() in FORBIDDEN:
        return False
    if v.startswith("sk-your-") or v.startswith("CHANGE-ME"):
        return False
    if name == "SECRET_KEY" and len(v) < 32:
        return False
    if name == "QWEN_API_KEY" and (not v.startswith("sk-") or len(v) < 20):
        return False
    return True


def rand_token(n: int = 48) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def main() -> None:
    template = parse_env(TEMPLATE)
    root = parse_env(ROOT_ENV)
    merged = dict(template)

    secret = root.get("SECRET_KEY", "")
    merged["SECRET_KEY"] = secret if usable("SECRET_KEY", secret) else rand_token(64)
    merged["APP_ENV"] = "production"
    merged["DEBUG"] = "False"
    merged["USE_SQLITE"] = "False"
    merged["ENABLE_MCP"] = "False"
    merged["ALLOW_REGISTER"] = "True"
    merged["ENABLE_DOCS"] = "False"
    merged["AUTH_REQUIRED"] = "True"
    merged["COOKIE_SECURE"] = "False"

    merged["DB_PASSWORD"] = rand_token(32)
    merged["NEO4J_PASSWORD"] = rand_token(32)
    merged["MINIO_ACCESS_KEY"] = "prod" + rand_token(16)
    merged["MINIO_SECRET_KEY"] = rand_token(40)

    qwen = root.get("QWEN_API_KEY", "")
    if not usable("QWEN_API_KEY", qwen):
        raise SystemExit("QWEN_API_KEY source is MISSING/INVALID/DEFAULT_VALUE; cannot materialize production env")
    merged["QWEN_API_KEY"] = qwen

    deepseek = root.get("DEEPSEEK_API_KEY", "")
    merged["DEEPSEEK_API_KEY"] = deepseek if usable("DEEPSEEK_API_KEY", deepseek) else ""
    merged["OPENAI_API_KEY"] = ""

    merged["ADMIN_USERNAME"] = "prod_gate_admin"
    merged["ADMIN_PASSWORD"] = rand_token(20)
    merged["CORS_ORIGINS"] = "http://localhost,http://127.0.0.1"

    lines = [
        "# Runtime-only production env. Generated locally. Do not commit.",
        f"APP_ENV={merged['APP_ENV']}",
    ]
    skip_header = True
    for key, value in merged.items():
        if key == "APP_ENV":
            continue
        lines.append(f"{key}={value}")
    RUNTIME.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("WROTE", str(RUNTIME))
    print("SECRET_KEY", "CONFIGURED" if usable("SECRET_KEY", merged["SECRET_KEY"]) else "INVALID")
    print("DB_PASSWORD", "CONFIGURED")
    print("NEO4J_PASSWORD", "CONFIGURED")
    print("MINIO_ACCESS_KEY", "CONFIGURED")
    print("MINIO_SECRET_KEY", "CONFIGURED")
    print("QWEN_API_KEY", "CONFIGURED")
    print("ADMIN_USERNAME", "CONFIGURED")
    print("APP_ENV", merged["APP_ENV"])
    _ = skip_header


if __name__ == "__main__":
    main()
