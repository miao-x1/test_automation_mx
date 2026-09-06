"""Launch fixture-page E2E using gitignored runtime credentials. Never prints secrets."""
from __future__ import annotations

import os
import runpy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "deploy" / "docker" / ".env"


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def main() -> None:
    env = parse_env(RUNTIME)
    user = env.get("ADMIN_USERNAME") or ""
    password = env.get("ADMIN_PASSWORD") or ""
    if not user or not password:
        raise SystemExit("ADMIN credentials MISSING in runtime env")
    os.environ["PROD_E2E_USER"] = user
    os.environ["PROD_E2E_PASSWORD"] = password
    print("E2E_USER", "CONFIGURED")
    print("E2E_TARGET", "http://localhost:8000/fixtures/basic-web-app/")
    runpy.run_path(str(Path(__file__).with_name("e2e_basic_loop.py")), run_name="__main__")


if __name__ == "__main__":
    main()
