"""Host-side loop check against the local fixture page. Never prints secrets."""
import json
import os
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

BASE = "http://localhost:8000"
USER = os.environ.get("PROD_E2E_USER", "qa_reviewer_02")
PASSWORD = os.environ.get("PROD_E2E_PASSWORD", "QaReview#2026")
FIXTURE = "http://127.0.0.1:8000/fixtures/basic-web-app/"


def main():
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    bearer = {"token": ""}

    def _auth_headers(headers):
        if bearer["token"]:
            headers["Authorization"] = f"Bearer {bearer['token']}"
        return headers

    def call(method, path, data=None, timeout=30):
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers = _auth_headers(headers)
        req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
        try:
            resp = opener.open(req, timeout=timeout)
            raw_text = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw_text) if raw_text else {}
        except urllib.error.HTTPError as e:
            raw_text = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw_text)
            except Exception:
                parsed = {"raw": raw_text[:800]}
            return e.code, parsed

    def multipart(path, field, filename, content, content_type):
        boundary = "----BasicLoopBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
        req = urllib.request.Request(
            BASE + path,
            data=body,
            headers=_auth_headers({"Content-Type": f"multipart/form-data; boundary={boundary}"}),
            method="POST",
        )
        resp = opener.open(req, timeout=60)
        return resp.status, json.loads(resp.read().decode("utf-8", "replace"))

    def read_sse(path, timeout=240, method="GET", data=None):
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        headers = _auth_headers(headers)
        req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
        events = []
        start = time.time()
        with opener.open(req, timeout=timeout) as resp:
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
                    events.append(ev)
                    evt = ev.get("event") or ev.get("step")
                    print("SSE", evt, ev.get("step_name") or "")
                    if evt in {"flow_success", "flow_failed", "done", "执行完成", "执行异常"}:
                        return events
                if time.time() - start > timeout - 5:
                    print("SSE_TIMEOUT")
                    break
        return events

    fixture = urllib.request.urlopen(FIXTURE, timeout=10).read()
    print("FIXTURE_OK", "基础 UI 测试页面".encode("utf-8") in fixture)

    status, captcha = call("GET", "/auth/captcha")
    captcha_data = captcha.get("data") or captcha
    status, payload = call("POST", "/auth/login", {
        "username": USER,
        "password": PASSWORD,
        "captcha_id": captcha_data.get("captcha_id") or "",
        "captcha_code": captcha_data.get("debug_text") or "",
    })
    print("LOGIN", status)
    if status != 200:
        return
    token = payload.get("access_token") or (payload.get("data") or {}).get("access_token") or ""
    bearer["token"] = token

    status, bad = call("POST", "/requirement/create", {"requirement": "没有地址的测试"})
    print("BAD_URL", status, (bad.get("detail") or bad.get("message") or "")[:80])

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
        b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(FIXTURE, timeout=15000)
            png = page.screenshot(full_page=True)
            browser.close()
        print("FIXTURE_SHOT", "real")
    except Exception as exc:
        print("FIXTURE_SHOT", "fallback", type(exc).__name__)
    status, img = multipart("/requirement/upload_images", "files", "basic.png", png, "image/png")
    image_paths = ((img.get("data") or {}).get("image_paths") or [])
    print("IMG_UPLOAD", status, bool(image_paths))

    req_body = {
        "requirement": f"打开 {FIXTURE} ，在用户名输入 alice，在密码输入 pass123，点击登录，验证出现登录成功。",
        "task_type": "web",
        "script_format": "playwright",
        "image_paths": image_paths,
    }
    status, created = call("POST", "/requirement/create", req_body)
    req_id = ((created.get("data") or {}).get("id"))
    print("CREATE", status, req_id)
    if not req_id:
        return

    events = read_sse(f"/requirement/analyze/{req_id}", timeout=240, method="POST", data={})
    print("ANALYZE_EVENTS", sorted({ev.get("event") for ev in events if ev.get("event")}))
    status, detail = call("GET", f"/requirement/{req_id}")
    detail_data = detail.get("data") or {}
    print("DETAIL_STATUS", detail_data.get("status"))
    print("HAS_ELEMENTS", bool(detail_data.get("page_elements")))
    print("LINKED_TASK_ID", detail_data.get("task_id"))
    script = detail_data.get("generated_script") or ""
    print("SCRIPT_LEN", len(script))
    print("SCRIPT_SNIP", script[:600].replace("\n", " | "))
    print("SCRIPT_HAS_LOGIN", "login-btn" in script or "登录" in script)
    print("SCRIPT_HAS_ASSERT", "登录成功" in script)
    print("SCRIPT_WRONG_SUBMIT", "submit-btn" in script)

    linked = detail_data.get("task_id")
    if linked and script:
        status, exec_created = call("POST", f"/executions/{linked}/execute", {})
        execution_id = ((exec_created.get("data") or {}).get("execution_id"))
        print("EXECUTE_CREATE", status, execution_id)
        if execution_id:
            try:
                exec_events = read_sse(f"/executions/{execution_id}/stream", timeout=150)
            except Exception as exc:
                print("EXEC_SSE_ERR", type(exc).__name__)
                exec_events = []
            print("EXEC_EVENTS", len(exec_events), [ev.get("step") or ev.get("event") for ev in exec_events][-5:])
            status, exec_detail = call("GET", f"/executions/{execution_id}")
            data = exec_detail.get("data") or {}
            print("EXEC_STATUS", data.get("status"), data.get("success_count"), data.get("failed_count"))
            print("EXEC_ERROR", (data.get("error_message") or "")[:200])
    print("BASIC_LOOP_DONE", req_id)


if __name__ == "__main__":
    main()
