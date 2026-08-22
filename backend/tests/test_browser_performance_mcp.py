"""
浏览器性能监控 MCP Server 测试

测试覆盖:
  1. CDP 采集器数据结构: PageMetrics / NetworkRequest / NetworkMetrics / JSMetrics / BrowserPerformanceReport
  2. CDP 采集器内部方法: _classify_resource_type / _fill_page_metrics / _merge_resource_timing
                         _fill_js_metrics / _build_network_metrics
  3. BrowserExtensionReceiver: 浏览器插件数据接收
  4. MCP 工具 get_page_metrics: TOOL_NAME / TOOL_SCHEMA / execute (参数校验)
  5. MCP 工具 get_network_metrics: TOOL_NAME / TOOL_SCHEMA / execute (参数校验)
  6. MCP 工具 get_performance_report: TOOL_NAME / TOOL_SCHEMA / execute (降级分析)
  7. MCP 工具注册: __init__.py ALL_TOOLS 包含 3 个新工具
  8. PerformanceAnalysisAgent: browser_analyze action / _build_browser_prompt / _fallback_browser_analysis
  9. 端到端流程: BrowserExtensionReceiver → Agent browser_analyze → 规则分析
"""
import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# ===== Stub 3rd-party modules (与 test_performance_diagnostic.py 一致) =====
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

# mcp stub (MCP SDK 未安装时)
_mcp = types.ModuleType("mcp")
_mcp_server = types.ModuleType("mcp.server")
_mcp_server.Server = _make_class("Server")
_mcp_server_sse = types.ModuleType("mcp.server.sse")
_mcp_server_sse.SseServerTransport = _make_class("SseServerTransport")
_mcp_server_http = types.ModuleType("mcp.server.streamable_http")
_mcp_server_http.StreamableHTTPServerTransport = _make_class("StreamableHTTPServerTransport")
_mcp_types = types.ModuleType("mcp.types")
_mcp_types.Tool = _make_class("Tool")
_mcp_types.TextContent = _make_class("TextContent")
_mcp.server = _mcp_server
_mcp.types = _mcp_types
sys.modules["mcp"] = _mcp
sys.modules["mcp.server"] = _mcp_server
sys.modules["mcp.server.sse"] = _mcp_server_sse
sys.modules["mcp.server.streamable_http"] = _mcp_server_http
sys.modules["mcp.types"] = _mcp_types


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
#  1. CDP 采集器数据结构                                              #
# ================================================================== #

def test_page_metrics_dataclass():
    """测试 1: PageMetrics 数据结构"""
    from app.domains.performance.cdp_collector import PageMetrics

    pm = PageMetrics(
        url="https://example.com",
        title="Example",
        dns_lookup_ms=10.5,
        tcp_connect_ms=20.3,
        ssl_handshake_ms=15.2,
        ttfb_ms=120.0,
        dom_parse_ms=300.0,
        dom_ready_ms=500.0,
        load_complete_ms=2000.0,
        fcp_ms=800.0,
        lcp_ms=1500.0,
        cls=0.05,
        dom_nodes=850,
        dom_depth=15,
        js_heap_mb=45.5,
    )

    d = pm.to_dict()
    ok = d["url"] == "https://example.com"
    ok = ok and d["ttfb_ms"] == 120.0
    ok = ok and d["load_complete_ms"] == 2000.0
    ok = ok and d["fcp_ms"] == 800.0
    ok = ok and d["lcp_ms"] == 1500.0
    ok = ok and d["cls"] == 0.05
    ok = ok and d["dom_nodes"] == 850
    record("PageMetrics-数据结构", ok)


def test_network_request_dataclass():
    """测试 2: NetworkRequest 数据结构"""
    from app.domains.performance.cdp_collector import NetworkRequest

    req = NetworkRequest(
        url="https://example.com/style.css",
        method="GET",
        status=200,
        resource_type="stylesheet",
        duration_ms=45.3,
        size_bytes=51200,
        transferred_bytes=12000,
        from_cache=False,
        from_service_worker=False,
        initiator="parser",
        priority="High",
    )

    d = req.to_dict()
    ok = d["url"] == "https://example.com/style.css"
    ok = ok and d["status"] == 200
    ok = ok and d["resource_type"] == "stylesheet"
    ok = ok and d["size_bytes"] == 51200
    record("NetworkRequest-数据结构", ok)


def test_network_metrics_dataclass():
    """测试 3: NetworkMetrics 数据结构 (含 MB 转换)"""
    from app.domains.performance.cdp_collector import NetworkMetrics, NetworkRequest

    nm = NetworkMetrics()
    nm.total_requests = 50
    nm.total_size_bytes = 3 * 1024 * 1024  # 3 MB
    nm.total_transferred_bytes = 1 * 1024 * 1024  # 1 MB
    nm.cache_hit_rate = 30.0
    nm.avg_duration_ms = 120.5
    nm.requests = [NetworkRequest(url="https://example.com")]

    d = nm.to_dict()
    ok = d["total_requests"] == 50
    ok = ok and d["total_size_mb"] == 3.0
    ok = ok and d["cache_hit_rate"] == 30.0
    ok = ok and d["request_count"] == 1
    record("NetworkMetrics-数据结构", ok)


def test_js_metrics_dataclass():
    """测试 4: JSMetrics 数据结构"""
    from app.domains.performance.cdp_collector import JSMetrics

    js = JSMetrics(
        total_execution_time_ms=500.0,
        long_tasks_count=3,
        long_tasks_total_ms=450.0,
        longest_task_ms=200.0,
        tbt_ms=300.0,
        layout_recalc_count=15,
        style_recalc_count=20,
    )

    d = js.to_dict()
    ok = d["long_tasks_count"] == 3
    ok = ok and d["long_tasks_total_ms"] == 450.0
    ok = ok and d["tbt_ms"] == 300.0
    ok = ok and d["layout_recalc_count"] == 15
    record("JSMetrics-数据结构", ok)


def test_browser_performance_report_dataclass():
    """测试 5: BrowserPerformanceReport 完整报告结构"""
    from app.domains.performance.cdp_collector import (
        BrowserPerformanceReport, PageMetrics, NetworkMetrics, JSMetrics,
    )

    report = BrowserPerformanceReport()
    report.page = PageMetrics(url="https://test.com", load_complete_ms=1500)
    report.network = NetworkMetrics(total_requests=30)
    report.js = JSMetrics(long_tasks_count=2)
    report.errors = ["minor warning"]

    d = report.to_dict()
    ok = "page" in d and "network" in d and "js" in d
    ok = ok and d["page"]["url"] == "https://test.com"
    ok = ok and d["network"]["total_requests"] == 30
    ok = ok and d["js"]["long_tasks_count"] == 2
    ok = ok and len(d["errors"]) == 1
    record("BrowserPerformanceReport-完整结构", ok)


# ================================================================== #
#  2. CDP 采集器内部方法                                              #
# ================================================================== #

def test_classify_resource_type():
    """测试 6: _classify_resource_type MIME 类型分类"""
    from app.domains.performance.cdp_collector import CDPCollector

    cls = CDPCollector._classify_resource_type
    ok = cls("text/html", "https://example.com") == "document"
    ok = ok and cls("application/javascript", "https://example.com/app.js") == "script"
    ok = ok and cls("text/css", "https://example.com/style.css") == "stylesheet"
    ok = ok and cls("image/png", "https://example.com/logo.png") == "image"
    ok = ok and cls("font/woff2", "https://example.com/font.woff2") == "font"
    ok = ok and cls("application/json", "https://example.com/api") == "xhr"
    ok = ok and cls("video/mp4", "https://example.com/video.mp4") == "media"
    ok = ok and cls("application/octet-stream", "https://example.com/file") == "other"
    record("CDP-MIME类型分类", ok)


def test_fill_page_metrics():
    """测试 7: _fill_page_metrics 从 JS 数据填充"""
    from app.domains.performance.cdp_collector import CDPCollector, PageMetrics

    page = PageMetrics()
    data = {
        "url": "https://filled.com",
        "title": "Filled Page",
        "dns_lookup_ms": 5.0,
        "ttfb_ms": 100.0,
        "load_complete_ms": 2000.0,
        "fcp_ms": 700.0,
        "lcp_ms": 1200.0,
        "dom_nodes": 500,
        "dom_depth": 12,
        "js_heap_mb": 30.0,
    }

    CDPCollector._fill_page_metrics(page, data)
    ok = page.url == "https://filled.com"
    ok = ok and page.title == "Filled Page"
    ok = ok and page.ttfb_ms == 100.0
    ok = ok and page.load_complete_ms == 2000.0
    ok = ok and page.fcp_ms == 700.0
    ok = ok and page.dom_nodes == 500
    record("CDP-页面指标填充", ok)


def test_build_network_metrics():
    """测试 8: _build_network_metrics 网络汇总计算"""
    from app.domains.performance.cdp_collector import CDPCollector, NetworkMetrics, NetworkRequest

    requests = [
        NetworkRequest(url="https://a.com", status=200, resource_type="script",
                       duration_ms=100, size_bytes=50000, transferred_bytes=20000),
        NetworkRequest(url="https://b.com", status=200, resource_type="image",
                       duration_ms=200, size_bytes=100000, transferred_bytes=80000),
        NetworkRequest(url="https://c.com", status=404, resource_type="document",
                       duration_ms=50, size_bytes=5000, transferred_bytes=5000),
        NetworkRequest(url="https://d.com", status=200, resource_type="script",
                       duration_ms=300, size_bytes=0, transferred_bytes=0, from_cache=True),
    ]

    collector = CDPCollector()
    net = NetworkMetrics()
    collector._build_network_metrics(net, requests)

    ok = net.total_requests == 4
    ok = ok and net.total_size_bytes == 155000
    ok = ok and net.avg_duration_ms == 162.5
    ok = ok and net.cache_hit_rate == 25.0  # 1/4 = 25%
    ok = ok and "script" in net.by_resource_type
    ok = ok and net.by_resource_type["script"]["count"] == 2
    ok = ok and "2xx" in net.by_status
    ok = ok and "4xx" in net.by_status
    ok = ok and len(net.failed_requests) == 1  # 404 is failed
    ok = ok and net.slowest_requests[0].duration_ms == 300  # slowest
    record("CDP-网络汇总计算", ok,
           f"total={net.total_requests}, avg={net.avg_duration_ms}, "
           f"cache={net.cache_hit_rate}%, failed={len(net.failed_requests)}")


def test_fill_js_metrics():
    """测试 9: _fill_js_metrics JS 指标填充 (含长任务)"""
    from app.domains.performance.cdp_collector import CDPCollector, JSMetrics

    perf_metrics = {
        "metrics": [
            {"name": "TaskDuration", "value": 0.5},
            {"name": "LayoutCount", "value": 10},
            {"name": "RecalcStyleCount", "value": 15},
        ]
    }
    long_tasks = [
        {"duration_ms": 80, "start_time": 100},
        {"duration_ms": 120, "start_time": 200},
        {"duration_ms": 60, "start_time": 300},
    ]

    collector = CDPCollector()
    js = JSMetrics()
    collector._fill_js_metrics(js, perf_metrics, long_tasks)

    ok = js.long_tasks_count == 3
    ok = ok and js.long_tasks_total_ms == 260
    ok = ok and js.longest_task_ms == 120
    ok = ok and js.tbt_ms == 110  # (80-50) + (120-50) + (60-50) = 30+70+10 = 110
    ok = ok and js.layout_recalc_count == 10
    ok = ok and js.style_recalc_count == 15
    record("CDP-JS指标填充", ok,
           f"long_tasks={js.long_tasks_count}, tbt={js.tbt_ms}ms, "
           f"longest={js.longest_task_ms}ms")


def test_merge_resource_timing():
    """测试 10: _merge_resource_timing 合并 Resource Timing 数据"""
    from app.domains.performance.cdp_collector import CDPCollector, NetworkRequest

    cdp_requests = {
        "req1": NetworkRequest(url="https://a.com", duration_ms=0, size_bytes=0),
        "req2": NetworkRequest(url="https://b.com", duration_ms=100, size_bytes=50000),
    }
    requests = []

    resource_entries = [
        {"url": "https://a.com", "duration_ms": 150, "size_bytes": 30000,
         "from_cache": True, "resource_type": "script"},
        {"url": "https://b.com", "duration_ms": 200, "size_bytes": 60000,
         "from_cache": False, "resource_type": "image"},
    ]

    collector = CDPCollector()
    collector._merge_resource_timing(requests, resource_entries, cdp_requests)

    # 2 CDP requests should be merged in
    ok = len(requests) == 2

    # req1 should get duration and size from Resource Timing
    req1 = next(r for r in requests if r.url == "https://a.com")
    ok = ok and req1.duration_ms == 150
    ok = ok and req1.size_bytes == 30000
    ok = ok and req1.from_cache is True
    ok = ok and req1.resource_type == "script"

    # req2 should NOT be overwritten (already has duration)
    req2 = next(r for r in requests if r.url == "https://b.com")
    ok = ok and req2.duration_ms == 100  # unchanged
    record("CDP-ResourceTiming合并", ok)


# ================================================================== #
#  3. BrowserExtensionReceiver 浏览器插件数据接收                     #
# ================================================================== #

def test_browser_extension_receiver_ingest():
    """测试 11: BrowserExtensionReceiver 接收插件数据"""
    from app.domains.performance.cdp_collector import BrowserExtensionReceiver

    extension_data = {
        "url": "https://example.com",
        "title": "Example Page",
        "timing": {
            "dns_lookup_ms": 5,
            "tcp_connect_ms": 15,
            "ttfb_ms": 80,
            "dom_ready_ms": 400,
            "load_complete_ms": 1200,
            "fcp_ms": 600,
            "lcp_ms": 1100,
            "cls": 0.03,
            "dom_nodes": 600,
            "js_heap_mb": 25.0,
        },
        "network": [
            {"url": "https://example.com/app.js", "status": 200, "resource_type": "script",
             "duration_ms": 80, "size_bytes": 100000, "transferred_bytes": 30000},
            {"url": "https://example.com/style.css", "status": 200, "resource_type": "stylesheet",
             "duration_ms": 40, "size_bytes": 50000, "transferred_bytes": 10000},
            {"url": "https://example.com/missing.png", "status": 404, "resource_type": "image",
             "duration_ms": 20, "size_bytes": 0, "transferred_bytes": 0},
        ],
        "js": {
            "total_execution_time_ms": 300,
            "layout_recalc_count": 8,
            "style_recalc_count": 12,
        },
        "long_tasks": [
            {"duration_ms": 80},
            {"duration_ms": 60},
        ],
    }

    receiver = BrowserExtensionReceiver()
    report = receiver.ingest(extension_data)

    ok = report.page.url == "https://example.com"
    ok = ok and report.page.title == "Example Page"
    ok = ok and report.page.ttfb_ms == 80
    ok = ok and report.page.load_complete_ms == 1200
    ok = ok and report.page.dom_nodes == 600
    ok = ok and report.network.total_requests == 3
    ok = ok and report.network.total_size_bytes == 150000
    ok = ok and len(report.network.failed_requests) == 1  # 404
    ok = ok and report.js.long_tasks_count == 2
    ok = ok and report.js.long_tasks_total_ms == 140
    ok = ok and report.js.tbt_ms == 40  # (80-50) + (60-50) = 30+10 = 40
    record("BrowserExtensionReceiver-数据接收", ok,
           f"page.url={report.page.url}, requests={report.network.total_requests}, "
           f"long_tasks={report.js.long_tasks_count}")


def test_browser_extension_receiver_empty():
    """测试 12: BrowserExtensionReceiver 空数据处理"""
    from app.domains.performance.cdp_collector import BrowserExtensionReceiver

    receiver = BrowserExtensionReceiver()
    report = receiver.ingest({})

    ok = report.page.url == ""
    ok = ok and report.network.total_requests == 0
    ok = ok and report.js.long_tasks_count == 0
    record("BrowserExtensionReceiver-空数据", ok)


# ================================================================== #
#  4. MCP 工具 get_page_metrics                                       #
# ================================================================== #

def test_get_page_metrics_tool_definition():
    """测试 13: get_page_metrics 工具定义"""
    from app.mcp.tools.get_page_metrics import (
        TOOL_NAME, TOOL_DESCRIPTION, TOOL_SCHEMA, execute,
    )

    ok = TOOL_NAME == "get_page_metrics"
    ok = ok and "页面性能" in TOOL_DESCRIPTION
    ok = ok and "url" in TOOL_SCHEMA["properties"]
    ok = ok and "url" in TOOL_SCHEMA.get("required", [])
    ok = ok and "headless" in TOOL_SCHEMA["properties"]
    ok = ok and "wait_until" in TOOL_SCHEMA["properties"]
    ok = ok and callable(execute)
    record("get_page_metrics-工具定义", ok)


def test_get_page_metrics_missing_url():
    """测试 14: get_page_metrics 缺少 url 参数返回错误"""
    from app.mcp.tools.get_page_metrics import execute

    result = asyncio.get_event_loop().run_until_complete(execute(url=""))
    ok = "error" in result
    ok = ok and "url" in result.get("error", "").lower()
    record("get_page_metrics-缺少URL参数", ok)


# ================================================================== #
#  5. MCP 工具 get_network_metrics                                    #
# ================================================================== #

def test_get_network_metrics_tool_definition():
    """测试 15: get_network_metrics 工具定义"""
    from app.mcp.tools.get_network_metrics import (
        TOOL_NAME, TOOL_DESCRIPTION, TOOL_SCHEMA, execute,
    )

    ok = TOOL_NAME == "get_network_metrics"
    ok = ok and "网络" in TOOL_DESCRIPTION
    ok = ok and "url" in TOOL_SCHEMA["properties"]
    ok = ok and "url" in TOOL_SCHEMA.get("required", [])
    ok = ok and callable(execute)
    record("get_network_metrics-工具定义", ok)


def test_get_network_metrics_missing_url():
    """测试 16: get_network_metrics 缺少 url 参数返回错误"""
    from app.mcp.tools.get_network_metrics import execute

    result = asyncio.get_event_loop().run_until_complete(execute(url=""))
    ok = "error" in result
    ok = ok and "url" in result.get("error", "").lower()
    record("get_network_metrics-缺少URL参数", ok)


# ================================================================== #
#  6. MCP 工具 get_performance_report                                 #
# ================================================================== #

def test_get_performance_report_tool_definition():
    """测试 17: get_performance_report 工具定义"""
    from app.mcp.tools.get_performance_report import (
        TOOL_NAME, TOOL_DESCRIPTION, TOOL_SCHEMA, execute,
    )

    ok = TOOL_NAME == "get_performance_report"
    ok = ok and "性能报告" in TOOL_DESCRIPTION or "综合" in TOOL_DESCRIPTION
    ok = ok and "url" in TOOL_SCHEMA["properties"]
    ok = ok and "analyze" in TOOL_SCHEMA["properties"]
    ok = ok and "url" in TOOL_SCHEMA.get("required", [])
    ok = ok and callable(execute)
    record("get_performance_report-工具定义", ok)


def test_get_performance_report_missing_url():
    """测试 18: get_performance_report 缺少 url 参数返回错误"""
    from app.mcp.tools.get_performance_report import execute

    result = asyncio.get_event_loop().run_until_complete(execute(url=""))
    ok = "error" in result
    ok = ok and "url" in result.get("error", "").lower()
    record("get_performance_report-缺少URL参数", ok)


def test_get_performance_report_fallback_analysis():
    """测试 19: get_performance_report 降级分析 (规则分析)"""
    from app.mcp.tools.get_performance_report import _fallback_browser_analysis, _generate_recommendations

    report = {
        "page": {
            "url": "https://slow.com",
            "load_complete_ms": 6000,
            "ttfb_ms": 1500,
            "fcp_ms": 2500,
            "lcp_ms": 5000,
            "cls": 0.3,
            "dom_nodes": 2500,
        },
        "network": {
            "total_requests": 120,
            "total_size_mb": 8.0,
            "failed_requests": [{"url": "https://broken.com"}],
        },
        "js": {
            "long_tasks_count": 15,
            "tbt_ms": 800,
        },
    }

    result = _fallback_browser_analysis(report)
    analysis = result.get("analysis", {})

    ok = analysis.get("score", 100) < 60  # multiple severe issues → FAIL
    ok = ok and analysis.get("verdict") == "FAIL"
    ok = ok and len(analysis.get("bottlenecks", [])) > 0
    ok = ok and len(analysis.get("recommendations", [])) > 0
    record("get_performance_report-降级分析", ok,
           f"score={analysis.get('score')}, verdict={analysis.get('verdict')}, "
           f"bottlenecks={len(analysis.get('bottlenecks', []))}")


def test_get_performance_report_fallback_good_page():
    """测试 20: get_performance_report 降级分析 (良好页面)"""
    from app.mcp.tools.get_performance_report import _fallback_browser_analysis

    report = {
        "page": {
            "url": "https://fast.com",
            "load_complete_ms": 1500,
            "ttfb_ms": 200,
            "fcp_ms": 800,
            "lcp_ms": 1500,
            "cls": 0.02,
            "dom_nodes": 500,
        },
        "network": {
            "total_requests": 30,
            "total_size_mb": 1.5,
            "failed_requests": [],
        },
        "js": {
            "long_tasks_count": 1,
            "tbt_ms": 50,
        },
    }

    result = _fallback_browser_analysis(report)
    analysis = result.get("analysis", {})

    ok = analysis.get("score", 0) >= 80
    ok = ok and analysis.get("verdict") == "PASS"
    record("get_performance_report-良好页面分析", ok,
           f"score={analysis.get('score')}, verdict={analysis.get('verdict')}")


def test_generate_recommendations():
    """测试 21: _generate_recommendations 优化建议生成"""
    from app.mcp.tools.get_performance_report import _generate_recommendations

    page = {"ttfb_ms": 800, "lcp_ms": 3000, "cls": 0.15, "dom_nodes": 1800}
    network = {"total_requests": 90, "total_size_mb": 4.0}
    js = {"long_tasks_count": 8}
    problems = ["TTFB过高", "LCP偏慢"]

    recs = _generate_recommendations(page, network, js, problems)

    ok = len(recs) > 0
    # Should contain CDN advice (ttfb > 600)
    ok = ok and any("CDN" in r or "缓存" in r for r in recs)
    # Should contain LCP advice (lcp > 2500)
    ok = ok and any("LCP" in r or "首屏" in r for r in recs)
    # Should contain DOM advice (dom > 1500)
    ok = ok and any("DOM" in r for r in recs)
    # Should contain request reduction advice
    ok = ok and any("请求" in r or "合并" in r for r in recs)
    record("get_performance_report-优化建议生成", ok,
           f"recs={len(recs)}")


# ================================================================== #
#  7. MCP 工具注册验证                                                #
# ================================================================== #

def test_mcp_tools_registered():
    """测试 22: __init__.py 注册 3 个浏览器性能工具"""
    from app.mcp.tools import ALL_TOOLS

    tool_names = [t[0] for t in ALL_TOOLS]
    ok = "get_page_metrics" in tool_names
    ok = ok and "get_network_metrics" in tool_names
    ok = ok and "get_performance_report" in tool_names
    record("MCP工具注册-3个浏览器工具", ok,
           f"tools={tool_names}")


def test_mcp_tools_count():
    """测试 23: ALL_TOOLS 包含至少 7 个工具 (4核心 + 3浏览器)"""
    from app.mcp.tools import ALL_TOOLS

    ok = len(ALL_TOOLS) >= 7
    record("MCP工具注册-工具数量", ok,
           f"count={len(ALL_TOOLS)}")


def test_mcp_tools_all_callable():
    """测试 24: 所有工具的 execute 函数可调用"""
    from app.mcp.tools import ALL_TOOLS

    ok = all(callable(t[3]) for t in ALL_TOOLS)
    record("MCP工具注册-execute可调用", ok)


# ================================================================== #
#  8. PerformanceAnalysisAgent browser_analyze                       #
# ================================================================== #

def test_analysis_agent_has_browser_analyze():
    """测试 25: PerformanceAnalysisAgent 有 browser_analyze action"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()
    ok = hasattr(agent, "handle_browser_analyze")
    record("分析Agent-browser_analyze方法", ok)


def test_analysis_agent_browser_system_prompt():
    """测试 26: BROWSER_SYSTEM_PROMPT 包含 Web Vitals 标准"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    ok = hasattr(PerformanceAnalysisAgent, "BROWSER_SYSTEM_PROMPT")
    if ok:
        prompt = PerformanceAnalysisAgent.BROWSER_SYSTEM_PROMPT
        ok = "FCP" in prompt and "LCP" in prompt and "CLS" in prompt
        ok = ok and "2500ms" in prompt  # LCP standard
    record("分析Agent-浏览器SystemPrompt", ok)


def test_analysis_agent_build_browser_prompt():
    """测试 27: _build_browser_prompt 构建 LLM 分析 prompt"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()
    page = {"ttfb_ms": 200, "load_complete_ms": 1500, "fcp_ms": 800, "lcp_ms": 1500,
            "cls": 0.05, "dom_nodes": 500}
    network = {"total_requests": 30, "total_size_mb": 1.5, "cache_hit_rate": 40,
               "by_resource_type": {"script": {"count": 5}}, "failed_requests": []}
    js = {"long_tasks_count": 2, "tbt_ms": 80}

    prompt = agent._build_browser_prompt(page, network, js, "https://test.com")

    data = json.loads(prompt)
    ok = data["url"] == "https://test.com"
    ok = ok and "page_metrics" in data
    ok = ok and "network_metrics" in data
    ok = ok and "js_metrics" in data
    ok = ok and data["page_metrics"]["ttfb_ms"] == 200
    ok = ok and data["js_metrics"]["long_tasks_count"] == 2
    record("分析Agent-浏览器Prompt构建", ok)


def test_analysis_agent_fallback_browser_analysis_good():
    """测试 28: _fallback_browser_analysis 良好页面"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()
    page = {"load_complete_ms": 1200, "ttfb_ms": 200, "fcp_ms": 700, "lcp_ms": 1200,
            "cls": 0.02, "dom_nodes": 400}
    network = {"total_requests": 25, "total_size_mb": 1.0, "failed_requests": [],
               "cache_hit_rate": 50}
    js = {"long_tasks_count": 1, "tbt_ms": 30}

    result = agent._fallback_browser_analysis(page, network, js)

    ok = result["verdict"] == "PASS"
    ok = ok and result["score"] >= 80
    record("分析Agent-降级分析良好页面", ok,
           f"score={result['score']}, verdict={result['verdict']}")


def test_analysis_agent_fallback_browser_analysis_bad():
    """测试 29: _fallback_browser_analysis 问题页面"""
    from app.domains.performance.agents import PerformanceAnalysisAgent

    agent = PerformanceAnalysisAgent()
    page = {"load_complete_ms": 6000, "ttfb_ms": 1200, "fcp_ms": 2500, "lcp_ms": 5000,
            "cls": 0.3, "dom_nodes": 2500}
    network = {"total_requests": 150, "total_size_mb": 8.0,
               "failed_requests": [{"url": "x"}], "cache_hit_rate": 10}
    js = {"long_tasks_count": 15, "tbt_ms": 700}

    result = agent._fallback_browser_analysis(page, network, js)

    ok = result["verdict"] == "FAIL"
    ok = ok and result["score"] < 60
    ok = ok and len(result["bottlenecks"]) > 3
    ok = ok and len(result["recommendations"]) > 0
    record("分析Agent-降级分析问题页面", ok,
           f"score={result['score']}, verdict={result['verdict']}, "
           f"bottlenecks={len(result['bottlenecks'])}")


# ================================================================== #
#  9. 端到端流程测试                                                  #
# ================================================================== #

def test_e2e_extension_to_agent_analysis():
    """测试 30: 端到端流程 (浏览器插件数据 → Agent browser_analyze → 规则分析)

    模拟完整流程:
      1. BrowserExtensionReceiver 接收插件数据 → BrowserPerformanceReport
      2. report.to_dict() → browser_report
      3. PerformanceAnalysisAgent._fallback_browser_analysis → 分析结论
    """
    from app.domains.performance.cdp_collector import BrowserExtensionReceiver
    from app.domains.performance.agents import PerformanceAnalysisAgent

    # Step 1: 模拟浏览器插件推送数据
    extension_data = {
        "url": "https://slow-site.com",
        "title": "Slow Site",
        "timing": {
            "dns_lookup_ms": 50,
            "tcp_connect_ms": 100,
            "ttfb_ms": 1500,
            "dom_ready_ms": 3000,
            "load_complete_ms": 6000,
            "fcp_ms": 2500,
            "lcp_ms": 5000,
            "cls": 0.3,
            "dom_nodes": 2500,
            "dom_depth": 20,
            "js_heap_mb": 80.0,
        },
        "network": [
            {"url": f"https://slow-site.com/resource_{i}.js", "status": 200,
             "resource_type": "script", "duration_ms": 100 + i * 10,
             "size_bytes": 50000 * i, "transferred_bytes": 20000 * i}
            for i in range(1, 101)  # 100 requests
        ] + [
            {"url": "https://slow-site.com/broken.png", "status": 500,
             "resource_type": "image", "duration_ms": 2000,
             "size_bytes": 0, "transferred_bytes": 0},
        ],
        "js": {
            "total_execution_time_ms": 800,
            "layout_recalc_count": 50,
            "style_recalc_count": 80,
        },
        "long_tasks": [
            {"duration_ms": 100 + i * 20}
            for i in range(12)
        ],
    }

    # Step 2: 接收并转换
    receiver = BrowserExtensionReceiver()
    report = receiver.ingest(extension_data)
    report_dict = report.to_dict()

    # 验证采集数据
    ok = report.page.load_complete_ms == 6000
    ok = ok and report.page.ttfb_ms == 1500
    ok = ok and report.network.total_requests == 101
    ok = ok and len(report.network.failed_requests) == 1  # 500 error
    ok = ok and report.js.long_tasks_count == 12

    # Step 3: Agent 规则分析 (降级, 不走 LLM)
    agent = PerformanceAnalysisAgent()
    analysis = agent._fallback_browser_analysis(
        report_dict["page"], report_dict["network"], report_dict["js"],
    )

    ok = ok and analysis["verdict"] == "FAIL"
    ok = ok and analysis["score"] < 60
    ok = ok and len(analysis["bottlenecks"]) >= 3
    ok = ok and len(analysis["recommendations"]) >= 3

    record("端到端-插件→Agent分析", ok,
           f"采集: load={report.page.load_complete_ms}ms, "
           f"requests={report.network.total_requests}, "
           f"分析: score={analysis['score']}, verdict={analysis['verdict']}, "
           f"bottlenecks={len(analysis['bottlenecks'])}")


def test_e2e_good_page_flow():
    """测试 31: 端到端流程 (良好页面 → PASS)"""
    from app.domains.performance.cdp_collector import BrowserExtensionReceiver
    from app.domains.performance.agents import PerformanceAnalysisAgent

    extension_data = {
        "url": "https://fast-site.com",
        "title": "Fast Site",
        "timing": {
            "ttfb_ms": 150,
            "dom_ready_ms": 500,
            "load_complete_ms": 1200,
            "fcp_ms": 600,
            "lcp_ms": 1200,
            "cls": 0.02,
            "dom_nodes": 400,
            "js_heap_mb": 20.0,
        },
        "network": [
            {"url": "https://fast-site.com/app.js", "status": 200,
             "resource_type": "script", "duration_ms": 50, "size_bytes": 30000,
             "transferred_bytes": 10000},
            {"url": "https://fast-site.com/style.css", "status": 200,
             "resource_type": "stylesheet", "duration_ms": 30, "size_bytes": 10000,
             "transferred_bytes": 3000},
        ],
        "js": {"layout_recalc_count": 5, "style_recalc_count": 8},
        "long_tasks": [{"duration_ms": 55}],
    }

    receiver = BrowserExtensionReceiver()
    report = receiver.ingest(extension_data)
    report_dict = report.to_dict()

    agent = PerformanceAnalysisAgent()
    analysis = agent._fallback_browser_analysis(
        report_dict["page"], report_dict["network"], report_dict["js"],
    )

    ok = analysis["verdict"] == "PASS"
    ok = ok and analysis["score"] >= 80
    record("端到端-良好页面PASS", ok,
           f"score={analysis['score']}, verdict={analysis['verdict']}")


def test_e2e_cdp_datastructures_serialization():
    """测试 32: CDP 采集器完整数据序列化 (to_dict 往返)"""
    from app.domains.performance.cdp_collector import (
        BrowserPerformanceReport, PageMetrics, NetworkMetrics, JSMetrics,
        NetworkRequest,
    )

    report = BrowserPerformanceReport()
    report.page = PageMetrics(
        url="https://test.com", title="Test", ttfb_ms=100,
        load_complete_ms=1500, fcp_ms=600, lcp_ms=1200,
        cls=0.05, dom_nodes=500, js_heap_mb=30.0,
    )
    report.network = NetworkMetrics(total_requests=10)
    report.network.requests = [NetworkRequest(url="https://test.com/r1", status=200)]
    report.js = JSMetrics(long_tasks_count=2, tbt_ms=80)

    # 序列化为 dict
    d = report.to_dict()

    # 验证可以 JSON 序列化
    json_str = json.dumps(d, ensure_ascii=False)
    ok = len(json_str) > 0

    # 反序列化验证
    parsed = json.loads(json_str)
    ok = ok and parsed["page"]["url"] == "https://test.com"
    ok = ok and parsed["network"]["total_requests"] == 10
    ok = ok and parsed["js"]["long_tasks_count"] == 2

    record("端到端-数据序列化往返", ok)


# ================================================================== #
#  10. MCP Server 路由验证                                            #
# ================================================================== #

def test_mcp_server_docstring_updated():
    """测试 33: server.py docstring 更新为 12 个工具"""
    from app.mcp import server

    doc = server.__doc__ or ""
    ok = "12" in doc or "get_page_metrics" in doc
    record("MCP Server-docstring更新", ok)


# ================================================================== #
#  运行所有测试                                                      #
# ================================================================== #

def run_all_tests():
    """运行所有测试"""
    print("\n" + "=" * 70)
    print("  浏览器性能监控 MCP Server 测试 — 开始")
    print("=" * 70 + "\n")

    # CDP 数据结构
    test_page_metrics_dataclass()
    test_network_request_dataclass()
    test_network_metrics_dataclass()
    test_js_metrics_dataclass()
    test_browser_performance_report_dataclass()

    # CDP 内部方法
    test_classify_resource_type()
    test_fill_page_metrics()
    test_build_network_metrics()
    test_fill_js_metrics()
    test_merge_resource_timing()

    # BrowserExtensionReceiver
    test_browser_extension_receiver_ingest()
    test_browser_extension_receiver_empty()

    # MCP 工具 get_page_metrics
    test_get_page_metrics_tool_definition()
    test_get_page_metrics_missing_url()

    # MCP 工具 get_network_metrics
    test_get_network_metrics_tool_definition()
    test_get_network_metrics_missing_url()

    # MCP 工具 get_performance_report
    test_get_performance_report_tool_definition()
    test_get_performance_report_missing_url()
    test_get_performance_report_fallback_analysis()
    test_get_performance_report_fallback_good_page()
    test_generate_recommendations()

    # MCP 工具注册
    test_mcp_tools_registered()
    test_mcp_tools_count()
    test_mcp_tools_all_callable()

    # PerformanceAnalysisAgent browser_analyze
    test_analysis_agent_has_browser_analyze()
    test_analysis_agent_browser_system_prompt()
    test_analysis_agent_build_browser_prompt()
    test_analysis_agent_fallback_browser_analysis_good()
    test_analysis_agent_fallback_browser_analysis_bad()

    # 端到端
    test_e2e_extension_to_agent_analysis()
    test_e2e_good_page_flow()
    test_e2e_cdp_datastructures_serialization()

    # MCP Server
    test_mcp_server_docstring_updated()

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
