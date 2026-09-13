from app.services.test_pipeline import TestPipelineService, _http_check
from app.services.testing_brain import classify_intent


class FakeMemory:
    def __init__(self):
        self.store = {}

    def get_by_title(self, user_id, project_id, kind, title):
        payload = self.store.get((user_id, project_id, kind, title))
        return {"content": payload} if payload is not None else None

    def remember(self, user_id, project_id, *, kind, title, content, **kwargs):
        self.store[(user_id, project_id, kind, title)] = content
        return {"kind": kind, "title": title}


class FakeDesigns:
    def get(self, *args, **kwargs):
        return {
            "objects": [{"name": "登录", "req_ids": ["REQ-001"]}],
            "environment": [],
        }


CASES = [
    {
        "id": 1,
        "case_code": "TC-001",
        "case_name": "登录成功",
        "scenario": "登录",
        "module": "用户",
        "test_data": "",
        "expected_result": "进入首页",
        "steps": ["打开登录页", "输入账号密码", "提交"],
    },
    {
        "id": 2,
        "case_code": "TC-002",
        "case_name": "错误密码",
        "scenario": "错误密码",
        "module": "用户",
        "test_data": "",
        "expected_result": "提示密码错误",
        "steps": ["打开登录页", "输入错误密码", "提交"],
    },
    {
        "id": 3,
        "case_code": "TC-003",
        "case_name": "禁用账号登录",
        "scenario": "禁用账号",
        "module": "用户",
        "test_data": "",
        "expected_result": "不可登录",
        "steps": ["打开登录页", "输入禁用账号", "提交"],
    },
]


def _pipe(monkeypatch, cases=None):
    service = TestPipelineService(FakeMemory())
    service.designs = FakeDesigns()
    monkeypatch.setattr(service, "list_cases", lambda user_id, project_id: list(cases if cases is not None else CASES))
    monkeypatch.setattr(service, "_link_cases_to_data", lambda *args, **kwargs: None)
    return service


def test_pipeline_intents():
    assert classify_intent("批量生成测试数据 20") == "prepare_data"
    assert classify_intent("批量生成测试账号") == "prepare_accounts"
    assert classify_intent("检查测试环境") == "check_env"
    assert classify_intent("创建执行批次") == "run_batch"
    assert classify_intent("从失败生成缺陷") == "draft_bugs"
    assert classify_intent("创建回归测试批次") == "regress"
    assert classify_intent("生成测试报告") == "generate_report"


def test_generate_data_refuses_without_cases(monkeypatch):
    pipe = _pipe(monkeypatch, cases=[])
    try:
        pipe.generate_data(1, 9, 10)
        assert False, "should refuse"
    except ValueError as exc:
        assert "测试用例" in str(exc)


def test_generate_data_creates_real_ids(monkeypatch):
    pipe = _pipe(monkeypatch)
    data = pipe.generate_data(1, 9, 5)
    assert data["count"] == 5
    ids = [item["id"] for item in data["created"]]
    assert ids == ["DATA-0001", "DATA-0002", "DATA-0003", "DATA-0004", "DATA-0005"]
    assert all(item["case_code"] for item in data["created"])
    assert all(item["fields"] for item in data["created"])
    assert all(item["provisioned"] is False for item in data["created"])
    disabled = next(item for item in data["created"] if item["case_code"] == "TC-003")
    assert disabled["purpose"] == "禁用账号"
    saved = pipe.get_prep(1, 9)
    assert len(saved["datasets"]) == 5


def test_accounts_are_pending_create_not_provisioned(monkeypatch):
    pipe = _pipe(monkeypatch)
    data = pipe.generate_accounts(1, 9, 4, ["管理员", "普通用户"])
    assert data["count"] == 4
    assert [item["id"] for item in data["created"]] == ["ACC-0001", "ACC-0002", "ACC-0003", "ACC-0004"]
    assert all(item["status"] == "pending_create" for item in data["created"])
    assert all(item["provisioned"] is False for item in data["created"])
    assert all("待在实际系统中创建" in item["note"] for item in data["created"])


def test_http_unknown_is_never_pass():
    status, detail = _http_check("")
    assert status == "UNKNOWN"
    assert status != "PASS"
    status, detail = _http_check("not-a-url")
    assert status == "UNKNOWN"


def test_env_check_does_not_mark_unknown_as_pass(monkeypatch):
    pipe = _pipe(monkeypatch)

    class FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return []

    class FakeDB:
        def query(self, *args, **kwargs):
            return FakeQuery()

        def close(self):
            return None

    monkeypatch.setattr("app.services.test_pipeline.SessionLocal", lambda: FakeDB())
    prep = pipe.check_environment(1, 9)
    statuses = {item["item"]: item["status"] for item in prep["env_checks"]}
    assert statuses["测试环境地址"] == "UNKNOWN"
    assert statuses["测试账号已在系统创建"] == "UNKNOWN"
    assert all(item["status"] in {"PASS", "FAIL", "UNKNOWN"} for item in prep["env_checks"])
    assert not any(item["status"] == "PASS" and item["item"] == "测试账号已在系统创建" for item in prep["env_checks"])
    assert prep["status"] == "partial"


def test_run_batch_starts_not_executed_and_refuses_auto_pass(monkeypatch):
    pipe = _pipe(monkeypatch)
    batch = pipe.create_run_batch(1, 9)
    assert batch["id"] == "EXEC-BATCH-001"
    assert batch["stats"]["total"] == 3
    assert batch["stats"]["NOT_EXECUTED"] == 3
    assert all(item["status"] == "NOT_EXECUTED" for item in batch["results"])
    try:
        pipe.record_results(1, 9, batch["id"], [{"id": batch["results"][0]["id"], "status": "PASS"}])
        assert False, "empty PASS should fail"
    except ValueError as exc:
        assert "实际结果" in str(exc)
    updated = pipe.record_results(
        1, 9, batch["id"],
        [{"id": batch["results"][0]["id"], "status": "FAIL", "actual": "点击登录后页面 500"}],
        executor="tester",
    )
    assert updated["results"][0]["status"] == "FAIL"
    assert updated["results"][0]["actual"] == "点击登录后页面 500"
    assert updated["stats"]["FAIL"] == 1
    assert updated["stats"]["NOT_EXECUTED"] == 2


def test_cannot_draft_bugs_without_fail(monkeypatch):
    pipe = _pipe(monkeypatch)
    pipe.create_run_batch(1, 9)
    try:
        pipe.draft_bugs_from_fails(1, 9)
        assert False, "should refuse"
    except ValueError as exc:
        assert "FAIL" in str(exc)


def test_bug_draft_and_verify_gate(monkeypatch):
    pipe = _pipe(monkeypatch)
    batch = pipe.create_run_batch(1, 9)
    fail_id = batch["results"][0]["id"]
    pipe.record_results(1, 9, batch["id"], [{"id": fail_id, "status": "FAIL", "actual": "页面 500"}])
    drafted = pipe.draft_bugs_from_fails(1, 9, batch["id"])
    assert drafted["count"] == 1
    bug = drafted["created"][0]
    assert bug["id"] == "BUG-001"
    assert bug["draft"] is True
    assert bug["exec_id"] == fail_id
    assert bug["case_code"] == "TC-001"
    submitted = pipe.submit_bug(1, 9, {**bug, "status": "FIXED", "title": "登录成功后页面返回 500"})
    assert submitted["status"] == "FIXED"
    try:
        pipe.submit_bug(1, 9, {"id": bug["id"], "status": "VERIFIED"})
        assert False, "verified without verification"
    except ValueError as exc:
        assert "验证" in str(exc)
    verified = pipe.verify_bug(1, 9, bug["id"], "PASS", "按原步骤重测已进入首页", ["日志：HTTP 200"])
    assert verified["bug"]["status"] == "VERIFIED"
    assert verified["verification"]["result"] == "PASS"
    reopened = pipe.verify_bug(1, 9, bug["id"], "FAIL", "仍返回 500")
    assert reopened["bug"]["status"] == "REOPENED"


def test_regression_and_honest_report(monkeypatch):
    pipe = _pipe(monkeypatch)
    batch = pipe.create_run_batch(1, 9)
    pipe.record_results(1, 9, batch["id"], [
        {"id": batch["results"][0]["id"], "status": "FAIL", "actual": "金额错误"},
        {"id": batch["results"][1]["id"], "status": "PASS", "actual": "提示密码错误"},
    ])
    drafted = pipe.draft_bugs_from_fails(1, 9)
    bug = drafted["created"][0]
    pipe.submit_bug(1, 9, {**bug, "status": "FIXED"})
    rec = pipe.recommend_regression(1, 9, [bug["id"]])
    assert rec["cases"]
    assert {item["id"] for item in rec["cases"]} <= {1, 2, 3}
    reg = pipe.create_regression(1, 9, [bug["id"]], version="1.0.1")
    assert reg["id"] == "REG-001"
    assert all(item["status"] == "NOT_EXECUTED" for item in reg["results"])
    done = pipe.record_regression(1, 9, reg["id"], [
        {"id": item["id"], "status": "PASS", "actual": "金额已正确"} for item in reg["results"]
    ])
    assert done["fix_verify"] == "PASS"
    assert done["risk"] == "低"
    report = pipe.generate_report(1, 9)
    assert report["id"] == "RPT-001"
    assert report["execution"]["FAIL"] == 1
    assert report["execution"]["NOT_EXECUTED"] == 1
    assert report["execution"]["pass_rate_of_executed"] == 50.0
    assert "未执行" in report["conclusion"]
    assert report["trace"]["batches"] == ["EXEC-BATCH-001"]
    assert "BUG-001" in report["trace"]["bugs"]


def test_report_without_runs_cannot_claim_pass(monkeypatch):
    pipe = _pipe(monkeypatch)
    report = pipe.generate_report(1, 9)
    assert report["execution"]["total"] == 0
    assert report["execution"]["pass_rate_of_executed"] is None
    assert "不能出具通过结论" in report["conclusion"]
