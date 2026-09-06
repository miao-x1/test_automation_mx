"""Phase 3 real-path API E2E: login, upload, analyze SSE, execute Playwright SSE."""
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


def main():
    cj = CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    bearer = {"token": ""}

    def _auth_headers(headers):
        if bearer["token"]:
            headers["Authorization"] = f"Bearer {bearer['token']}"
        return headers

    def call(method, path, data=None, timeout=30, raw=False):
        body = None
        headers = {}
        if data is not None and not raw:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = data
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
        boundary = "----Phase3Boundary7MA4YWxkTrZu0gW"
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
        try:
            resp = opener.open(req, timeout=60)
            raw_text = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(raw_text) if raw_text else {}
        except urllib.error.HTTPError as e:
            raw_text = e.read().decode("utf-8", "replace")
            try:
                parsed = json.loads(raw_text)
            except Exception:
                parsed = {"raw": raw_text[:800]}
            return e.code, parsed

    def read_sse(path, timeout=300, method="GET", data=None):
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
                    msg = (ev.get("error") or ev.get("message") or "")[:160]
                    print("SSE", evt, ev.get("step_name") or "", msg.encode("ascii", "replace").decode("ascii"))
                    if evt in {"flow_success", "flow_failed", "done", "执行完成", "执行异常"}:
                        return events
                if time.time() - start > timeout - 5:
                    print("SSE_TIMEOUT")
                    break
        return events

    status, captcha = call("GET", "/auth/captcha")
    captcha_data = captcha.get("data") or captcha
    status, payload = call("POST", "/auth/login", {
        "username": USER,
        "password": PASSWORD,
        "captcha_id": captcha_data.get("captcha_id") or "",
        "captcha_code": captcha_data.get("debug_text") or "",
    })
    print("LOGIN", status, payload.get("message") or payload)
    if status != 200:
        return
    token = payload.get("access_token") or (payload.get("data") or {}).get("access_token") or ""
    bearer["token"] = token
    print("AUTH_BEARER", "CONFIGURED" if token else "MISSING")

    doc = json.dumps({
        "openapi": "3.0.0",
        "info": {"title": "phase3-e2e", "version": "1.0.0"},
        "paths": {"/health": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }, ensure_ascii=False).encode("utf-8")
    status, uploaded = multipart(
        "/requirement/upload_document", "file", "phase3-e2e.json", doc, "application/json"
    )
    print("DOC_UPLOAD", status, uploaded)
    document_path = ((uploaded.get("data") or {}).get("document_path") or "")

    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc``\x00\x00"
        b"\x00\x04\x00\x01\xf6\x178U\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    host_png = None
    preferred = Path(r"C:\ui-automation\data\uploads\requirement_images\baidu_home.png")
    if preferred.exists():
        host_png = preferred
    else:
        for candidate in [
            Path(r"C:\ui-automation\data\uploads\requirement_images"),
            Path(r"C:\ui-automation\backend\data\uploads\requirement_images"),
        ]:
            if candidate.exists():
                found = list(candidate.glob("*.png"))
                if found:
                    host_png = found[0]
                    break
    if host_png:
        png = host_png.read_bytes()
        print("IMAGE_SOURCE", host_png)
    status, img = multipart(
        "/requirement/upload_images", "files", "phase3-e2e.png", png, "image/png"
    )
    print("IMG_UPLOAD", status, img)
    image_paths = ((img.get("data") or {}).get("image_paths") or [])

    req_body = {
        "requirement": "打开 https://www.baidu.com ，在搜索框输入自动化测试，点击搜索按钮，验证结果页出现。",
        "task_type": "web",
        "script_format": "playwright",
        "document_paths": [document_path] if document_path else [],
        "image_paths": image_paths,
    }
    status, created = call("POST", "/requirement/create", req_body)
    print("CREATE", status, created)
    data = created.get("data") or created
    req_id = data.get("id")
    if not req_id:
        print("NO_TASK")
        return

    events = read_sse(f"/requirement/analyze/{req_id}", timeout=300, method="POST", data={})
    analyze_events = {ev.get("event") for ev in events}
    print("ANALYZE_EVENTS", sorted(x for x in analyze_events if x))

    status, detail = call("GET", f"/requirement/{req_id}")
    detail_data = detail.get("data") or {}
    print("DETAIL_STATUS", status, detail_data.get("status"))
    print("DOCUMENT_PATHS", detail_data.get("document_paths"))
    print("IMAGE_PATHS", detail_data.get("image_paths"))
    print("LINKED_TASK_ID", detail_data.get("task_id"))
    script = detail_data.get("generated_script") or ""
    print("SCRIPT_LEN", len(script))
    print("HAS_TODO", "TODO_REPLACE" in script)
    print("HAS_EMPTY_LOCATOR", 'page.locator("")' in script or "page.locator('')" in script)
    print("HAS_GET_BY", "get_by_" in script)
    print("SCRIPT_HEAD")
    print(script[:600])

    linked_task_id = detail_data.get("task_id")
    if linked_task_id and script:
        status, exec_created = call("POST", f"/executions/{linked_task_id}/execute", {})
        print("EXECUTE_CREATE", status, exec_created)
        execution_id = ((exec_created.get("data") or {}).get("execution_id"))
        if execution_id:
            exec_events = read_sse(f"/executions/{execution_id}/stream", timeout=180)
            print("EXEC_EVENTS", len(exec_events))
            status, exec_detail = call("GET", f"/executions/{execution_id}")
            print("EXEC_DETAIL", status, exec_detail)
        else:
            print("NO_EXECUTION_ID")
    else:
        print("SKIP_EXECUTE", "no linked task or empty script")

    if document_path:
        status, again = call("GET", f"/requirement/{req_id}")
        docs = ((again.get("data") or {}).get("document_paths") or [])
        print("DOC_REF_AFTER_GET", docs)
        print("DOC_REF_OK", document_path in docs)

    print("E2E_DONE", "req_id", req_id, "events", len(events))


if __name__ == "__main__":
    main()
