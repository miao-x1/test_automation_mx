"""真实 Playwright：打开本地基础页，完成输入/点击/清空/验证。"""
import os
import sys
from pathlib import Path

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))
os.environ.setdefault("USE_SQLITE", "True")
os.environ.setdefault("APP_ENV", "development")

from playwright.sync_api import expect, sync_playwright

from app.utils.browser_launcher import get_launch_kwargs


def test_basic_web_app_click_type_clear_verify():
    html = backend_dir.parent / "test-fixtures" / "basic-web-app" / "index.html"
    assert html.is_file()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**get_launch_kwargs())
        page = browser.new_page()
        try:
            page.goto(html.as_uri())
            page.get_by_test_id("username").fill("alice")
            page.get_by_test_id("password").fill("pass123")
            page.get_by_test_id("role").select_option("user")
            page.get_by_test_id("notify").check()
            page.get_by_test_id("login-btn").click()
            expect(page.get_by_test_id("login-result")).to_have_text("登录成功")
            page.get_by_test_id("clear-btn").click()
            expect(page.get_by_test_id("username")).to_have_value("")
            page.get_by_test_id("open-modal").click()
            expect(page.get_by_test_id("close-modal")).to_be_visible()
            page.get_by_test_id("close-modal").click()
            page.get_by_test_id("tab-search").click()
            page.get_by_test_id("search").fill("alice")
            page.get_by_test_id("search-btn").click()
            expect(page.get_by_test_id("search-result")).to_contain_text("alice")
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.go_back()
            page.wait_for_timeout(200)
        finally:
            page.close()
            browser.close()
