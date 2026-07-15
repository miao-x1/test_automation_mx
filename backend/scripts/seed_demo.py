#!/usr/bin/env python3
"""
电商演示数据种子脚本

创建完整的电商测试场景演示数据，包括：
  - 演示用户 (admin/admin123)
  - 7 个需求任务 (RequirementTask)
  - 7 个测试任务 (Task)
  - 7 个测试脚本 (Script)
  - 12 条执行记录 (ExecutionRecord)
  - 3 条用户反馈 (Feedback)

特性：
  - 幂等：已存在的数据自动跳过
  - 自包含：所有依赖从 app 包导入
  - 进度输出：每条记录创建时打印日志

用法：
  cd backend
  python scripts/seed_demo.py
"""
import sys
import os
import json
import random
from datetime import datetime, timedelta

# 添加项目根目录到 sys.path（与 migrate_case_asset.py 一致）
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy.orm import noload

from app.db.database import SessionLocal, Base, sync_engine
from app.core.auth import hash_password
from app.models.user import User, UserRole
from app.models.task import Task, TaskStatus, InputMode, TaskType
from app.models.requirement_task import RequirementTask
from app.models.script import Script
from app.models.execution_record import ExecutionRecord
from app.models.feedback import Feedback


# Task 模型使用了 lazy="selectin" 加载多个关联表，
# 如果关联表存在缺失列会导致查询失败。
# 使用 noload 选项避免加载这些关联关系。
TASK_NOLOAD_OPTS = (
    noload(Task.images),
    noload(Task.analysis_result),
    noload(Task.script),
    noload(Task.ui_elements),
    noload(Task.page_elements),
    noload(Task.execution_records),
    noload(Task.test_assets),
)


# =============================================================================
#  演示用户
# =============================================================================

DEMO_USERNAME = "admin"
DEMO_PASSWORD = "admin123"
DEMO_DISPLAY_NAME = "管理员"
DEMO_EMAIL = "admin@shop.demo.com"


# =============================================================================
#  场景定义（7 个电商测试场景）
# =============================================================================

SCENARIOS = [
    # ------------------------------------------------------------------
    # 1. 用户登录
    # ------------------------------------------------------------------
    {
        "name": "测试商城用户登录功能",
        "short": "用户登录",
        "task_type": "web",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "login_test",
        "page_url": "https://shop.demo.com/login",
        "framework": "playwright",
        "platform": "browser",
        "confidence": 0.92,
        "created_at": datetime(2026, 7, 9, 9, 15, 0),
        "requirement": (
            "测试商城用户登录功能。需要覆盖以下场景：\n"
            "1. 正常登录：输入正确的用户名和密码，验证登录成功并跳转到首页\n"
            "2. 空密码登录：只输入用户名不输入密码，验证提示密码不能为空\n"
            "3. 错误密码登录：输入正确用户名和错误密码，验证提示用户名或密码错误\n"
            "4. SQL注入防护：在用户名输入框输入SQL注入语句，验证系统正确拦截\n"
            "目标URL: https://shop.demo.com/login"
        ),
        "cases": [
            {"case_id": 1, "title": "正常登录", "precondition": "用户已注册", "steps": ["输入用户名 testuser", "输入密码 Test@1234", "点击登录按钮"], "expected": "登录成功，跳转到首页，显示欢迎信息"},
            {"case_id": 2, "title": "空密码登录", "precondition": "用户已注册", "steps": ["输入用户名 testuser", "密码留空", "点击登录按钮"], "expected": "提示'密码不能为空'，停留在登录页"},
            {"case_id": 3, "title": "错误密码登录", "precondition": "用户已注册", "steps": ["输入用户名 testuser", "输入错误密码 WrongPass", "点击登录按钮"], "expected": "提示'用户名或密码错误'，停留在登录页"},
            {"case_id": 4, "title": "SQL注入防护", "precondition": "无", "steps": ["在用户名输入框输入 ' OR 1=1 --", "输入任意密码", "点击登录按钮"], "expected": "提示'用户名包含非法字符'，登录失败"},
        ],
        "script": '''import pytest
from playwright.sync_api import Page, expect


class TestShopLogin:
    """商城用户登录功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page):
        self.page = page
        self.page.goto("https://shop.demo.com/login")

    def test_normal_login(self):
        """正常登录：输入正确的用户名和密码"""
        self.page.fill("[data-testid='username']", "testuser")
        self.page.fill("[data-testid='password']", "Test@1234")
        self.page.click("button[data-testid='login-btn']")
        expect(self.page.locator(".welcome-msg")).to_contain_text("欢迎")
        expect(self.page).to_have_url("https://shop.demo.com/")

    def test_empty_password(self):
        """空密码登录：密码留空"""
        self.page.fill("[data-testid='username']", "testuser")
        self.page.click("button[data-testid='login-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("密码不能为空")

    def test_wrong_password(self):
        """错误密码登录"""
        self.page.fill("[data-testid='username']", "testuser")
        self.page.fill("[data-testid='password']", "WrongPass")
        self.page.click("button[data-testid='login-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("用户名或密码错误")

    def test_sql_injection(self):
        """SQL注入防护"""
        self.page.fill("[data-testid='username']", "' OR 1=1 --")
        self.page.fill("[data-testid='password']", "anything")
        self.page.click("button[data-testid='login-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("非法字符")
''',
    },

    # ------------------------------------------------------------------
    # 2. 用户注册
    # ------------------------------------------------------------------
    {
        "name": "测试商城用户注册功能",
        "short": "用户注册",
        "task_type": "web",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "registration_test",
        "page_url": "https://shop.demo.com/register",
        "framework": "playwright",
        "platform": "browser",
        "confidence": 0.88,
        "created_at": datetime(2026, 7, 9, 14, 30, 0),
        "requirement": (
            "测试商城用户注册功能。需要覆盖以下场景：\n"
            "1. 正常注册：填写合法的用户名、邮箱、密码，验证注册成功\n"
            "2. 重复用户名注册：使用已存在的用户名，验证提示用户名已存在\n"
            "3. 弱密码注册：输入少于6位的密码，验证提示密码强度不足\n"
            "4. 邮箱格式校验：输入非法邮箱格式，验证提示邮箱格式不正确\n"
            "目标URL: https://shop.demo.com/register"
        ),
        "cases": [
            {"case_id": 1, "title": "正常注册", "precondition": "用户名未被占用", "steps": ["输入用户名 newuser01", "输入邮箱 newuser01@test.com", "输入密码 NewUser@2024", "点击注册按钮"], "expected": "注册成功，跳转到登录页"},
            {"case_id": 2, "title": "重复用户名注册", "precondition": "用户名 testuser 已存在", "steps": ["输入用户名 testuser", "输入邮箱 newuser02@test.com", "输入密码 NewUser@2024", "点击注册按钮"], "expected": "提示'用户名已存在'"},
            {"case_id": 3, "title": "弱密码注册", "precondition": "无", "steps": ["输入用户名 newuser03", "输入邮箱 newuser03@test.com", "输入密码 123", "点击注册按钮"], "expected": "提示'密码长度不能少于6位'"},
            {"case_id": 4, "title": "邮箱格式校验", "precondition": "无", "steps": ["输入用户名 newuser04", "输入邮箱 invalid-email", "输入密码 NewUser@2024", "点击注册按钮"], "expected": "提示'邮箱格式不正确'"},
        ],
        "script": '''import pytest
from playwright.sync_api import Page, expect


class TestShopRegister:
    """商城用户注册功能测试"""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page):
        self.page = page
        self.page.goto("https://shop.demo.com/register")

    def test_normal_register(self):
        """正常注册"""
        self.page.fill("[data-testid='reg-username']", "newuser01")
        self.page.fill("[data-testid='reg-email']", "newuser01@test.com")
        self.page.fill("[data-testid='reg-password']", "NewUser@2024")
        self.page.click("button[data-testid='register-btn']")
        expect(self.page).to_have_url("https://shop.demo.com/login")

    def test_duplicate_username(self):
        """重复用户名注册"""
        self.page.fill("[data-testid='reg-username']", "testuser")
        self.page.fill("[data-testid='reg-email']", "newuser02@test.com")
        self.page.fill("[data-testid='reg-password']", "NewUser@2024")
        self.page.click("button[data-testid='register-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("用户名已存在")

    def test_weak_password(self):
        """弱密码注册"""
        self.page.fill("[data-testid='reg-username']", "newuser03")
        self.page.fill("[data-testid='reg-email']", "newuser03@test.com")
        self.page.fill("[data-testid='reg-password']", "123")
        self.page.click("button[data-testid='register-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("密码长度")

    def test_invalid_email(self):
        """邮箱格式校验"""
        self.page.fill("[data-testid='reg-username']", "newuser04")
        self.page.fill("[data-testid='reg-email']", "invalid-email")
        self.page.fill("[data-testid='reg-password']", "NewUser@2024")
        self.page.click("button[data-testid='register-btn']")
        expect(self.page.locator(".error-tip")).to_contain_text("邮箱格式")
''',
    },

    # ------------------------------------------------------------------
    # 3. 搜索商品
    # ------------------------------------------------------------------
    {
        "name": "测试商城搜索商品流程",
        "short": "搜索商品",
        "task_type": "web",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "search_product",
        "page_url": "https://shop.demo.com/products",
        "framework": "playwright",
        "platform": "browser",
        "confidence": 0.85,
        "created_at": datetime(2026, 7, 10, 10, 20, 0),
        "requirement": (
            "测试商城搜索商品流程。需要覆盖以下场景：\n"
            "1. 关键词搜索：输入商品关键词，验证搜索结果正确展示\n"
            "2. 空关键词搜索：不输入关键词直接搜索，验证显示全部商品或提示\n"
            "3. 搜索结果排序：按价格排序，验证商品列表正确排序\n"
            "4. 搜索结果分页：翻到第二页，验证分页功能正常\n"
            "目标URL: https://shop.demo.com/products"
        ),
        "cases": [
            {"case_id": 1, "title": "关键词搜索", "precondition": "商品库中有相关商品", "steps": ["在搜索框输入'手机'", "点击搜索按钮", "等待搜索结果加载"], "expected": "搜索结果列表展示包含'手机'的商品"},
            {"case_id": 2, "title": "空关键词搜索", "precondition": "无", "steps": ["搜索框留空", "点击搜索按钮"], "expected": "显示全部商品或提示'请输入搜索关键词'"},
            {"case_id": 3, "title": "搜索结果排序", "precondition": "搜索结果不为空", "steps": ["搜索'手机'", "点击'价格从低到高'排序按钮"], "expected": "商品列表按价格升序排列"},
            {"case_id": 4, "title": "搜索结果分页", "precondition": "搜索结果超过一页", "steps": ["搜索'手机'", "点击第2页按钮"], "expected": "显示第二页的商品列表"},
        ],
        "script": '''import pytest
from playwright.sync_api import Page, expect


class TestShopSearch:
    """商城搜索商品流程测试"""

    BASE_URL = "https://shop.demo.com/products"

    @pytest.fixture(autouse=True)
    def setup(self, page: Page):
        self.page = page
        self.page.goto(self.BASE_URL)

    def test_keyword_search(self):
        """关键词搜索"""
        self.page.fill("[data-testid='search-input']", "手机")
        self.page.click("button[data-testid='search-btn']")
        self.page.wait_for_selector(".product-card")
        cards = self.page.locator(".product-card .product-name")
        for i in range(cards.count()):
            expect(cards.nth(i)).to_contain_text("手机")

    def test_empty_keyword_search(self):
        """空关键词搜索"""
        self.page.click("button[data-testid='search-btn']")
        # 应显示全部商品或提示
        tip = self.page.locator(".search-tip")
        if tip.is_visible():
            expect(tip).to_contain_text("请输入")

    def test_sort_by_price(self):
        """搜索结果按价格排序"""
        self.page.fill("[data-testid='search-input']", "手机")
        self.page.click("button[data-testid='search-btn']")
        self.page.wait_for_selector(".product-card")
        self.page.select_option("[data-testid='sort-select']", "price_asc")
        prices = self.page.locator(".product-card .price")
        price_values = [float(p.text().replace("¥", "")) for p in prices.all()]
        assert price_values == sorted(price_values)

    def test_pagination(self):
        """搜索结果分页"""
        self.page.fill("[data-testid='search-input']", "手机")
        self.page.click("button[data-testid='search-btn']")
        self.page.wait_for_selector(".product-card")
        self.page.click(".pagination .page-next")
        expect(self.page.locator(".pagination .active")).to_contain_text("2")
''',
    },

    # ------------------------------------------------------------------
    # 4. 加入购物车
    # ------------------------------------------------------------------
    {
        "name": "测试商城加入购物车流程",
        "short": "加入购物车",
        "task_type": "web",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "add_to_cart",
        "page_url": "https://shop.demo.com/products",
        "framework": "playwright",
        "platform": "browser",
        "confidence": 0.90,
        "created_at": datetime(2026, 7, 11, 11, 45, 0),
        "requirement": (
            "测试商城加入购物车流程。需要覆盖以下场景：\n"
            "1. 单个商品加入购物车：选择商品点击加入购物车，验证购物车数量增加\n"
            "2. 多个商品加入购物车：依次添加多个商品，验证购物车数量正确\n"
            "3. 重复添加同一商品：多次添加同一商品，验证购物车中数量累加\n"
            "4. 查看购物车：点击购物车图标，验证购物车页面展示正确\n"
            "目标URL: https://shop.demo.com/products"
        ),
        "cases": [
            {"case_id": 1, "title": "单个商品加入购物车", "precondition": "用户已登录", "steps": ["浏览商品列表", "点击第一个商品的'加入购物车'按钮"], "expected": "购物车角标数字变为1，提示'已加入购物车'"},
            {"case_id": 2, "title": "多个商品加入购物车", "precondition": "用户已登录，购物车为空", "steps": ["点击商品A的'加入购物车'", "点击商品B的'加入购物车'"], "expected": "购物车角标数字变为2"},
            {"case_id": 3, "title": "重复添加同一商品", "precondition": "用户已登录", "steps": ["点击商品A的'加入购物车'两次"], "expected": "购物车角标数字变为2，购物车中商品A数量为2"},
            {"case_id": 4, "title": "查看购物车", "precondition": "购物车中有商品", "steps": ["点击页面右上角购物车图标"], "expected": "跳转到购物车页面，展示已添加的商品列表"},
        ],
        "script": '''import pytest
from playwright.sync_api import Page, expect


class TestShopAddToCart:
    """商城加入购物车流程测试"""

    BASE_URL = "https://shop.demo.com/products"

    @pytest.fixture(autouse=True)
    def setup(self, page: Page):
        self.page = page
        # 先登录
        self.page.goto("https://shop.demo.com/login")
        self.page.fill("[data-testid='username']", "testuser")
        self.page.fill("[data-testid='password']", "Test@1234")
        self.page.click("button[data-testid='login-btn']")
        self.page.wait_for_url("**/products")
        self.page.goto(self.BASE_URL)

    def test_add_single_product(self):
        """单个商品加入购物车"""
        self.page.locator(".product-card").first.locator("button.add-to-cart").click()
        expect(self.page.locator(".cart-badge")).to_have_text("1")
        expect(self.page.locator(".toast-msg")).to_contain_text("已加入购物车")

    def test_add_multiple_products(self):
        """多个商品加入购物车"""
        cards = self.page.locator(".product-card button.add-to-cart")
        cards.nth(0).click()
        cards.nth(1).click()
        expect(self.page.locator(".cart-badge")).to_have_text("2")

    def test_add_same_product_twice(self):
        """重复添加同一商品"""
        btn = self.page.locator(".product-card").first.locator("button.add-to-cart")
        btn.click()
        btn.click()
        expect(self.page.locator(".cart-badge")).to_have_text("2")

    def test_view_cart(self):
        """查看购物车"""
        self.page.locator(".product-card").first.locator("button.add-to-cart").click()
        self.page.click("[data-testid='cart-icon']")
        expect(self.page).to_have_url("https://shop.demo.com/cart")
        expect(self.page.locator(".cart-item")).to_have_count(1)
''',
    },

    # ------------------------------------------------------------------
    # 5. 下单支付
    # ------------------------------------------------------------------
    {
        "name": "测试商城下单支付流程",
        "short": "下单支付",
        "task_type": "api",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "checkout_payment",
        "page_url": "https://shop.demo.com/api/orders",
        "framework": "pytest",
        "platform": "server",
        "confidence": 0.82,
        "created_at": datetime(2026, 7, 12, 13, 0, 0),
        "requirement": (
            "测试商城下单支付流程（API接口测试）。需要覆盖以下场景：\n"
            "1. 正常下单：调用POST /api/orders创建订单，验证返回订单ID\n"
            "2. 支付订单：调用POST /api/payment支付订单，验证支付成功\n"
            "3. 库存不足下单：购买数量超过库存，验证返回库存不足错误\n"
            "4. 重复支付：对已支付订单再次支付，验证返回重复支付错误\n"
            "API基础地址: https://shop.demo.com/api"
        ),
        "cases": [
            {"case_id": 1, "title": "正常下单", "precondition": "用户已登录，购物车有商品", "steps": ["POST /api/orders 创建订单", "验证响应状态码200", "验证返回order_id"], "expected": "返回200，包含order_id字段"},
            {"case_id": 2, "title": "支付订单", "precondition": "存在未支付订单", "steps": ["POST /api/payment 支付订单", "验证响应状态码200", "验证支付状态为paid"], "expected": "返回200，status=paid"},
            {"case_id": 3, "title": "库存不足下单", "precondition": "商品库存为10", "steps": ["POST /api/orders 购买数量设为100"], "expected": "返回400，错误信息'库存不足'"},
            {"case_id": 4, "title": "重复支付", "precondition": "订单已支付", "steps": ["POST /api/payment 对已支付订单再次支付"], "expected": "返回400，错误信息'订单已支付'"},
        ],
        "script": '''import pytest
import requests

BASE_URL = "https://shop.demo.com/api"
TOKEN = "demo-token-admin-2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


class TestCheckoutPayment:
    """商城下单支付流程 API 测试"""

    def test_create_order(self):
        """正常下单"""
        resp = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json={
            "product_id": 1001,
            "quantity": 2,
            "address_id": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "order_id" in data
        assert data["status"] == "pending"

    def test_pay_order(self):
        """支付订单"""
        # 先创建订单
        create_resp = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json={
            "product_id": 1001, "quantity": 1, "address_id": 1,
        })
        order_id = create_resp.json()["order_id"]
        # 支付
        pay_resp = requests.post(f"{BASE_URL}/payment", headers=HEADERS, json={
            "order_id": order_id, "method": "alipay",
        })
        assert pay_resp.status_code == 200
        assert pay_resp.json()["status"] == "paid"

    def test_insufficient_stock(self):
        """库存不足下单"""
        resp = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json={
            "product_id": 1001, "quantity": 999999, "address_id": 1,
        })
        assert resp.status_code == 400
        assert "库存不足" in resp.json()["message"]

    def test_duplicate_payment(self):
        """重复支付"""
        # 创建并支付订单
        create_resp = requests.post(f"{BASE_URL}/orders", headers=HEADERS, json={
            "product_id": 1001, "quantity": 1, "address_id": 1,
        })
        order_id = create_resp.json()["order_id"]
        requests.post(f"{BASE_URL}/payment", headers=HEADERS, json={
            "order_id": order_id, "method": "alipay",
        })
        # 再次支付
        resp = requests.post(f"{BASE_URL}/payment", headers=HEADERS, json={
            "order_id": order_id, "method": "alipay",
        })
        assert resp.status_code == 400
        assert "已支付" in resp.json()["message"]
''',
    },

    # ------------------------------------------------------------------
    # 6. 订单查询
    # ------------------------------------------------------------------
    {
        "name": "测试商城订单查询功能",
        "short": "订单查询",
        "task_type": "api",
        "req_status": "completed",
        "task_status": TaskStatus.SUCCESS,
        "intent": "order_query",
        "page_url": "https://shop.demo.com/api/orders",
        "framework": "pytest",
        "platform": "server",
        "confidence": 0.78,
        "created_at": datetime(2026, 7, 13, 15, 30, 0),
        "requirement": (
            "测试商城订单查询功能（API接口测试）。需要覆盖以下场景：\n"
            "1. 查询全部订单：调用GET /api/orders，验证返回订单列表\n"
            "2. 按状态筛选订单：查询status=paid的订单，验证结果筛选正确\n"
            "3. 查询订单详情：调用GET /api/orders/{id}，验证返回订单详情\n"
            "4. 查询不存在的订单：查询不存在的订单ID，验证返回404\n"
            "API基础地址: https://shop.demo.com/api"
        ),
        "cases": [
            {"case_id": 1, "title": "查询全部订单", "precondition": "用户有订单数据", "steps": ["GET /api/orders", "验证响应状态码200", "验证返回订单数组"], "expected": "返回200，包含orders数组"},
            {"case_id": 2, "title": "按状态筛选订单", "precondition": "存在已支付订单", "steps": ["GET /api/orders?status=paid", "验证所有返回订单status为paid"], "expected": "返回200，所有订单status=paid"},
            {"case_id": 3, "title": "查询订单详情", "precondition": "存在订单", "steps": ["GET /api/orders/{order_id}", "验证返回订单详情字段"], "expected": "返回200，包含order_id, items, total等字段"},
            {"case_id": 4, "title": "查询不存在的订单", "precondition": "无", "steps": ["GET /api/orders/99999999"], "expected": "返回404，错误信息'订单不存在'"},
        ],
        "script": '''import pytest
import requests

BASE_URL = "https://shop.demo.com/api"
TOKEN = "demo-token-admin-2026"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}


class TestOrderQuery:
    """商城订单查询功能 API 测试"""

    def test_list_all_orders(self):
        """查询全部订单"""
        resp = requests.get(f"{BASE_URL}/orders", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert "orders" in data
        assert isinstance(data["orders"], list)

    def test_filter_by_status(self):
        """按状态筛选订单"""
        resp = requests.get(f"{BASE_URL}/orders?status=paid", headers=HEADERS)
        assert resp.status_code == 200
        for order in resp.json()["orders"]:
            assert order["status"] == "paid"

    def test_get_order_detail(self):
        """查询订单详情"""
        # 先获取一个订单ID
        list_resp = requests.get(f"{BASE_URL}/orders", headers=HEADERS)
        order_id = list_resp.json()["orders"][0]["order_id"]
        # 查询详情
        resp = requests.get(f"{BASE_URL}/orders/{order_id}", headers=HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert data["order_id"] == order_id
        assert "items" in data
        assert "total" in data

    def test_get_nonexistent_order(self):
        """查询不存在的订单"""
        resp = requests.get(f"{BASE_URL}/orders/99999999", headers=HEADERS)
        assert resp.status_code == 404
        assert "订单不存在" in resp.json()["message"]
''',
    },

    # ------------------------------------------------------------------
    # 7. 商品详情页面（失败场景）
    # ------------------------------------------------------------------
    {
        "name": "测试商城商品详情页面",
        "short": "商品详情页",
        "task_type": "web",
        "req_status": "failed",
        "task_status": TaskStatus.FAILED,
        "intent": "product_detail",
        "page_url": "https://shop.demo.com/products/1001",
        "framework": "playwright",
        "platform": "browser",
        "confidence": 0.76,
        "created_at": datetime(2026, 7, 14, 16, 10, 0),
        "requirement": (
            "测试商城商品详情页面。需要覆盖以下场景：\n"
            "1. 查看商品基本信息：验证商品名称、价格、描述正确展示\n"
            "2. 查看商品图片：验证商品图片轮播功能正常\n"
            "3. 选择商品规格：选择颜色和尺码，验证价格联动更新\n"
            "4. 查看商品评价：验证商品评价列表正确展示\n"
            "目标URL: https://shop.demo.com/products/1001"
        ),
        "cases": [
            {"case_id": 1, "title": "查看商品基本信息", "precondition": "商品存在", "steps": ["访问商品详情页", "验证商品名称展示", "验证商品价格展示"], "expected": "商品名称和价格正确展示"},
            {"case_id": 2, "title": "查看商品图片轮播", "precondition": "商品有多张图片", "steps": ["点击下一张图片按钮", "验证图片切换"], "expected": "图片轮播正常切换"},
            {"case_id": 3, "title": "选择商品规格", "precondition": "商品有规格选项", "steps": ["选择颜色'红色'", "选择尺码'XL'", "验证价格更新"], "expected": "选择规格后价格正确更新"},
            {"case_id": 4, "title": "查看商品评价", "precondition": "商品有评价", "steps": ["滚动到评价区域", "验证评价列表展示"], "expected": "评价列表正确展示"},
        ],
        "script": '''import pytest
from playwright.sync_api import Page, expect


class TestProductDetail:
    """商城商品详情页面测试"""

    @pytest.fixture(autouse=True)
    def setup(self, page: Page):
        self.page = page
        self.page.goto("https://shop.demo.com/products/1001")

    def test_product_info(self):
        """查看商品基本信息"""
        expect(self.page.locator("[data-testid='product-name']")).to_be_visible()
        expect(self.page.locator("[data-testid='product-price']")).to_contain_text("¥")

    def test_image_carousel(self):
        """查看商品图片轮播"""
        first_img = self.page.locator(".carousel img.active").get_attribute("src")
        self.page.click(".carousel .next-btn")
        second_img = self.page.locator(".carousel img.active").get_attribute("src")
        assert first_img != second_img

    def test_select_spec(self):
        """选择商品规格"""
        self.page.click("[data-testid='spec-color'] button:has-text('红色')")
        self.page.click("[data-testid='spec-size'] button:has-text('XL')")
        expect(self.page.locator("[data-testid='product-price']")).to_contain_text("¥")

    def test_view_reviews(self):
        """查看商品评价"""
        self.page.locator(".review-section").scroll_into_view_if_needed()
        expect(self.page.locator(".review-item").first).to_be_visible()
''',
    },
]


# =============================================================================
#  执行记录定义（12 条）
# =============================================================================

EXECUTION_RECORDS = [
    # 8 success, 3 failed, 1 cancelled
    {"scenario_idx": 0, "status": "success", "exec_type": "web",  "duration": 12.5, "success_count": 4, "failed_count": 0, "start": "2026-07-09 10:00:00", "end": "2026-07-09 10:00:13", "error": None},
    {"scenario_idx": 1, "status": "success", "exec_type": "web",  "duration": 15.3, "success_count": 4, "failed_count": 0, "start": "2026-07-09 15:00:00", "end": "2026-07-09 15:00:15", "error": None},
    {"scenario_idx": 2, "status": "success", "exec_type": "web",  "duration": 18.7, "success_count": 4, "failed_count": 0, "start": "2026-07-10 11:00:00", "end": "2026-07-10 11:00:19", "error": None},
    {"scenario_idx": 2, "status": "failed",  "exec_type": "web",  "duration": 22.1, "success_count": 3, "failed_count": 1, "start": "2026-07-10 14:30:00", "end": "2026-07-10 14:30:22", "error": "Element not found: button[data-testid='sort-select'] timeout after 30000ms"},
    {"scenario_idx": 3, "status": "success", "exec_type": "web",  "duration": 25.4, "success_count": 4, "failed_count": 0, "start": "2026-07-11 12:00:00", "end": "2026-07-11 12:00:25", "error": None},
    {"scenario_idx": 4, "status": "success", "exec_type": "api",  "duration":  3.2, "success_count": 4, "failed_count": 0, "start": "2026-07-12 13:30:00", "end": "2026-07-12 13:30:03", "error": None},
    {"scenario_idx": 4, "status": "failed",  "exec_type": "api",  "duration":  5.8, "success_count": 2, "failed_count": 2, "start": "2026-07-12 17:00:00", "end": "2026-07-12 17:00:06", "error": "ConnectionError: Failed to establish connection to https://shop.demo.com/api/payment (503 Service Unavailable)"},
    {"scenario_idx": 5, "status": "success", "exec_type": "api",  "duration":  2.5, "success_count": 4, "failed_count": 0, "start": "2026-07-13 14:00:00", "end": "2026-07-13 14:00:03", "error": None},
    {"scenario_idx": 3, "status": "success", "exec_type": "web",  "duration": 30.2, "success_count": 4, "failed_count": 0, "start": "2026-07-13 16:30:00", "end": "2026-07-13 16:30:30", "error": None},
    {"scenario_idx": 6, "status": "cancelled", "exec_type": "web","duration":  8.0, "success_count": 0, "failed_count": 0, "start": "2026-07-14 09:30:00", "end": "2026-07-14 09:30:08", "error": "Execution cancelled by user"},
    {"scenario_idx": 6, "status": "failed",  "exec_type": "web",  "duration": 35.6, "success_count": 2, "failed_count": 2, "start": "2026-07-14 16:30:00", "end": "2026-07-14 16:30:36", "error": "Element not found: button[data-testid='checkout'] timeout after 30000ms"},
    {"scenario_idx": 5, "status": "success", "exec_type": "api",  "duration":  4.1, "success_count": 4, "failed_count": 0, "start": "2026-07-15 10:00:00", "end": "2026-07-15 10:00:04", "error": None},
]


# =============================================================================
#  反馈定义（3 条）
# =============================================================================

FEEDBACKS = [
    {"scenario_idx": 0, "score": 4, "accepted": True,  "comment": "生成的登录测试脚本覆盖了主要场景，SQL注入测试很全面。但是缺少记住密码功能的测试用例，希望后续补充。"},
    {"scenario_idx": 2, "score": 5, "accepted": True,  "comment": "搜索商品流程的测试非常完善，关键词搜索、排序、分页都覆盖到了。脚本质量很高，直接可以运行。"},
    {"scenario_idx": 6, "score": 3, "accepted": False, "comment": "商品详情页测试脚本存在元素定位问题，carousel的next-btn选择器在实际页面上找不到。需要根据真实页面结构调整定位策略。"},
]


# =============================================================================
#  辅助函数
# =============================================================================

def build_analysis_result(cases, scenario_name, status):
    """
    构建 ExecutionRecord.analysis_result 的 JSON 字符串。

    结构:
      {
        "cases": [
          {"case_id": 1, "title": "...", "status": "pass/fail", "duration_ms": 1200},
          ...
        ],
        "total": 4,
        "passed": 3,
        "failed": 1,
        "duration_ms": 4450
      }
    """
    result_cases = []
    total_duration = 0
    passed = 0
    failed = 0

    for i, case in enumerate(cases):
        # 成功记录全部 pass；失败记录让最后一个 case fail；取消记录全部 skip
        if status == "success":
            case_status = "pass"
            case_duration = random.randint(600, 2000)
        elif status == "failed":
            if i == len(cases) - 1:
                case_status = "fail"
                case_duration = random.randint(2000, 4000)
            else:
                case_status = "pass"
                case_duration = random.randint(600, 2000)
        else:  # cancelled
            case_status = "skip"
            case_duration = 0

        entry = {
            "case_id": case["case_id"],
            "title": case["title"],
            "status": case_status,
            "duration_ms": case_duration,
        }
        if case_status == "fail":
            entry["error"] = "Expected element not found within timeout"
            failed += 1
        elif case_status == "pass":
            passed += 1

        result_cases.append(entry)
        total_duration += case_duration

    result = {
        "cases": result_cases,
        "total": len(cases),
        "passed": passed,
        "failed": failed,
        "duration_ms": total_duration,
    }
    return json.dumps(result, ensure_ascii=False)


def truncate(s: str, n: int = 200) -> str:
    """截取字符串前 n 个字符（用于 generated_script 字段摘要展示）。"""
    if len(s) <= n:
        return s
    return s[:n] + "..."


# =============================================================================
#  种子主流程
# =============================================================================

def seed():
    """执行种子数据创建"""
    print("=" * 60)
    print("  电商演示数据种子脚本")
    print("=" * 60)

    # 确保数据库表存在
    print("\n[1/6] 确保数据库表存在...")
    Base.metadata.create_all(bind=sync_engine)
    print("  数据库表就绪")

    db = SessionLocal()
    db.expire_on_commit = False  # 避免 commit 后对象过期触发 selectin 重新加载
    try:
        # ------------------------------------------------------------------
        # 2. 创建演示用户
        # ------------------------------------------------------------------
        print("\n[2/6] 创建演示用户...")
        user = db.query(User).filter(User.username == DEMO_USERNAME).first()
        if user:
            print(f"  用户已存在: {user} (跳过)")
        else:
            user = User(
                username=DEMO_USERNAME,
                hashed_password=hash_password(DEMO_PASSWORD),
                email=DEMO_EMAIL,
                display_name=DEMO_DISPLAY_NAME,
                role=UserRole.ADMIN,
                is_active=True,
            )
            db.add(user)
            db.flush()
            print(f"  创建用户: {user}")

        user_id = user.id

        # ------------------------------------------------------------------
        # 3. 创建 Task + RequirementTask + Script（7 组）
        # ------------------------------------------------------------------
        print("\n[3/6] 创建需求任务、测试任务和脚本 (7 组)...")
        created_tasks = []        # Task 对象列表
        created_req_tasks = []    # RequirementTask 对象列表

        for idx, scenario in enumerate(SCENARIOS):
            tag = f"  [{idx + 1}/7]"

            # --- 3a. Task ---
            task_name = f"[需求] {scenario['short']}"
            existing_task = db.query(Task).options(*TASK_NOLOAD_OPTS).filter(
                Task.task_name == task_name,
                Task.user_id == user_id,
            ).first()

            if existing_task:
                print(f"{tag} Task 已存在: '{task_name}' (跳过)")
                task = existing_task
            else:
                task = Task(
                    task_name=task_name,
                    status=scenario["task_status"],
                    input_mode=InputMode.REQUIREMENT,
                    page_url=scenario["page_url"],
                    task_type=TaskType(scenario["task_type"]),
                    framework=scenario["framework"],
                    platform=scenario["platform"],
                    confidence=scenario["confidence"],
                    user_id=user_id,
                    created_by=user_id,
                    created_at=scenario["created_at"],
                )
                db.add(task)
                db.flush()
                print(f"{tag} 创建 Task: id={task.id}, name='{task_name}', status={task.status.value}")

            created_tasks.append(task)

            # --- 3b. RequirementTask ---
            existing_req = db.query(RequirementTask).filter(
                RequirementTask.intent == scenario["intent"],
                RequirementTask.user_id == user_id,
            ).first()

            if existing_req:
                print(f"{tag} RequirementTask 已存在: intent='{scenario['intent']}' (跳过)")
                req_task = existing_req
            else:
                cases_json = json.dumps(scenario["cases"], ensure_ascii=False)
                req_task = RequirementTask(
                    requirement=scenario["requirement"],
                    status=scenario["req_status"],
                    intent=scenario["intent"],
                    generated_case=cases_json,
                    generated_script=truncate(scenario["script"], 200),
                    task_id=task.id,
                    task_type=scenario["task_type"],
                    script_source="generated",
                    script_format=scenario["framework"],
                    kb_status="approved",
                    user_id=user_id,
                    created_by=user_id,
                    created_at=scenario["created_at"],
                )
                # 如果是失败任务，记录错误信息
                if scenario["req_status"] == "failed":
                    req_task.error_message = "脚本生成部分失败：元素定位策略与实际页面不匹配"

                db.add(req_task)
                db.flush()
                print(f"{tag} 创建 RequirementTask: id={req_task.id}, intent='{scenario['intent']}', status={scenario['req_status']}")

            created_req_tasks.append(req_task)

            # --- 3c. Script ---
            existing_script = db.query(Script).filter(
                Script.task_id == task.id,
            ).first()

            if existing_script:
                print(f"{tag} Script 已存在: task_id={task.id} (跳过)")
            else:
                script = Script(
                    task_id=task.id,
                    script_type=scenario["framework"],
                    script_content=scenario["script"],
                    script_language="python",
                    file_path=f"uploads/scripts/test_{scenario['intent']}.py",
                    kb_status="approved",
                    script_source="generated",
                    reuse_count=0,
                    user_id=user_id,
                    created_by=user_id,
                    created_at=scenario["created_at"],
                )
                db.add(script)
                db.flush()
                print(f"{tag} 创建 Script: id={script.id}, type={scenario['framework']}")

        # ------------------------------------------------------------------
        # 4. 创建 ExecutionRecord（12 条）
        # ------------------------------------------------------------------
        print("\n[4/6] 创建执行记录 (12 条)...")
        existing_exec_count = db.query(ExecutionRecord).filter(
            ExecutionRecord.user_id == user_id,
            ExecutionRecord.trigger_source == "demo_seed",
        ).count()

        if existing_exec_count >= len(EXECUTION_RECORDS):
            print(f"  执行记录已存在 ({existing_exec_count} 条)，跳过")
        else:
            for idx, er_def in enumerate(EXECUTION_RECORDS):
                tag = f"  [{idx + 1}/12]"
                scenario = SCENARIOS[er_def["scenario_idx"]]
                task = created_tasks[er_def["scenario_idx"]]

                # 构建分析结果 JSON
                analysis_json = build_analysis_result(
                    scenario["cases"],
                    scenario["name"],
                    er_def["status"],
                )

                # 解析时间字符串为 datetime 设置 created_at
                er_created = datetime.strptime(er_def["start"], "%Y-%m-%d %H:%M:%S")

                exec_record = ExecutionRecord(
                    task_id=task.id,
                    execution_type=er_def["exec_type"],
                    status=er_def["status"],
                    trigger_source="demo_seed",
                    start_time=er_def["start"],
                    end_time=er_def["end"],
                    duration=er_def["duration"],
                    success_count=er_def["success_count"],
                    failed_count=er_def["failed_count"],
                    error_message=er_def["error"],
                    report_path=f"reports/report_demo_{idx + 1}.html" if er_def["status"] == "success" else None,
                    screenshot_path=f"uploads/screenshots/demo_exec_{idx + 1}.png" if er_def["status"] == "failed" else None,
                    analysis_result=analysis_json,
                    user_id=user_id,
                    created_by=user_id,
                    created_at=er_created,
                )
                db.add(exec_record)
                db.flush()
                print(f"{tag} 创建 ExecutionRecord: id={exec_record.id}, type={er_def['exec_type']}, status={er_def['status']}, duration={er_def['duration']}s")

        # ------------------------------------------------------------------
        # 5. 创建 Feedback（3 条）
        # ------------------------------------------------------------------
        print("\n[5/6] 创建用户反馈 (3 条)...")
        for idx, fb_def in enumerate(FEEDBACKS):
            tag = f"  [{idx + 1}/3]"
            req_task = created_req_tasks[fb_def["scenario_idx"]]
            task = created_tasks[fb_def["scenario_idx"]]

            existing_fb = db.query(Feedback).filter(
                Feedback.requirement_id == req_task.id,
                Feedback.score == fb_def["score"],
                Feedback.user_id == user_id,
            ).first()

            if existing_fb:
                print(f"{tag} Feedback 已存在: req_id={req_task.id}, score={fb_def['score']} (跳过)")
            else:
                fb_created = req_task.created_at + timedelta(hours=2)
                feedback = Feedback(
                    requirement_id=req_task.id,
                    task_id=task.id,
                    script_id=None,
                    score=fb_def["score"],
                    comment=fb_def["comment"],
                    accepted=fb_def["accepted"],
                    regenerated=False,
                    user_id=user_id,
                    created_by=user_id,
                    created_at=fb_created,
                )
                db.add(feedback)
                db.flush()
                print(f"{tag} 创建 Feedback: id={feedback.id}, score={fb_def['score']}, accepted={fb_def['accepted']}")

        # ------------------------------------------------------------------
        # 6. 提交并汇总
        # ------------------------------------------------------------------
        db.commit()
        print("\n[6/6] 数据汇总")
        print("-" * 60)

        user_count = db.query(User).filter(User.username == DEMO_USERNAME).count()
        task_count = db.query(Task.id).filter(Task.user_id == user_id).count()
        req_count = db.query(RequirementTask).filter(RequirementTask.user_id == user_id).count()
        script_count = db.query(Script).filter(Script.user_id == user_id).count()
        exec_count = db.query(ExecutionRecord).filter(ExecutionRecord.user_id == user_id).count()
        fb_count = db.query(Feedback).filter(Feedback.user_id == user_id).count()

        print(f"  用户 (User):             {user_count}")
        print(f"  任务 (Task):             {task_count}")
        print(f"  需求任务 (RequirementTask): {req_count}")
        print(f"  脚本 (Script):           {script_count}")
        print(f"  执行记录 (ExecutionRecord): {exec_count}")
        print(f"  反馈 (Feedback):         {fb_count}")
        print("-" * 60)
        print(f"\n  演示账号: {DEMO_USERNAME} / {DEMO_PASSWORD}")
        print("\n  种子数据创建完成!")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
