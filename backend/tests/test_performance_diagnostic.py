"""
性能诊断模块测试

测试覆盖:
  1. JStackParser: 线程解析 / 死锁检测 / 阻塞检测 / CPU 热点检测
  2. LogAnalyzer: 日志解析 / 错误聚类 / 慢操作 / 错误突增
  3. DiagnosticReportBuilder: 多源关联分析 / 问题提取 / 严重度计算
  4. PerformanceDiagnosticAgent: 类定义 / action 注册 / 降级分析
  5. Agent 注册验证 (definitions.py)
  6. API 路由验证 (diagnose 端点)
  7. PerformanceAnalysisAgent 集成诊断 (自动触发)
"""
import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# ===== Stub 3rd-party modules (与 test_performance.py 一致) =====
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

_pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
if not hasattr(_pm, "DataType"):
    _pm.DataType = type("DataType", (), {"INT64": "int64", "VARCHAR": "varchar", "FLOAT_VECTOR": "float_vector", "BOOL": "bool"})
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
sys.modules["pymilvus"] = _pm

_pymysql = types.ModuleType("pymysql")
_pymysql.paramstyle = "format"
_pymysql.install_as_MySQLdb = lambda: None
_pymysql.connect = lambda *a, **kw: None
sys.modules["pymysql"] = _pymysql

_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.Driver = type("Driver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.Session = type("Session", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.basic_auth = lambda *a, **kw: MagicMock()
sys.modules["neo4j"] = _neo

# autogen stub
_ag = types.ModuleType("autogen_core")
def _make_class(name):
    return type(name, (), {"__init__": lambda self, *a, **kw: None})
_ag.RoutedAgent = _make_class("RoutedAgent")
_ag.message_handler = lambda *a, **kw: (lambda f: f)
_ag.MessageContext = _make_class("MessageContext")
_ag.AgentId = _make_class("AgentId")
_ag.AgentRuntime = _make_class("AgentRuntime")
_ag.CancellationToken = _make_class("CancellationToken")
_ag.DefaultTopicId = _make_class("DefaultTopicId")
_ag.SingleThreadedAgentRuntime = _make_class("SingleThreadedAgentRuntime")
_ag.ComponentBase = _make_class("ComponentBase")
_ag.default_subscription = lambda *a, **kw: (lambda f: f)
sys.modules["autogen_core"] = _ag

_aac = types.ModuleType("autogen_agentchat")
_aac_base = types.ModuleType("autogen_agentchat.base")
_aac_base.ChatAgent = _make_class("ChatAgent")
_aac_base.Response = _make_class("Response")
_aac_base.TaskResult = _make_class("TaskResult")
_aac_messages = types.ModuleType("autogen_agentchat.messages")
_aac_messages.TextMessage = _make_class("TextMessage")
_aac_messages.BaseChatMessage = _make_class("BaseChatMessage")
_aac_messages.BaseAgentEvent = _make_class("BaseAgentEvent")
_aac_teams = types.ModuleType("autogen_agentchat.teams")
_aac_teams.DiGraphBuilder = _make_class("DiGraphBuilder")
_aac_teams.GraphFlow = _make_class("GraphFlow")
_aac.base = _aac_base
_aac.messages = _aac_messages
_aac.teams = _aac_teams
sys.modules["autogen_agentchat"] = _aac
sys.modules["autogen_agentchat.base"] = _aac_base
sys.modules["autogen_agentchat.messages"] = _aac_messages
sys.modules["autogen_agentchat.teams"] = _aac_teams

_sse = types.ModuleType("sse_starlette")
_sse_sse = types.ModuleType("sse_starlette.sse")
_sse_sse.EventSourceResponse = type("EventSourceResponse", (), {"__init__": lambda *a, **kw: None})
sys.modules["sse_starlette"] = _sse
sys.modules["sse_starlette.sse"] = _sse_sse


# ===== 测试工具 =====
RESULTS = []

def record(name: str, ok: bool, detail: str = ""):
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"{status} {name}"
    if detail and not ok:
        msg += f" | {detail}"
    print(msg)
    RESULTS.append((name, ok))


# ================================================================== #
#  测试数据                                                          #
# ================================================================== #

# 包含死锁的 jstack dump
JSTACK_WITH_DEADLOCK = '''
"Thread-1" #18 prio=5 os_prio=0 tid=0x00007f8b3c00a800 nid=0x4a2f waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
   at com.example.Service.methodA(Service.java:25)
   - waiting to lock <0x000000076b3a1e98> (a java.lang.Object)
   - locked <0x000000076b3a1e99> (a java.lang.Object)

"Thread-2" #19 prio=5 os_prio=0 tid=0x00007f8b3c00b800 nid=0x4a30 waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
   at com.example.Service.methodB(Service.java:45)
   - waiting to lock <0x000000076b3a1e99> (a java.lang.Object)
   - locked <0x000000076b3a1e98> (a java.lang.Object)

"main" #1 prio=5 os_prio=0 tid=0x00007f8b3800a000 nid=0x4a20 runnable
   java.lang.Thread.State: RUNNABLE
   at java.net.SocketInputStream.socketRead0(Native Method)
   at java.net.SocketInputStream.read(SocketInputStream.java:171)
   at com.example.HttpServer.handleRequest(HttpServer.java:100)

Found one Java-level deadlock:
=============================
"Thread-1":
  waiting to lock <0x000000076b3a1e98> (a java.lang.Object),
  which is held by "Thread-2"
"Thread-2":
  waiting to lock <0x000000076b3a1e99> (a java.lang.Object),
  which is held by "Thread-1"

Java stack information for the threads listed above:
===================================================
"Thread-1":
   at com.example.Service.methodA(Service.java:25)
   - waiting to lock <0x000000076b3a1e98> (a java.lang.Object)
   - locked <0x000000076b3a1e99> (a java.lang.Object)
"Thread-2":
   at com.example.Service.methodB(Service.java:45)
   - waiting to lock <0x000000076b3a1e99> (a java.lang.Object)
   - locked <0x000000076b3a1e98> (a java.lang.Object)
'''

# 包含 CPU 热点的 jstack dump (多个 RUNNABLE 线程在同一栈帧)
JSTACK_WITH_CPU_HOTSPOT = '''
"worker-1" #21 prio=5 os_prio=0 tid=0x00001 nid=0x51 runnable
   java.lang.Thread.State: RUNNABLE
   at com.example.Calculator.heavyCompute(Calculator.java:120)
   at com.example.Worker.run(Worker.java:50)

"worker-2" #22 prio=5 os_prio=0 tid=0x00002 nid=0x52 runnable
   java.lang.Thread.State: RUNNABLE
   at com.example.Calculator.heavyCompute(Calculator.java:120)
   at com.example.Worker.run(Worker.java:50)

"worker-3" #23 prio=5 os_prio=0 tid=0x00003 nid=0x53 runnable
   java.lang.Thread.State: RUNNABLE
   at com.example.Calculator.heavyCompute(Calculator.java:120)
   at com.example.Worker.run(Worker.java:50)

"http-nio-8080-exec-1" #10 daemon prio=5 os_prio=0 tid=0x00004 nid=0x60 runnable
   java.lang.Thread.State: RUNNABLE
   at java.net.SocketInputStream.socketRead0(Native Method)
   at org.apache.catalina.connector.CoyoteAdapter.service(CoyoteAdapter.java:300)
'''

# 包含阻塞但没有死锁的 jstack dump
JSTACK_WITH_BLOCKING = '''
"pool-1-thread-1" #15 prio=5 os_prio=0 tid=0x00001 nid=0x3a waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
   at com.example.Database.query(Database.java:80)
   - waiting to lock <0x00000007a0b2c000> (a com.example.Database)
   - locked <0x00000007a0b2c001> (a java.lang.Object)

"pool-1-thread-2" #16 prio=5 os_prio=0 tid=0x00002 nid=0x3b waiting for monitor entry
   java.lang.Thread.State: BLOCKED (on object monitor)
   at com.example.Database.query(Database.java:80)
   - waiting to lock <0x00000007a0b2c000> (a com.example.Database)

"db-owner" #14 prio=5 os_prio=0 tid=0x00003 nid=0x3c runnable
   java.lang.Thread.State: RUNNABLE
   at com.example.Database.executeUpdate(Database.java:200)
   - locked <0x00000007a0b2c000> (a com.example.Database)
'''

# 测试日志数据
TEST_LOGS = [
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:01", "logger": "com.example.UserService"},
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:02", "logger": "com.example.UserService"},
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:03", "logger": "com.example.UserService"},
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:04", "logger": "com.example.UserService"},
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:05", "logger": "com.example.UserService"},
    {"level": "ERROR", "message": "ConnectException: Connection refused to 192.168.1.100:3306",
     "timestamp": "2026-07-23 10:00:06", "logger": "com.example.DbPool"},
    {"level": "WARN", "message": "Slow query detected: SELECT * FROM orders WHERE status=1 took 3500ms",
     "timestamp": "2026-07-23 10:00:07", "logger": "com.example.SqlLogger"},
    {"level": "WARN", "message": "Slow query detected: SELECT * FROM orders WHERE status=1 took 4200ms",
     "timestamp": "2026-07-23 10:00:08", "logger": "com.example.SqlLogger"},
    {"level": "INFO", "message": "Request processed: GET /api/users/123",
     "timestamp": "2026-07-23 10:00:09", "logger": "com.example.Controller"},
    {"level": "ERROR", "message": "NullPointerException at UserService.getUser(UserService.java:45)",
     "timestamp": "2026-07-23 10:00:10", "logger": "com.example.UserService"},
]

# 纯文本日志测试数据
TEST_TEXT_LOGS = [
    "2026-07-23 10:00:01 ERROR [com.example.Service] OutOfMemoryError: Java heap space",
    "2026-07-23 10:00:02 ERROR [com.example.Service] OutOfMemoryError: Java heap space",
    "2026-07-23 10:00:03 WARN  [com.example.Cache] Cache miss for key user:12345",
    "2026-07-23 10:00:04 ERROR [com.example.HttpClient] Read timeout after 5000ms",
    "2026-07-23 10:00:05 INFO  [com.example.App] Application started successfully",
    "2026-07-23 10:00:06 ERROR [com.example.Service] OutOfMemoryError: Java heap space",
]


# ================================================================== #
#  1. JStackParser 测试                                              #
# ================================================================== #

def test_jstack_parse_basic():
    """测试 1: JStack 基本解析 — 线程数和状态分布"""
    from app.domains.performance.analyzer.jstack_parser import JStackParser
    parser = JStackParser()
    report = parser.parse(JSTACK_WITH_DEADLOCK)

    ok = report.total_threads >= 3
    ok = ok and "BLOCKED" in report.state_distribution
    ok = ok and "RUNNABLE" in report.state_distribution
    record("JStack-基本解析(线程数+状态)", ok,
           f"threads={report.total_threads}, states={report.state_distribution}")


def test_jstack_deadlock_detection():
    """测试 2: 死锁检测"""
    from app.domains.performance.analyzer.jstack_parser import JStackParser
    parser = JStackParser()
    report = parser.parse(JSTACK_WITH_DEADLOCK)

    ok = report.has_deadlock_section
    ok = ok and len(report.deadlocks) > 0
    if ok:
        deadlock = report.deadlocks[0]
        ok = "Thread-1" in deadlock.involved_threads
        ok = ok and "Thread-2" in deadlock.involved_threads
    record("JStack-死锁检测", ok,
           f"deadlocks={len(report.deadlocks)}, threads={report.deadlocks[0].involved_threads if report.deadlocks else []}")


def test_jstack_blocked_threads():
    """测试 3: BLOCKED 线程检测"""
    from app.domains.performance.analyzer.jstack_parser import JStackParser
    parser = JStackParser()
    report = parser.parse(JSTACK_WITH_BLOCKING)

    ok = len(report.blocked_threads) >= 2
    if ok:
        blocked = report.blocked_threads[0]
        ok = ok and blocked.thread_name.startswith("pool-1-thread")
        ok = ok and "0x00000007a0b2c000" in blocked.waiting_on_lock
    record("JStack-BLOCKED线程检测", ok,
           f"blocked={len(report.blocked_threads)}")


def test_jstack_cpu_hotspot():
    """测试 4: CPU 热点检测"""
    from app.domains.performance.analyzer.jstack_parser import JStackParser
    parser = JStackParser()
    report = parser.parse(JSTACK_WITH_CPU_HOTSPOT)

    ok = len(report.cpu_hotspots) > 0
    if ok:
        hotspot = report.cpu_hotspots[0]
        ok = "com.example.Calculator.heavyCompute" in hotspot.frame
        ok = ok and hotspot.runnable_thread_count >= 3
    record("JStack-CPU热点检测", ok,
           f"hotspots={len(report.cpu_hotspots)}, top={report.cpu_hotspots[0].frame[:50] if report.cpu_hotspots else 'N/A'}")


def test_jstack_empty_input():
    """测试 5: 空输入处理"""
    from app.domains.performance.analyzer.jstack_parser import JStackParser
    parser = JStackParser()
    report = parser.parse("")
    ok = report.total_threads == 0
    ok = ok and len(report.parse_errors) > 0
    record("JStack-空输入处理", ok)


def test_jstack_convenience_functions():
    """测试 6: 便捷函数 (parse_jstack / detect_deadlock / find_blocked_threads)"""
    from app.domains.performance.analyzer.jstack_parser import (
        parse_jstack, detect_deadlock, find_blocked_threads, find_cpu_hotspots,
    )

    result = parse_jstack(JSTACK_WITH_DEADLOCK)
    ok = "total_threads" in result and result["total_threads"] >= 3

    deadlock = detect_deadlock(JSTACK_WITH_DEADLOCK)
    ok = ok and deadlock is not None and "Thread-1" in deadlock["involved_threads"]

    blocked = find_blocked_threads(JSTACK_WITH_BLOCKING)
    ok = ok and len(blocked) >= 2

    hotspots = find_cpu_hotspots(JSTACK_WITH_CPU_HOTSPOT)
    ok = ok and len(hotspots) > 0
    record("JStack-便捷函数", ok)


# ================================================================== #
#  2. LogAnalyzer 测试                                               #
# ================================================================== #

def test_log_analyzer_basic():
    """测试 7: 日志基本分析 — 级别分布"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_LOGS)

    ok = report.total_lines == len(TEST_LOGS)
    ok = ok and report.level_distribution.get("ERROR", 0) == 7  # 6 NPE + 1 ConnectException
    ok = ok and report.level_distribution.get("WARN", 0) == 2
    record("日志-基本分析(级别分布)", ok,
           f"lines={report.total_lines}, dist={report.level_distribution}")


def test_log_error_clustering():
    """测试 8: 错误聚类"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_LOGS)

    ok = len(report.error_clusters) > 0
    if ok:
        # NullPointerException 应聚为一类
        npe_cluster = None
        for cluster in report.error_clusters:
            if "NullPointerException" in cluster.error_type:
                npe_cluster = cluster
                break
        ok = npe_cluster is not None
        if ok:
            ok = npe_cluster.count == 6  # 6 条 NPE
    record("日志-错误聚类", ok,
           f"clusters={len(report.error_clusters)}, NPE count={npe_cluster.count if npe_cluster else 0}")


def test_log_text_format():
    """测试 9: 纯文本日志解析"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_TEXT_LOGS)

    ok = report.total_lines == len(TEST_TEXT_LOGS)
    ok = ok and report.level_distribution.get("ERROR", 0) == 4
    record("日志-纯文本格式解析", ok,
           f"lines={report.total_lines}, dist={report.level_distribution}")


def test_log_slow_operation():
    """测试 10: 慢操作检测"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_LOGS)

    # 日志中有 "took 3500ms" 和 "took 4200ms"
    ok = len(report.slow_operations) >= 2
    if ok:
        ok = report.slow_operations[0].duration_ms >= 3500
    record("日志-慢操作检测", ok,
           f"slow_ops={len(report.slow_operations)}, top_duration={report.slow_operations[0].duration_ms if report.slow_operations else 0}")


def test_log_error_spike():
    """测试 11: 错误突增检测"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_LOGS)

    # TEST_LOGS 中 10:00:01-10:00:06 有 6 个 ERROR (集中在很短时间), 应触发突增
    ok = report.error_spike is not None
    record("日志-错误突增检测", ok,
           f"spike={report.error_spike}")


def test_log_severity():
    """测试 12: 日志严重度判定"""
    from app.domains.performance.analyzer.log_analyzer import LogAnalyzer
    analyzer = LogAnalyzer()
    report = analyzer.analyze(TEST_LOGS)

    # 6 个 NPE 错误, 严重度应为 high 或 critical
    ok = report.severity in ("high", "critical")
    record("日志-严重度判定", ok, f"severity={report.severity}")


# ================================================================== #
#  3. DiagnosticReportBuilder 测试                                   #
# ================================================================== #

def test_diagnostic_report_jstack_only():
    """测试 13: 仅 jstack 诊断报告"""
    from app.domains.performance.analyzer.diagnostic_report import DiagnosticReportBuilder
    builder = DiagnosticReportBuilder()
    report = builder.build(jstack_dump=JSTACK_WITH_DEADLOCK)

    ok = len(report.problems) > 0
    if ok:
        # 应检测到死锁
        has_deadlock = any(p.problem_type == "deadlock" for p in report.problems)
        ok = has_deadlock
    ok = ok and report.overall_severity == "critical"
    record("诊断报告-仅jstack(死锁)", ok,
           f"problems={len(report.problems)}, severity={report.overall_severity}")


def test_diagnostic_report_logs_only():
    """测试 14: 仅日志诊断报告"""
    from app.domains.performance.analyzer.diagnostic_report import DiagnosticReportBuilder
    builder = DiagnosticReportBuilder()
    report = builder.build(logs=TEST_LOGS)

    ok = len(report.problems) > 0
    if ok:
        has_error_cluster = any(p.problem_type == "error_cluster" for p in report.problems)
        ok = has_error_cluster
    record("诊断报告-仅日志(错误聚类)", ok,
           f"problems={len(report.problems)}, severity={report.overall_severity}")


def test_diagnostic_report_correlation():
    """测试 15: 多源关联分析"""
    from app.domains.performance.analyzer.diagnostic_report import DiagnosticReportBuilder
    builder = DiagnosticReportBuilder()

    monitoring_data = {
        "avg_tps": 50,
        "peak_tps": 80,
        "avg_rt": 500,
        "p95_rt": 2500,  # 高 RT
        "p99_rt": 3000,
        "error_rate": 15,  # 高错误率
        "cpu_peak_pct": 90,  # 高 CPU
        "mem_peak_mb": 2048,
        "metrics": [],
    }

    report = builder.build(
        jstack_dump=JSTACK_WITH_BLOCKING,
        logs=TEST_LOGS,
        monitoring_data=monitoring_data,
    )

    # 应有关联分析 (线程阻塞 + 高 RT)
    ok = len(report.correlations) > 0
    if ok:
        has_block_latency = any(c["type"] == "block_latency" for c in report.correlations)
        ok = has_block_latency
    record("诊断报告-多源关联分析", ok,
           f"correlations={len(report.correlations)}, types={[c['type'] for c in report.correlations]}")


def test_diagnostic_report_empty_input():
    """测试 16: 空输入处理"""
    from app.domains.performance.analyzer.diagnostic_report import DiagnosticReportBuilder
    builder = DiagnosticReportBuilder()
    report = builder.build()

    ok = len(report.problems) == 0
    ok = ok and report.overall_severity == "low"
    record("诊断报告-空输入处理", ok,
           f"problems={len(report.problems)}, severity={report.overall_severity}")


def test_diagnostic_report_convenience_function():
    """测试 17: 便捷函数 build_diagnostic_report"""
    from app.domains.performance.analyzer import build_diagnostic_report

    result = build_diagnostic_report(
        jstack_dump=JSTACK_WITH_DEADLOCK,
        logs=TEST_LOGS,
    )

    ok = "problems" in result
    ok = ok and "overall_severity" in result
    ok = ok and len(result["problems"]) > 0
    record("诊断报告-便捷函数", ok)


# ================================================================== #
#  4. PerformanceDiagnosticAgent 测试                                #
# ================================================================== #

def test_diagnostic_agent_class_definition():
    """测试 18: PerformanceDiagnosticAgent 类定义"""
    from app.domains.performance.agents import PerformanceDiagnosticAgent
    agent = PerformanceDiagnosticAgent()

    ok = getattr(agent, "_display_name", "") == "PerformanceDiagnosticAgent" or \
         getattr(agent, "display_name", "") == "PerformanceDiagnosticAgent"
    caps = getattr(agent, "_capabilities", getattr(agent, "capabilities", []))
    ok = ok and "performance_diagnosis" in caps
    ok = ok and hasattr(agent, "handle_diagnose")
    ok = ok and hasattr(agent, "execute")
    record("诊断Agent-类定义", ok)


def test_diagnostic_agent_fallback_analysis():
    """测试 19: 诊断 Agent 降级分析 (LLM 不可用)"""
    from app.domains.performance.agents import PerformanceDiagnosticAgent
    from app.domains.performance.analyzer.diagnostic_report import (
        DiagnosticReport, DiagnosticProblem,
    )

    agent = PerformanceDiagnosticAgent()

    # 构造模拟报告
    report = DiagnosticReport()
    report.problems.append(DiagnosticProblem(
        problem_type="deadlock",
        severity="critical",
        title="测试死锁",
        description="Thread-A 和 Thread-B 形成死锁",
        location="com.example.Service:25",
        recommendations=["修复建议1", "修复建议2"],
    ))
    report.correlations.append({"description": "死锁导致高RT", "type": "deadlock_error"})
    report.overall_severity = "critical"

    result = agent._fallback_llm_analysis(report)

    ok = "root_cause" in result
    ok = ok and len(result["problem_details"]) > 0
    ok = ok and result["risk_assessment"] == "高风险"
    record("诊断Agent-降级分析", ok,
           f"root_cause={result.get('root_cause', '')[:50]}")


def test_diagnostic_agent_action_handler():
    """测试 20: 诊断 Agent action_handler 注册"""
    from app.domains.performance.agents import PerformanceDiagnosticAgent
    agent = PerformanceDiagnosticAgent()

    # 检查 "diagnose" action 是否注册
    ok = "diagnose" in agent._action_handlers if hasattr(agent, "_action_handlers") else True
    # 如果没有 _action_handlers 属性, 检查方法存在即可
    if not ok:
        ok = hasattr(agent, "handle_diagnose")
    record("诊断Agent-action注册", ok)


# ================================================================== #
#  5. Agent 注册验证                                                  #
# ================================================================== #

def test_agent_registration():
    """测试 21: Agent 在 definitions.py 中注册"""
    from app.agents.factory.definitions import DEFAULT_AGENT_SPECS

    diag_spec = None
    for spec in DEFAULT_AGENT_SPECS:
        if spec.name == "performance_diagnostic_agent":
            diag_spec = spec
            break

    ok = diag_spec is not None
    if ok:
        ok = diag_spec.class_name == "PerformanceDiagnosticAgent"
        ok = ok and "performance_diagnosis" in diag_spec.capabilities
        ok = ok and "jstack_analysis" in diag_spec.capabilities
    record("注册-Agent定义验证", ok,
           f"name={diag_spec.name if diag_spec else 'NOT FOUND'}")


# ================================================================== #
#  6. API 路由验证                                                    #
# ================================================================== #

def test_api_diagnose_endpoint():
    """测试 22: API 诊断端点注册"""
    from app.api.performance import router

    # 检查路由中是否有 diagnose 端点
    diagnose_routes = [
        r for r in router.routes
        if hasattr(r, "path") and "diagnose" in r.path
    ]
    ok = len(diagnose_routes) > 0
    if ok:
        ok = any(r.path.endswith("/diagnose") for r in diagnose_routes)
    record("API-诊断端点注册", ok,
           f"routes={[r.path for r in diagnose_routes]}")


def test_api_diagnose_request_model():
    """测试 23: DiagnoseRequest 模型"""
    from app.api.performance import DiagnoseRequest

    req = DiagnoseRequest(jstack_dump="test", logs=[{"level": "ERROR"}])
    ok = req.jstack_dump == "test"
    ok = ok and len(req.logs) == 1
    record("API-DiagnoseRequest模型", ok)


# ================================================================== #
#  7. PerformanceAnalysisAgent 集成验证                               #
# ================================================================== #

def test_analysis_agent_has_run_diagnosis():
    """测试 24: PerformanceAnalysisAgent 集成诊断方法"""
    from app.domains.performance.agents import PerformanceAnalysisAgent
    agent = PerformanceAnalysisAgent()

    ok = hasattr(agent, "_run_diagnosis")
    record("分析Agent-集成诊断方法", ok)


def test_analysis_agent_returns_diagnosis_field():
    """测试 25: 分析 Agent 返回结果包含 diagnosis 字段"""
    # 这个测试验证 handle_analyze 返回结构中包含 "diagnosis" key
    # 由于无法实际调用 LLM, 只验证代码结构
    import inspect
    from app.domains.performance.agents import PerformanceAnalysisAgent

    source = inspect.getsource(PerformanceAnalysisAgent.handle_analyze)
    ok = "diagnosis" in source
    ok = ok and "_run_diagnosis" in source
    record("分析Agent-返回diagnosis字段", ok)


# ================================================================== #
#  8. __init__.py 导出验证                                           #
# ================================================================== #

def test_init_exports():
    """测试 26: __init__.py 导出 PerformanceDiagnosticAgent"""
    from app.domains.performance import (
        PerformanceDiagnosticAgent,
        PerformancePlanAgent,
        PerformanceScriptAgent,
        PerformanceAnalysisAgent,
    )
    ok = PerformanceDiagnosticAgent is not None
    ok = ok and PerformancePlanAgent is not None
    record("导出-__init__.py验证", ok)


def test_analyzer_init_exports():
    """测试 27: analyzer __init__.py 导出"""
    from app.domains.performance.analyzer import (
        JStackParser, JStackReport,
        LogAnalyzer, LogReport,
        DiagnosticReportBuilder, DiagnosticReport, DiagnosticProblem,
        parse_jstack, analyze_logs, build_diagnostic_report,
    )
    ok = JStackParser is not None
    ok = ok and LogAnalyzer is not None
    ok = ok and DiagnosticReportBuilder is not None
    record("导出-analyzer __init__.py验证", ok)


# ================================================================== #
#  9. 端到端诊断流程测试                                              #
# ================================================================== #

def test_e2e_diagnostic_flow():
    """测试 28: 端到端诊断流程 (解析模块 → 报告生成 → 结构验证)"""
    from app.domains.performance.analyzer import build_diagnostic_report

    monitoring = {
        "avg_tps": 30,
        "peak_tps": 50,
        "avg_rt": 800,
        "p95_rt": 2500,
        "p99_rt": 3500,
        "error_rate": 12,
        "cpu_peak_pct": 85,
        "mem_peak_mb": 1800,
        "metrics": [],
    }

    result = build_diagnostic_report(
        jstack_dump=JSTACK_WITH_DEADLOCK,
        logs=TEST_LOGS + TEST_TEXT_LOGS,
        monitoring_data=monitoring,
    )

    # 验证报告结构
    ok = "problems" in result and len(result["problems"]) > 0
    ok = ok and "correlations" in result and len(result["correlations"]) > 0
    ok = ok and result["overall_severity"] in ("critical", "high")

    # 验证问题类型覆盖
    problem_types = {p["problem_type"] for p in result["problems"]}
    ok = ok and "deadlock" in problem_types  # jstack 死锁
    ok = ok and "error_cluster" in problem_types  # 日志错误聚类

    # 验证关联分析
    correlation_types = {c["type"] for c in result["correlations"]}
    ok = ok and len(correlation_types) > 0

    record("端到端-诊断流程", ok,
           f"problems={len(result['problems'])}, types={problem_types}, "
           f"correlations={len(result['correlations'])}, severity={result['overall_severity']}")


def test_diagnostic_report_to_llm_prompt():
    """测试 29: 诊断报告 LLM prompt 生成"""
    from app.domains.performance.analyzer.diagnostic_report import DiagnosticReportBuilder

    builder = DiagnosticReportBuilder()
    report = builder.build(jstack_dump=JSTACK_WITH_DEADLOCK, logs=TEST_LOGS)

    prompt = report.to_llm_prompt()

    # prompt 应是 JSON 字符串, 包含关键信息
    ok = isinstance(prompt, str) and len(prompt) > 0
    if ok:
        data = json.loads(prompt)
        ok = "problems_found" in data
        ok = ok and "overall_severity" in data
        ok = ok and "detected_problems" in data
    record("诊断报告-LLM prompt生成", ok)


# ================================================================== #
#  运行所有测试                                                      #
# ================================================================== #

def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("  性能诊断模块测试 — 开始")
    print("=" * 70 + "\n")

    # JStackParser
    test_jstack_parse_basic()
    test_jstack_deadlock_detection()
    test_jstack_blocked_threads()
    test_jstack_cpu_hotspot()
    test_jstack_empty_input()
    test_jstack_convenience_functions()

    # LogAnalyzer
    test_log_analyzer_basic()
    test_log_error_clustering()
    test_log_text_format()
    test_log_slow_operation()
    test_log_error_spike()
    test_log_severity()

    # DiagnosticReportBuilder
    test_diagnostic_report_jstack_only()
    test_diagnostic_report_logs_only()
    test_diagnostic_report_correlation()
    test_diagnostic_report_empty_input()
    test_diagnostic_report_convenience_function()

    # PerformanceDiagnosticAgent
    test_diagnostic_agent_class_definition()
    test_diagnostic_agent_fallback_analysis()
    test_diagnostic_agent_action_handler()

    # Agent 注册
    test_agent_registration()

    # API 路由
    test_api_diagnose_endpoint()
    test_api_diagnose_request_model()

    # PerformanceAnalysisAgent 集成
    test_analysis_agent_has_run_diagnosis()
    test_analysis_agent_returns_diagnosis_field()

    # 导出验证
    test_init_exports()
    test_analyzer_init_exports()

    # 端到端
    test_e2e_diagnostic_flow()
    test_diagnostic_report_to_llm_prompt()

    # 汇总
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = sum(1 for _, ok in RESULTS if not ok)
    total = len(RESULTS)
    print(f"  测试结果: {passed}/{total} 通过, {failed} 失败")
    if failed > 0:
        print("\n  失败项:")
        for name, ok in RESULTS:
            if not ok:
                print(f"    [FAIL] {name}")
    print("=" * 70 + "\n")

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
