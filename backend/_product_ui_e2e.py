"""Restore-acceptance: workspace -> first-version test platform.

Reads ADMIN_* from deploy/docker/.env. Never prints secrets.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = "http://127.0.0.1:3000"
FIXTURE = "http://127.0.0.1:8000/fixtures/basic-web-app/"
BAD_URL = "http://no-such-host-ui-e2e.invalid/"
BTN = lambda text: re.compile(text)


def _env() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (ROOT / "deploy" / "docker" / ".env").read_text(encoding="utf-8", errors="replace").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        key, _, val = raw.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def _login(page: Page, user: str, password: str) -> None:
    cap = page.request.get(f"{FRONTEND}/api/auth/captcha")
    cap_data = (cap.json() or {}).get("data") or {}
    if not cap_data.get("debug_text") or not cap_data.get("captcha_id"):
        raise SystemExit("captcha debug_text missing")
    login = page.request.post(
        f"{FRONTEND}/api/auth/login",
        headers={"Content-Type": "application/json"},
        data=json.dumps({
            "username": user,
            "password": password,
            "captcha_id": cap_data["captcha_id"],
            "captcha_code": cap_data["debug_text"],
        }),
    )
    profile = ((login.json() or {}).get("data") or {}).get("user")
    if login.status != 200 or not profile:
        raise SystemExit(f"login failed status={login.status}")
    page.goto(f"{FRONTEND}/auth/login")
    page.evaluate(
        "user => sessionStorage.setItem('test_automation_user', JSON.stringify(user))",
        profile,
    )


def _click_btn(page: Page, pattern: str, timeout: int = 15000):
    page.locator("button").filter(has_text=BTN(pattern)).first.click(timeout=timeout)


def main() -> None:
    creds = _env()
    user = creds.get("ADMIN_USERNAME") or ""
    password = creds.get("ADMIN_PASSWORD") or ""
    if not user or not password:
        raise SystemExit("ADMIN credentials MISSING")

    stamp = time.strftime("%H%M%S")
    org_a = f"恢复团队A{stamp}"
    org_b = f"恢复团队B{stamp}"
    project_a = f"恢复项目A{stamp}"
    project_b = f"恢复项目B{stamp}"
    task_a = f"恢复任务A{stamp}"
    result = {
        "login": False,
        "workspace": False,
        "organization": False,
        "project": False,
        "first_version_platform": False,
        "create_test": False,
        "agent_analyze": False,
        "playwright_execute": False,
        "sse": False,
        "result_view": False,
        "assets": False,
        "profile": False,
        "isolation": False,
        "fail_scenario": False,
        "fake_success": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(20000)
        _login(page, user, password)
        page.goto(f"{FRONTEND}/workspace")
        page.get_by_text("工作空间").first.wait_for()
        result["login"] = True
        result["workspace"] = True

        _click_btn(page, r"创\s*建\s*团\s*队")
        page.get_by_placeholder("例如：AI 测试团队").fill(org_a)
        page.locator(".ant-modal").locator("button").filter(has_text=BTN(r"^创\s*建$")).click()
        page.wait_for_url("**/workspace/org/**", timeout=20000)
        page.get_by_text(org_a).first.wait_for()
        result["organization"] = True

        _click_btn(page, r"创\s*建\s*项\s*目")
        page.get_by_placeholder("例如：商城系统").fill(project_a)
        page.locator(".ant-modal").locator("button").filter(has_text=BTN(r"^创\s*建$")).click()
        page.wait_for_url("**/dashboard", timeout=20000)
        page.get_by_text("开始测试").first.wait_for()
        page.get_by_text("智能自动化测试平台").first.wait_for()
        result["project"] = True
        result["first_version_platform"] = True

        page.get_by_text("开始测试").first.click()
        page.wait_for_url("**/task/create", timeout=15000)
        page.get_by_placeholder("输入任务名称，例如：商城核心流程测试").fill(task_a)
        page.get_by_text("URL地址").click()
        page.get_by_placeholder("https://example.com").fill(FIXTURE)
        _click_btn(page, r"开\s*始\s*智\s*能\s*测\s*试")
        result["create_test"] = True
        page.get_by_text("AI 实时分析").wait_for()
        page.get_by_text(re.compile(r"需求解析|测试类型识别|页面识别|用例生成|脚本生成")).first.wait_for()
        result["sse"] = True
        try:
            page.get_by_text(re.compile(r"生成结果|AI 分析完成|已生成")).first.wait_for(timeout=360000)
            result["agent_analyze"] = True
        except Exception:
            body = page.inner_text("body")
            result["agent_analyze"] = "生成结果" in body or "脚本已生成" in body
        page.screenshot(path=str(Path(__file__).with_name("_product_ui_e2e.png")), full_page=True)

        if page.get_by_text("查看任务详情").count():
            page.get_by_text("查看任务详情").click()
            page.wait_for_timeout(2000)
            match = re.search(r"/task/(\d+)", page.url)
            linked = None
            if match:
                result["requirement_id"] = match.group(1)
                payload = page.evaluate(
                    """async (id) => {
                      const res = await fetch('/api/requirement/' + id, { credentials: 'include' });
                      return await res.json();
                    }""",
                    match.group(1),
                )
                linked = ((payload or {}).get("data") or {}).get("task_id")
            result["linked_task_id"] = linked
            if linked:
                page.goto(f"{FRONTEND}/task/{linked}")
                page.wait_for_timeout(2500)
            exec_btn = page.locator("button").filter(has_text=re.compile(r"开\s*始\s*执\s*行|执\s*行"))
            result["execute_btn"] = exec_btn.count()
            if exec_btn.count():
                exec_btn.first.click()
                result["playwright_execute"] = True
                try:
                    page.get_by_text(re.compile(r"成功|失败|执行完成|执行异常")).first.wait_for(timeout=180000)
                except Exception:
                    pass
            body = page.inner_text("body")
            result["task_page_url"] = page.url
            result["result_view"] = any(token in body for token in ["成功", "失败", "执行", "日志", "截图", "报告"])
            result["fake_success"] = "测试完成 100%" in body and "失败" not in body

        page.goto(f"{FRONTEND}/dashboard")
        if page.url.endswith("/workspace"):
            page.get_by_text(project_a).first.click()
            page.wait_for_url("**/dashboard", timeout=15000)
        page.goto(f"{FRONTEND}/asset")
        page.get_by_text(re.compile(r"测试资产|用例资产|资产列表")).first.wait_for()
        result["assets"] = True

        page.goto(f"{FRONTEND}/profile")
        page.get_by_text(re.compile(r"个人中心|修改密码|用户信息|统计")).first.wait_for()
        result["profile"] = True

        page.goto(f"{FRONTEND}/task/create")
        page.get_by_placeholder("输入任务名称，例如：商城核心流程测试").fill(f"失败任务{stamp}")
        page.get_by_text("URL地址").click()
        page.get_by_placeholder("https://example.com").fill(BAD_URL)
        _click_btn(page, r"开\s*始\s*智\s*能\s*测\s*试")
        deadline = time.time() + 240
        fail_body = ""
        while time.time() < deadline:
            fail_body = page.inner_text("body")
            if any(token in fail_body for token in ["失败", "错误", "无法", "ERR_", "未完成", "NAME_NOT_RESOLVED"]):
                break
            page.wait_for_timeout(3000)
        result["fail_scenario"] = (
            "测试完成 100%" not in fail_body
            and any(token in fail_body for token in ["失败", "错误", "无法", "ERR_", "未完成", "NAME_NOT_RESOLVED"])
        )
        page.screenshot(path=str(Path(__file__).with_name("_product_ui_e2e_fail.png")), full_page=True)

        page.goto(f"{FRONTEND}/workspace")
        _click_btn(page, r"创\s*建\s*团\s*队")
        page.get_by_placeholder("例如：AI 测试团队").fill(org_b)
        page.locator(".ant-modal").locator("button").filter(has_text=BTN(r"^创\s*建$")).click()
        page.wait_for_url("**/workspace/org/**", timeout=20000)
        _click_btn(page, r"创\s*建\s*项\s*目")
        page.get_by_placeholder("例如：商城系统").fill(project_b)
        page.locator(".ant-modal").locator("button").filter(has_text=BTN(r"^创\s*建$")).click()
        page.wait_for_url("**/dashboard", timeout=20000)
        page.goto(f"{FRONTEND}/task")
        page.wait_for_timeout(2500)
        task_body = page.inner_text("body")
        result["isolation"] = task_a not in task_body
        browser.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    required = (
        "login", "workspace", "organization", "project", "first_version_platform",
        "create_test", "agent_analyze", "sse", "assets", "profile", "fail_scenario", "isolation",
        "playwright_execute", "result_view",
    )
    if result["fake_success"]:
        raise SystemExit("UI_E2E_FAKE_SUCCESS")
    if not all(result[k] for k in required):
        raise SystemExit("UI_E2E_INCOMPLETE")
    print("UI_E2E_OK")


if __name__ == "__main__":
    main()
