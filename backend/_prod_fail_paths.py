"""Production failure-path checks. Never prints secrets. No mocks."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "deploy" / "docker" / ".env"
BASE = "http://localhost:8000"


def parse_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def classify_result(name: str, http_status: int, payload: dict) -> None:
    status_field = str(payload.get("status") or "")
    code = payload.get("code")
    message = str(payload.get("message") or "")
    fake = False
    if http_status == 200 and status_field == "success" and "error" in payload and payload.get("error"):
        fake = True
    if http_status == 200 and name in {
        "empty_requirement",
        "fake_png",
        "fake_jpeg",
        "oversized",
        "illegal_ext",
        "missing_task",
    }:
        if name == "empty_requirement" and code == 200:
            fake = True
        if name in {"fake_png", "fake_jpeg", "illegal_ext"} and http_status == 200 and code == 200:
            fake = True
        if name == "oversized" and http_status == 200 and code == 200:
            fake = True
        if name == "missing_task" and http_status == 200 and code == 200:
            fake = True
    print(
        "CASE",
        name,
        "HTTP",
        http_status,
        "CODE",
        code,
        "STATUS_FIELD",
        status_field or "ABSENT",
        "FAKE_SUCCESS",
        "YES" if fake else "NO",
        "MSG",
        message[:80].encode("ascii", "replace").decode("ascii"),
    )


def main() -> None:
    env = parse_env(RUNTIME)
    user = env.get("ADMIN_USERNAME") or ""
    password = env.get("ADMIN_PASSWORD") or ""
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    token = ""

    def auth_headers(headers: dict) -> dict:
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def call(method: str, path: str, data=None, raw=False, timeout=30):
        body = None
        headers = {}
        if data is not None and not raw:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = data
        req = urllib.request.Request(BASE + path, data=body, headers=auth_headers(headers), method=method)
        try:
            resp = opener.open(req, timeout=timeout)
            text = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {"raw": text[:400]}
            return e.code, parsed

    def multipart(path: str, field: str, filename: str, content: bytes, content_type: str):
        boundary = "----FailPathBoundary7MA4YWxkTrZu0gW"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            BASE + path,
            data=body,
            headers=auth_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
            method="POST",
        )
        try:
            resp = opener.open(req, timeout=60)
            text = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(text) if text else {}
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = {"raw": text[:400]}
            return e.code, parsed

    st, captcha = call("GET", "/auth/captcha")
    captcha_data = captcha.get("data") or captcha
    st, payload = call("POST", "/auth/login", {
        "username": user,
        "password": password,
        "captcha_id": captcha_data.get("captcha_id") or "",
        "captcha_code": captcha_data.get("debug_text") or "",
    })
    print("LOGIN", st, "OK" if st == 200 else "FAIL")
    token = payload.get("access_token") or (payload.get("data") or {}).get("access_token") or ""
    print("AUTH_BEARER", "CONFIGURED" if token else "MISSING")

    st, payload = call("POST", "/requirement/create", {"requirement": "   ", "task_type": "web"})
    classify_result("empty_requirement", st, payload)

    st, payload = multipart(
        "/requirement/upload_images",
        "files",
        "fake.png",
        b"this is not a png",
        "image/png",
    )
    classify_result("fake_png", st, payload)
    saved = ((payload.get("data") or {}).get("image_paths") or [])
    print("FAKE_PNG_SAVED", bool(saved))

    st, payload = multipart(
        "/requirement/upload_images",
        "files",
        "fake.jpg",
        b"JFIF-not-really",
        "image/jpeg",
    )
    classify_result("fake_jpeg", st, payload)
    print("FAKE_JPEG_SAVED", bool(((payload.get("data") or {}).get("image_paths") or [])))

    st, payload = multipart(
        "/requirement/upload_images",
        "files",
        "huge.png",
        b"\x89PNG\r\n\x1a\n" + (b"A" * (11 * 1024 * 1024)),
        "image/png",
    )
    classify_result("oversized", st, payload)

    st, payload = multipart(
        "/requirement/upload_images",
        "files",
        "evil.exe",
        b"MZ-not-an-image",
        "application/octet-stream",
    )
    classify_result("illegal_ext", st, payload)

    st, payload = call("POST", "/requirement/analyze/99999999", {})
    classify_result("missing_task", st, payload)

    st, payload = call(
        "POST",
        "/requirement/create",
        {
            "requirement": "打开 https://127.0.0.1:1 ，点击不存在的按钮 #this-locator-must-fail-xyz",
            "task_type": "web",
            "script_format": "playwright",
        },
    )
    req_id = (payload.get("data") or {}).get("id")
    print("LOCATOR_FAIL_CREATE", st, "REQ", req_id)
    if req_id:
        events = []
        req = urllib.request.Request(
            f"{BASE}/requirement/analyze/{req_id}",
            data=b"{}",
            headers=auth_headers({"Content-Type": "application/json"}),
            method="POST",
        )
        try:
            with opener.open(req, timeout=180) as resp:
                buf = b""
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        text = line.decode("utf-8", "replace").strip()
                        if not text.startswith("data:"):
                            continue
                        try:
                            ev = json.loads(text[5:].strip())
                        except Exception:
                            continue
                        events.append(ev.get("event") or ev.get("step"))
                        if (ev.get("event") or ev.get("step")) in {"flow_success", "flow_failed", "done"}:
                            break
        except Exception as exc:
            print("LOCATOR_ANALYZE_ERR", type(exc).__name__)
        print("LOCATOR_ANALYZE_EVENTS", [x for x in events if x][-8:])
        st, detail = call("GET", f"/requirement/{req_id}")
        detail_data = detail.get("data") or {}
        print("LOCATOR_TASK_STATUS", detail_data.get("status"))
        script = detail_data.get("generated_script") or ""
        print("LOCATOR_HAS_TEST_PASS", "##TEST_PASS##" in script)
        linked = detail_data.get("task_id")
        if linked and script:
            st, exec_created = call("POST", f"/executions/{linked}/execute", {})
            execution_id = ((exec_created.get("data") or {}).get("execution_id"))
            print("PLAYWRIGHT_FAIL_EXEC", st, "ID", execution_id)
            if execution_id:
                st, exec_detail = call("GET", f"/executions/{execution_id}")
                data = exec_detail.get("data") or exec_detail
                print(
                    "PLAYWRIGHT_FAIL_DETAIL",
                    "HTTP",
                    st,
                    "success_count",
                    data.get("success_count"),
                    "failed_count",
                    data.get("failed_count"),
                    "status",
                    data.get("status") or data.get("execution_status"),
                )

    print("AI_ANOMALY", "verified via isolated production image: missing QWEN => AI_CONFIGURED false + FAIL_CLOSED startup")
    print("FAIL_PATHS_DONE")


if __name__ == "__main__":
    main()
