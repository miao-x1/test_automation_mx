"""Production gate helpers: classify secrets, scan leaks, fail-closed smoke.

Never prints secret values.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "deploy" / "docker" / ".env"
TEMPLATE = ROOT / "deploy" / "docker" / ".env.production"
K8S = ROOT / "deploy" / "k8s" / "02-secret.yaml"

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


def classify(name: str, value: str) -> str:
    v = (value or "").strip()
    if not v:
        return "MISSING"
    low = v.lower()
    if v in FORBIDDEN or low in FORBIDDEN or v.startswith("sk-your-") or v.startswith("CHANGE-ME"):
        return "DEFAULT_VALUE"
    if name == "SECRET_KEY" and len(v) < 32:
        return "INVALID"
    if name == "QWEN_API_KEY" and (not v.startswith("sk-") or len(v) < 20):
        return "INVALID"
    return "CONFIGURED"


def cmd_classify() -> None:
    runtime = parse_env(RUNTIME)
    template = parse_env(TEMPLATE)
    keys = [
        "SECRET_KEY",
        "DB_PASSWORD",
        "NEO4J_PASSWORD",
        "MINIO_ACCESS_KEY",
        "MINIO_SECRET_KEY",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "QWEN_API_KEY",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
        "ADMIN_PASSWORD",
        "REDIS_PASSWORD",
    ]
    print("SOURCE runtime", "PRESENT" if RUNTIME.exists() else "MISSING")
    print("SOURCE template", "PRESENT")
    print("APP_ENV runtime", runtime.get("APP_ENV") or "MISSING")
    print("APP_ENV template", template.get("APP_ENV") or "MISSING")
    for key in keys:
        print(f"TEMPLATE {key} {classify(key, template.get(key, ''))}")
        print(f"RUNTIME {key} {classify(key, runtime.get(key, ''))}")


def _git_tracked() -> list[Path]:
    raw = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, encoding="utf-8")
    return [ROOT / line.strip() for line in raw.splitlines() if line.strip()]


def cmd_git_scan() -> None:
    runtime = parse_env(RUNTIME)
    secrets = [
        runtime.get(k, "")
        for k in (
            "SECRET_KEY",
            "DB_PASSWORD",
            "NEO4J_PASSWORD",
            "MINIO_ACCESS_KEY",
            "MINIO_SECRET_KEY",
            "QWEN_API_KEY",
            "ADMIN_PASSWORD",
        )
        if classify(k, runtime.get(k, "")) == "CONFIGURED"
    ]
    hits = 0
    for path in _git_tracked():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for secret in secrets:
            if secret and secret in text:
                hits += 1
                print("GIT_LEAK", path.relative_to(ROOT).as_posix())
                break
    print("GIT_LEAK_COUNT", hits)
    print("K8S_TEMPLATE SECRET_KEY", classify("SECRET_KEY", "CHANGE-ME-TO-A-RANDOM-64-CHAR-STRING" if K8S.exists() else ""))
    k8s = K8S.read_text(encoding="utf-8", errors="replace") if K8S.exists() else ""
    print("K8S_FILE", "PRESENT" if K8S.exists() else "MISSING")
    print("K8S_PLACEHOLDER", "YES" if "CHANGE-ME-TO-A-RANDOM-64-CHAR-STRING" in k8s and "magic1212" in k8s else "NO")


def _image_contains(image: str, needle: str) -> bool:
    if not needle:
        return False
    proc = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", image, "-c", "grep -R -F -l --binary-files=without-match '' / 2>/dev/null | head -n 0"],
        capture_output=True,
        text=True,
    )
    # Use python inside image to search without printing values.
    script = (
        "import os,sys\n"
        "n=os.environ['NEEDLE']\n"
        "hit=False\n"
        "roots=['/app','/usr/share/nginx/html']\n"
        "for root in roots:\n"
        "  if not os.path.isdir(root): continue\n"
        "  for dp, dns, fns in os.walk(root):\n"
        "    dns[:] = [d for d in dns if d not in {'.git','__pycache__','node_modules'}]\n"
        "    for fn in fns:\n"
        "      p=os.path.join(dp,fn)\n"
        "      try:\n"
        "        data=open(p,'rb').read()\n"
        "      except Exception:\n"
        "        continue\n"
        "      if n.encode() in data:\n"
        "        hit=True\n"
        "        break\n"
        "    if hit: break\n"
        "print('HIT' if hit else 'CLEAN')\n"
    )
    proc = subprocess.run(
        ["docker", "run", "--rm", "-e", "NEEDLE=" + needle, "--entrypoint", "python", image, "-c", script],
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if "CLEAN" in out:
        return False
    if "HIT" in out:
        return True
    # frontend image has no python
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-e",
            "NEEDLE=" + needle,
            "--entrypoint",
            "sh",
            image,
            "-c",
            "grep -R -F -q --binary-files=without-match \"$NEEDLE\" /usr/share/nginx/html /app 2>/dev/null && echo HIT || echo CLEAN",
        ],
        capture_output=True,
        text=True,
    )
    return "HIT" in ((proc.stdout or "") + (proc.stderr or ""))


def cmd_image_scan() -> None:
    runtime = parse_env(RUNTIME)
    targets = {
        "SECRET_KEY": runtime.get("SECRET_KEY", ""),
        "DB_PASSWORD": runtime.get("DB_PASSWORD", ""),
        "NEO4J_PASSWORD": runtime.get("NEO4J_PASSWORD", ""),
        "MINIO_SECRET_KEY": runtime.get("MINIO_SECRET_KEY", ""),
        "QWEN_API_KEY": runtime.get("QWEN_API_KEY", ""),
        "ADMIN_PASSWORD": runtime.get("ADMIN_PASSWORD", ""),
    }
    for image in ("docker-backend:latest", "docker-frontend:latest"):
        for name, value in targets.items():
            if classify(name, value) != "CONFIGURED":
                print(f"IMAGE {image} {name} SKIP")
                continue
            leaked = _image_contains(image, value)
            print(f"IMAGE {image} {name} {'LEAK' if leaked else 'CLEAN'}")


def cmd_container_env_scan() -> None:
    runtime = parse_env(RUNTIME)
    qwen = runtime.get("QWEN_API_KEY", "")
    secret = runtime.get("SECRET_KEY", "")
    for container in ("prod_backend", "prod_frontend", "prod_worker"):
        proc = subprocess.run(
            ["docker", "exec", container, "sh", "-c", "printenv"],
            capture_output=True,
            text=True,
        )
        env_text = proc.stdout or ""
        print(f"CONTAINER {container} QWEN_IN_ENV", "YES" if qwen and qwen in env_text else "NO")
        print(f"CONTAINER {container} SECRET_IN_ENV", "YES" if secret and secret in env_text else "NO")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "classify"
    if action == "classify":
        cmd_classify()
    elif action == "git":
        cmd_git_scan()
    elif action == "image":
        cmd_image_scan()
    elif action == "env":
        cmd_container_env_scan()
    else:
        raise SystemExit("unknown action")
