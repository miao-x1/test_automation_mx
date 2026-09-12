from app.knowledge.testing_expert import get_testing_expert
from app.knowledge.testing_expert.catalog import all_cards, all_playbooks

QUESTIONS = [
    "什么是软件测试？", "QA和QC有什么区别？", "什么是测试生命周期？", "测试流程包含哪些环节？",
    "测试计划写什么？", "测试策略怎么定？", "测试方案和计划有什么不同？", "如何确定测试范围？",
    "什么是产品风险？", "测试估算看什么？", "P0/P1/P2/P3怎么划分？", "什么是测试级别？",
    "单元测试测什么？", "集成测试测什么？", "系统测试测什么？", "验收测试测什么？",
    "什么是黑盒测试？", "什么是白盒测试？", "什么是灰盒测试？", "静态测试和动态测试有什么区别？",
    "功能测试和非功能测试有什么区别？", "冒烟测试和回归测试有什么区别？", "什么是探索性测试？",
    "兼容性测试怎么做？", "可用性测试关注什么？", "什么是安全测试？", "什么是性能测试？",
    "稳定性测试测什么？", "可靠性测试测什么？", "接口测试怎么测？", "UI测试测什么？",
    "E2E测试什么时候用？", "什么是等价类？", "等价类和边界值有什么区别？", "什么是边界值分析？",
    "决策表怎么用？", "状态迁移怎么测？", "什么是因果图？", "场景法怎么设计用例？",
    "什么是错误推测？", "什么是正交测试？", "Pairwise能保证全覆盖吗？", "什么是风险驱动测试？",
    "什么是数据驱动测试？", "什么是组合测试？", "什么是测试覆盖率？", "需求覆盖率怎么看？",
    "缺陷覆盖指什么？", "测试用例怎么设计？", "测试用例怎么评审？", "测试数据怎么设计？",
    "测试环境要注意什么？", "什么是测试配置？", "缺陷怎么发现和定位？", "缺陷怎么复现？",
    "Bug严重程度怎么定？", "Bug优先级怎么定？", "缺陷生命周期是什么？", "如何做根因分析？",
    "回归验证做什么？", "测试报告写什么？", "测试度量看哪些指标？", "什么是测试左移？",
    "什么是Shift-right？", "什么是持续测试？", "Agile测试怎么做？", "DevOps测试是什么？",
    "CI/CD里怎么放测试？", "什么是Mock？", "什么是Stub？", "什么是Spy？", "什么是Test Double？",
    "什么是Fixture？", "什么是Hook？", "什么是Flaky Test？", "如何提高自动化测试稳定性？",
    "UI自动化为什么不稳定？", "Playwright怎么提高稳定性？", "什么是Page Object？",
    "什么是Screenplay？", "接口鉴权怎么测？", "JWT和Session有什么差别？", "什么是OAuth？",
    "如何测水平越权？", "SQL注入怎么测？", "XSS怎么测？", "CSRF怎么测？",
    "文件上传安全测什么？", "什么是幂等性？", "分页接口怎么测？", "接口超时重试有什么风险？",
    "如何做接口与数据库一致性验证？", "事务回滚怎么测？", "Load和Stress有什么区别？",
    "P95和P99是什么？", "如何建立性能基线？", "OWASP Top 10是什么？", "如何判断测试是否充分？",
    "测试人员如何与开发沟通？", "版本变化后要不要重建测试体系？",
]

TASKS = [
    "帮我测试登录功能", "测试注册", "测试购物车", "测试支付", "测试文件上传",
    "测试权限", "测试接口", "测试订单", "测试搜索", "测试分页",
    "测试找回密码", "测试结算", "测试导出", "测试导入", "测试评论",
    "测试通知", "测试webhook回调", "测试验证码", "测试并发下单", "测试会话过期",
]


def test_catalog_size_and_domains():
    cards = all_cards()
    books = all_playbooks()
    assert len(cards) >= 50
    assert len(books) == 20
    domains = {item["domain"] for item in cards}
    for required in ("foundation", "lifecycle", "technique", "automation", "api", "security", "thinking"):
        assert required in domains


def test_one_hundred_professional_questions():
    assert len(QUESTIONS) == 100
    expert = get_testing_expert()
    missed = []
    weak = []
    for question in QUESTIONS:
        result = expert.answer(question)
        if not result["used_cards"]:
            missed.append(question)
            continue
        if result["used_cards"][0]["score"] < 2:
            weak.append(question)
        assert "适用：" in result["answer"] or "怎么用" in result["answer"]
    assert not missed, f"未命中: {missed}"
    assert len(weak) <= 8, f"命中过弱: {weak}"


def test_twenty_real_tasks_use_playbooks():
    assert len(TASKS) == 20
    expert = get_testing_expert()
    missed = []
    for task in TASKS:
        analysis = expert.analyze_task(task)
        if not analysis.get("playbook"):
            missed.append(task)
            continue
        assert analysis["must_test"], task
        assert analysis["candidate_points"], task
        assert any(point["priority"] == "P0" for point in analysis["candidate_points"])
        assert "无脑" in analysis["prompt"] or "风险" in analysis["prompt"]
    assert not missed, f"未命中场景手册: {missed}"


def test_login_thinking_is_not_mechanical():
    analysis = get_testing_expert().analyze_task("帮我测试登录功能")
    joined = " ".join(analysis["must_test"] + analysis["should_test"] + analysis["thinking"])
    for needle in ("会话", "空", "退出", "权限"):
        assert needle in joined
    assert analysis["skip_unless"]


def test_payment_marks_money_as_p0():
    analysis = get_testing_expert().analyze_task("测试支付")
    assert analysis["playbook"]["id"] == "payment"
    assert any("一次" in item or "幂等" in item for item in analysis["must_test"])
