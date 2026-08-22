"""
Chrome DevTools Protocol 性能采集器

通过 Playwright 的 CDP Session 采集浏览器性能指标:
  1. 页面加载时间 (Navigation Timing API)
  2. 网络请求 (Network domain)
  3. JS 执行时间 (Runtime / Performance domain)
  4. DOM 数量 (DOM domain)
  5. 资源大小 (Network domain + Resource Timing API)

数据来源:
  - Chrome DevTools Protocol (CDP)
  - 浏览器 Performance API (window.performance)
  - Resource Timing API (performance.getEntriesByType)

使用方式:
  collector = CDPCollector()
  metrics = await collector.collect("https://example.com")

设计约束:
  - 纯采集, 不做分析 (分析由 PerformanceAnalysisAgent 负责)
  - 支持 headless 和 headful 模式
  - 采集完成后关闭浏览器, 不保持长连接
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 限制同时打开的 Playwright 浏览器实例数，避免并发过高导致进程泄漏
# 使用 asyncio.Semaphore 在异步上下文中控制并发
_PLAYWRIGHT_SEMAPHORE = asyncio.Semaphore(2)


# ================================================================
# 数据结构
# ================================================================

@dataclass
class PageMetrics:
    """页面加载指标"""
    url: str = ""
    title: str = ""
    # Navigation Timing
    dns_lookup_ms: float = 0
    tcp_connect_ms: float = 0
    ssl_handshake_ms: float = 0
    ttfb_ms: float = 0          # Time to First Byte
    dom_parse_ms: float = 0     # DOM 解析时间
    dom_ready_ms: float = 0     # DOMContentLoaded
    load_complete_ms: float = 0  # onload 完成时间
    # Performance API
    fcp_ms: float = 0           # First Contentful Paint
    lcp_ms: float = 0           # Largest Contentful Paint
    cls: float = 0              # Cumulative Layout Shift
    fid_ms: float = 0           # First Input Delay
    tbt_ms: float = 0           # Total Blocking Time
    # DOM 统计
    dom_nodes: int = 0
    dom_depth: int = 0
    js_heap_mb: float = 0
    js_event_listeners: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "dns_lookup_ms": round(self.dns_lookup_ms, 2),
            "tcp_connect_ms": round(self.tcp_connect_ms, 2),
            "ssl_handshake_ms": round(self.ssl_handshake_ms, 2),
            "ttfb_ms": round(self.ttfb_ms, 2),
            "dom_parse_ms": round(self.dom_parse_ms, 2),
            "dom_ready_ms": round(self.dom_ready_ms, 2),
            "load_complete_ms": round(self.load_complete_ms, 2),
            "fcp_ms": round(self.fcp_ms, 2),
            "lcp_ms": round(self.lcp_ms, 2),
            "cls": round(self.cls, 4),
            "fid_ms": round(self.fid_ms, 2),
            "tbt_ms": round(self.tbt_ms, 2),
            "dom_nodes": self.dom_nodes,
            "dom_depth": self.dom_depth,
            "js_heap_mb": round(self.js_heap_mb, 2),
            "js_event_listeners": self.js_event_listeners,
        }


@dataclass
class NetworkRequest:
    """单个网络请求"""
    url: str = ""
    method: str = "GET"
    status: int = 0
    resource_type: str = ""    # document/script/stylesheet/image/xhr/fetch/font/other
    duration_ms: float = 0
    size_bytes: int = 0
    transferred_bytes: int = 0
    from_cache: bool = False
    from_service_worker: bool = False
    initiator: str = ""        # 请求发起者 (script/parser/redirect等)
    priority: str = ""         # High/Medium/Low

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "method": self.method,
            "status": self.status,
            "resource_type": self.resource_type,
            "duration_ms": round(self.duration_ms, 2),
            "size_bytes": self.size_bytes,
            "transferred_bytes": self.transferred_bytes,
            "from_cache": self.from_cache,
            "initiator": self.initiator,
            "priority": self.priority,
        }


@dataclass
class NetworkMetrics:
    """网络指标汇总"""
    total_requests: int = 0
    total_size_bytes: int = 0
    total_transferred_bytes: int = 0
    by_resource_type: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    by_status: Dict[str, int] = field(default_factory=dict)
    slowest_requests: List[NetworkRequest] = field(default_factory=list)
    largest_requests: List[NetworkRequest] = field(default_factory=list)
    failed_requests: List[NetworkRequest] = field(default_factory=list)
    cache_hit_rate: float = 0
    avg_duration_ms: float = 0
    requests: List[NetworkRequest] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_requests": self.total_requests,
            "total_size_bytes": self.total_size_bytes,
            "total_transferred_bytes": self.total_transferred_bytes,
            "total_size_mb": round(self.total_size_bytes / 1024 / 1024, 2),
            "by_resource_type": self.by_resource_type,
            "by_status": self.by_status,
            "slowest_requests": [r.to_dict() for r in self.slowest_requests[:10]],
            "largest_requests": [r.to_dict() for r in self.largest_requests[:10]],
            "failed_requests": [r.to_dict() for r in self.failed_requests],
            "cache_hit_rate": round(self.cache_hit_rate, 2),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "request_count": len(self.requests),
        }


@dataclass
class JSMetrics:
    """JS 执行指标"""
    total_execution_time_ms: float = 0
    long_tasks_count: int = 0
    long_tasks_total_ms: float = 0
    longest_task_ms: float = 0
    function_call_count: int = 0
    tbt_ms: float = 0              # Total Blocking Time
    layout_recalc_count: int = 0
    style_recalc_count: int = 0
    gc_count: int = 0
    gc_total_ms: float = 0
    top_functions: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_execution_time_ms": round(self.total_execution_time_ms, 2),
            "long_tasks_count": self.long_tasks_count,
            "long_tasks_total_ms": round(self.long_tasks_total_ms, 2),
            "longest_task_ms": round(self.longest_task_ms, 2),
            "tbt_ms": round(self.tbt_ms, 2),
            "function_call_count": self.function_call_count,
            "layout_recalc_count": self.layout_recalc_count,
            "style_recalc_count": self.style_recalc_count,
            "gc_count": self.gc_count,
            "gc_total_ms": round(self.gc_total_ms, 2),
            "top_functions": self.top_functions[:10],
        }


@dataclass
class BrowserPerformanceReport:
    """浏览器性能报告 (完整)"""
    page: PageMetrics = field(default_factory=PageMetrics)
    network: NetworkMetrics = field(default_factory=NetworkMetrics)
    js: JSMetrics = field(default_factory=JSMetrics)
    collected_at: float = field(default_factory=time.time)
    collection_duration_ms: float = 0
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "page": self.page.to_dict(),
            "network": self.network.to_dict(),
            "js": self.js.to_dict(),
            "collected_at": self.collected_at,
            "collection_duration_ms": round(self.collection_duration_ms, 2),
            "errors": self.errors,
        }


# ================================================================
# CDP 采集器
# ================================================================

# 浏览器内执行的 JS 采集脚本
_PAGE_TIMING_JS = """
() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const paint = performance.getEntriesByType('paint');
    const fcp = paint.find(p => p.name === 'first-contentful-paint');
    const lcpEntries = performance.getEntriesByType('largest-contentful-paint');
    const lcp = lcpEntries.length > 0 ? lcpEntries[lcpEntries.length - 1] : null;

    // DOM 统计
    const allNodes = document.querySelectorAll('*').length;
    let maxDepth = 0;
    function checkDepth(el, depth) {
        if (depth > maxDepth) maxDepth = depth;
        for (const child of el.children) checkDepth(child, depth + 1);
    }
    checkDepth(document.body, 0);

    // 事件监听器统计 (近似)
    let listenerCount = 0;
    document.querySelectorAll('*').forEach(el => {
        // 无法精确获取, 使用近似值
    });

    return {
        url: location.href,
        title: document.title,
        dns_lookup_ms: nav.domainLookupEnd - nav.domainLookupStart || 0,
        tcp_connect_ms: nav.connectEnd - nav.connectStart || 0,
        ssl_handshake_ms: nav.connectEnd - nav.secureConnectionStart || 0,
        ttfb_ms: nav.responseStart - nav.requestStart || 0,
        dom_parse_ms: nav.domInteractive - nav.responseEnd || 0,
        dom_ready_ms: nav.domContentLoadedEventEnd - nav.startTime || 0,
        load_complete_ms: nav.loadEventEnd - nav.startTime || 0,
        fcp_ms: fcp ? fcp.startTime : 0,
        lcp_ms: lcp ? lcp.startTime : 0,
        dom_nodes: allNodes,
        dom_depth: maxDepth,
        js_heap_mb: performance.memory ? performance.memory.usedJSHeapSize / 1024 / 1024 : 0,
        js_event_listeners: 0,
    };
}
"""

_RESOURCE_TIMING_JS = """
() => {
    const entries = performance.getEntriesByType('resource');
    return entries.map(e => ({
        url: e.name,
        duration_ms: e.duration,
        size_bytes: e.transferSize || 0,
        transferred_bytes: e.encodedBodySize || 0,
        initiator_type: e.initiatorType,
        resource_type: e.initiatorType,
        from_cache: e.transferSize === 0 && e.decodedBodySize > 0,
    }));
}
"""

_LONG_TASKS_JS = """
() => {
    const observer = new PerformanceObserver(() => {});
    observer.observe({entryTypes: ['longtask']});
    const tasks = performance.getEntriesByType('longtask');
    return tasks.map(t => ({
        duration_ms: t.duration,
        start_time: t.startTime,
    }));
}
"""

_CLS_JS = """
() => {
    const entries = performance.getEntriesByType('layout-shift');
    let cls = 0;
    for (const e of entries) {
        if (!e.hadRecentInput) cls += e.value;
    }
    return cls;
}
"""


class CDPCollector:
    """Chrome DevTools Protocol 性能采集器

    使用 Playwright 连接 Chrome 浏览器, 通过 CDP Session 采集性能指标。
    采集完成后关闭浏览器, 不保持长连接。

    使用方式:
        collector = CDPCollector()
        report = await collector.collect("https://example.com")
        # 或单独采集
        page_metrics = await collector.collect_page_metrics("https://example.com")
        network_metrics = await collector.collect_network_metrics("https://example.com")
    """

    def __init__(
        self,
        headless: bool = True,
        timeout_ms: int = 30000,
        wait_until: str = "networkidle",
    ) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self.wait_until = wait_until

    async def collect(
        self, url: str, wait_after_load: float = 2.0,
    ) -> BrowserPerformanceReport:
        """完整采集浏览器性能指标

        Args:
            url: 目标页面 URL
            wait_after_load: 页面加载后额外等待时间 (秒), 用于采集后续动态指标

        Returns:
            BrowserPerformanceReport 完整性能报告
        """
        start_time = time.time()
        report = BrowserPerformanceReport()
        report.page.url = url

        try:
            from playwright.async_api import async_playwright
        except ImportError:
            report.errors.append("playwright 未安装, 请运行 pip install playwright")
            report.collection_duration_ms = (time.time() - start_time) * 1000
            return report

        network_requests: List[NetworkRequest] = []
        long_tasks: List[Dict] = []

        try:
            # 限制并发打开浏览器，防止系统资源被耗尽
            await _PLAYWRIGHT_SEMAPHORE.acquire()
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=self.headless,
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--no-sandbox",
                            "--disable-web-security",
                        ],
                    )

                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        ignore_https_errors=True,
                    )

                    page = await context.new_page()

                    # 开启 CDP Session
                    client = await page.context.new_cdp_session(page)

                    # 启用 Network domain (必须在导航前启用)
                    await client.send("Network.enable")
                    await client.send("Performance.enable")
                    await client.send("Runtime.enable")

                    # 注册网络请求事件监听
                    request_map: Dict[str, NetworkRequest] = {}

                    def _on_request(params: Dict) -> None:
                        req_id = params.get("requestId", "")
                        request = params.get("request", {})
                        req = NetworkRequest(
                            url=request.get("url", ""),
                            method=request.get("method", "GET"),
                            resource_type="other",
                            initiator=str(params.get("initiator", {}).get("type", "")),
                        )
                        request_map[req_id] = req

                    def _on_response(params: Dict) -> None:
                        req_id = params.get("requestId", "")
                        response = params.get("response", {})
                        if req_id in request_map:
                            req = request_map[req_id]
                            req.status = response.get("status", 0)
                            req.resource_type = response.get("mimeType", "").split("/")[0] or "other"
                            req.from_service_worker = response.get("fromServiceWorker", False)
                            # 更精确的 resource_type 映射
                            mime = response.get("mimeType", "")
                            req.resource_type = self._classify_resource_type(mime, req.url)

                    def _on_loading_finished(params: Dict) -> None:
                        req_id = params.get("requestId", "")
                        if req_id in request_map:
                            req = request_map[req_id]
                            encoded = params.get("encodedDataLength", 0)
                            req.transferred_bytes = encoded
                            req.size_bytes = encoded

                    def _on_loading_failed(params: Dict) -> None:
                        req_id = params.get("requestId", "")
                        if req_id in request_map:
                            req = request_map[req_id]
                            req.status = -1  # 标记失败
                            network_requests.append(req)

                    client.on("Network.requestWillBeSent", _on_request)
                    client.on("Network.responseReceived", _on_response)
                    client.on("Network.loadingFinished", _on_loading_finished)
                    client.on("Network.loadingFailed", _on_loading_failed)

                    # 导航到目标页面
                    logger.info(f"[CDPCollector] 导航到 {url}")
                    try:
                        await page.goto(
                            url, wait_until=self.wait_until,
                            timeout=self.timeout_ms,
                        )
                    except Exception as e:
                        report.errors.append(f"页面导航失败: {str(e)[:200]}")

                    # 额外等待 (让动态内容加载)
                    await asyncio.sleep(wait_after_load)

                    # 采集页面指标
                    try:
                        timing_data = await page.evaluate(_PAGE_TIMING_JS)
                        self._fill_page_metrics(report.page, timing_data)
                    except Exception as e:
                        report.errors.append(f"页面指标采集失败: {str(e)[:200]}")

                    # 采集 CLS
                    try:
                        cls_value = await page.evaluate(_CLS_JS)
                        report.page.cls = cls_value if isinstance(cls_value, (int, float)) else 0
                    except Exception:
                        pass

                    # 采集 Resource Timing (补充网络数据)
                    try:
                        resource_entries = await page.evaluate(_RESOURCE_TIMING_JS)
                        self._merge_resource_timing(network_requests, resource_entries, request_map)
                    except Exception as e:
                        report.errors.append(f"Resource Timing 采集失败: {str(e)[:200]}")

                    # 采集长任务
                    try:
                        long_tasks = await page.evaluate(_LONG_TASKS_JS) or []
                    except Exception:
                        long_tasks = []

                    # 采集 CDP Performance metrics
                    try:
                        perf_metrics = await client.send("Performance.getMetrics")
                        self._fill_js_metrics(report.js, perf_metrics, long_tasks)
                    except Exception as e:
                        report.errors.append(f"Performance metrics 采集失败: {str(e)[:200]}")

                    # 采集 DOM 指标
                    try:
                        dom_count = await page.evaluate("document.querySelectorAll('*').length")
                        report.page.dom_nodes = dom_count or 0
                    except Exception:
                        pass

                    # 获取页面标题
                    try:
                        report.page.title = await page.title()
                    except Exception:
                        pass

                    await context.close()
                    await browser.close()
            finally:
                try:
                    _PLAYWRIGHT_SEMAPHORE.release()
                except Exception:
                    pass
        except Exception as e:
            report.errors.append(f"浏览器采集异常: {str(e)[:300]}")
            logger.exception(f"[CDPCollector] 采集异常: {e}")

        except Exception as e:
            report.errors.append(f"浏览器采集异常: {str(e)[:300]}")
            logger.exception(f"[CDPCollector] 采集异常: {e}")

        # 处理网络请求汇总
        self._build_network_metrics(report.network, network_requests)

        report.collection_duration_ms = (time.time() - start_time) * 1000
        logger.info(
            f"[CDPCollector] 采集完成: {url}, "
            f"requests={report.network.total_requests}, "
            f"dom_nodes={report.page.dom_nodes}, "
            f"duration={report.collection_duration_ms:.0f}ms"
        )

        return report

    async def collect_page_metrics(self, url: str) -> Dict[str, Any]:
        """仅采集页面加载指标"""
        report = await self.collect(url)
        return report.page.to_dict()

    async def collect_network_metrics(self, url: str) -> Dict[str, Any]:
        """仅采集网络指标"""
        report = await self.collect(url)
        return report.network.to_dict()

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    @staticmethod
    def _classify_resource_type(mime_type: str, url: str) -> str:
        """根据 MIME 类型分类资源"""
        mime = mime_type.lower()
        if "html" in mime:
            return "document"
        if "javascript" in mime or url.endswith(".js") or url.endswith(".mjs"):
            return "script"
        if "css" in mime:
            return "stylesheet"
        if "image" in mime:
            return "image"
        if "font" in mime or url.endswith((".woff", ".woff2", ".ttf", ".otf")):
            return "font"
        if "json" in mime or "xml" in mime:
            return "xhr"
        if "video" in mime or "audio" in mime:
            return "media"
        return "other"

    @staticmethod
    def _fill_page_metrics(page: PageMetrics, data: Dict[str, Any]) -> None:
        """从 JS 采集数据填充 PageMetrics"""
        page.url = data.get("url", page.url)
        page.title = data.get("title", "")
        page.dns_lookup_ms = data.get("dns_lookup_ms", 0)
        page.tcp_connect_ms = data.get("tcp_connect_ms", 0)
        page.ssl_handshake_ms = data.get("ssl_handshake_ms", 0)
        page.ttfb_ms = data.get("ttfb_ms", 0)
        page.dom_parse_ms = data.get("dom_parse_ms", 0)
        page.dom_ready_ms = data.get("dom_ready_ms", 0)
        page.load_complete_ms = data.get("load_complete_ms", 0)
        page.fcp_ms = data.get("fcp_ms", 0)
        page.lcp_ms = data.get("lcp_ms", 0)
        page.dom_nodes = data.get("dom_nodes", 0)
        page.dom_depth = data.get("dom_depth", 0)
        page.js_heap_mb = data.get("js_heap_mb", 0)
        page.js_event_listeners = data.get("js_event_listeners", 0)

    def _merge_resource_timing(
        self,
        requests: List[NetworkRequest],
        resource_entries: List[Dict],
        cdp_requests: Dict[str, NetworkRequest],
    ) -> None:
        """合并 Resource Timing API 数据到 CDP 采集的请求列表"""
        # 将 CDP 采集的请求先加入列表
        for req in cdp_requests.values():
            if req not in requests:
                requests.append(req)

        # 用 Resource Timing 补充缺失的 duration
        timing_map: Dict[str, Dict] = {}
        for entry in resource_entries:
            timing_map[entry.get("url", "")] = entry

        for req in requests:
            if req.duration_ms == 0 and req.url in timing_map:
                entry = timing_map[req.url]
                req.duration_ms = entry.get("duration_ms", 0)
                if req.size_bytes == 0:
                    req.size_bytes = entry.get("size_bytes", 0)
                if req.from_cache is False and entry.get("from_cache"):
                    req.from_cache = True
                if not req.resource_type:
                    req.resource_type = entry.get("resource_type", "other")

    def _fill_js_metrics(
        self, js: JSMetrics, perf_metrics: Dict, long_tasks: List[Dict],
    ) -> None:
        """填充 JS 执行指标"""
        metrics_list = perf_metrics.get("metrics", [])
        metrics_map = {m.get("name"): m.get("value", 0) for m in metrics_list}

        js.total_execution_time_ms = metrics_map.get("TaskDuration", 0) * 1000
        js.function_call_count = int(metrics_map.get("JSHeapUsedSize", 0))
        js.layout_recalc_count = int(metrics_map.get("LayoutCount", 0))
        js.style_recalc_count = int(metrics_map.get("RecalcStyleCount", 0))
        js.gc_count = int(metrics_map.get("JSHeapUsedSize", 0) and 0)  # CDP 无直接 GC 计数

        # 长任务
        if long_tasks:
            js.long_tasks_count = len(long_tasks)
            js.long_tasks_total_ms = sum(t.get("duration_ms", 0) for t in long_tasks)
            js.longest_task_ms = max(t.get("duration_ms", 0) for t in long_tasks)
            js.tbt_ms = sum(
                max(0, t.get("duration_ms", 0) - 50) for t in long_tasks
            )

    def _build_network_metrics(
        self, net: NetworkMetrics, requests: List[NetworkRequest],
    ) -> None:
        """构建网络指标汇总"""
        net.requests = requests
        net.total_requests = len(requests)

        if not requests:
            return

        total_size = 0
        total_transferred = 0
        total_duration = 0
        cache_hits = 0
        by_type: Dict[str, Dict[str, Any]] = {}
        by_status: Dict[str, int] = {}

        for req in requests:
            total_size += req.size_bytes
            total_transferred += req.transferred_bytes
            total_duration += req.duration_ms

            if req.from_cache:
                cache_hits += 1

            # 按资源类型分组
            rtype = req.resource_type or "other"
            if rtype not in by_type:
                by_type[rtype] = {"count": 0, "size_bytes": 0, "duration_ms": 0}
            by_type[rtype]["count"] += 1
            by_type[rtype]["size_bytes"] += req.size_bytes
            by_type[rtype]["duration_ms"] += req.duration_ms

            # 按状态码分组
            status_key = str(req.status // 100) + "xx" if req.status > 0 else "failed"
            by_status[status_key] = by_status.get(status_key, 0) + 1

            # 失败请求
            if req.status == -1 or req.status >= 400:
                net.failed_requests.append(req)

        net.total_size_bytes = total_size
        net.total_transferred_bytes = total_transferred
        net.by_resource_type = {
            k: {
                "count": v["count"],
                "size_mb": round(v["size_bytes"] / 1024 / 1024, 2),
                "duration_ms": round(v["duration_ms"], 2),
            }
            for k, v in by_type.items()
        }
        net.by_status = by_status
        net.cache_hit_rate = (cache_hits / len(requests) * 100) if requests else 0
        net.avg_duration_ms = total_duration / len(requests) if requests else 0

        # 最慢和最大的请求
        net.slowest_requests = sorted(requests, key=lambda r: r.duration_ms, reverse=True)
        net.largest_requests = sorted(requests, key=lambda r: r.size_bytes, reverse=True)


# ================================================================
# 浏览器扩展数据接收器 (支持浏览器插件推送数据)
# ================================================================

class BrowserExtensionReceiver:
    """浏览器扩展数据接收器

    接收来自浏览器插件的性能数据推送。
    浏览器插件可以在页面运行时持续采集指标, 通过 HTTP 推送到此接收器。

    使用方式:
        receiver = BrowserExtensionReceiver()
        # 接收插件推送的数据
        report = receiver.ingest(extension_data)
    """

    def ingest(self, data: Dict[str, Any]) -> BrowserPerformanceReport:
        """接收浏览器插件推送的性能数据

        Args:
            data: 浏览器插件推送的数据, 格式:
                {
                    "url": "https://example.com",
                    "title": "Example",
                    "timing": {...},
                    "network": [...],
                    "js": {...},
                    "long_tasks": [...],
                }

        Returns:
            BrowserPerformanceReport 性能报告
        """
        report = BrowserPerformanceReport()
        report.collected_at = time.time()

        # 页面指标
        timing = data.get("timing", {})
        report.page = PageMetrics(
            url=data.get("url", ""),
            title=data.get("title", ""),
            dns_lookup_ms=timing.get("dns_lookup_ms", 0),
            tcp_connect_ms=timing.get("tcp_connect_ms", 0),
            ssl_handshake_ms=timing.get("ssl_handshake_ms", 0),
            ttfb_ms=timing.get("ttfb_ms", 0),
            dom_parse_ms=timing.get("dom_parse_ms", 0),
            dom_ready_ms=timing.get("dom_ready_ms", 0),
            load_complete_ms=timing.get("load_complete_ms", 0),
            fcp_ms=timing.get("fcp_ms", 0),
            lcp_ms=timing.get("lcp_ms", 0),
            cls=timing.get("cls", 0),
            dom_nodes=timing.get("dom_nodes", 0),
            dom_depth=timing.get("dom_depth", 0),
            js_heap_mb=timing.get("js_heap_mb", 0),
        )

        # 网络指标
        network_data = data.get("network", [])
        requests = []
        for item in network_data:
            requests.append(NetworkRequest(
                url=item.get("url", ""),
                method=item.get("method", "GET"),
                status=item.get("status", 0),
                resource_type=item.get("resource_type", "other"),
                duration_ms=item.get("duration_ms", 0),
                size_bytes=item.get("size_bytes", 0),
                transferred_bytes=item.get("transferred_bytes", 0),
                from_cache=item.get("from_cache", False),
            ))

        collector = CDPCollector()
        collector._build_network_metrics(report.network, requests)

        # JS 指标
        js_data = data.get("js", {})
        long_tasks = data.get("long_tasks", [])
        report.js = JSMetrics(
            total_execution_time_ms=js_data.get("total_execution_time_ms", 0),
            long_tasks_count=len(long_tasks),
            long_tasks_total_ms=sum(t.get("duration_ms", 0) for t in long_tasks),
            longest_task_ms=max((t.get("duration_ms", 0) for t in long_tasks), default=0),
            tbt_ms=sum(max(0, t.get("duration_ms", 0) - 50) for t in long_tasks),
            layout_recalc_count=js_data.get("layout_recalc_count", 0),
            style_recalc_count=js_data.get("style_recalc_count", 0),
        )

        return report


# ================================================================
# 便捷函数
# ================================================================

async def collect_browser_performance(
    url: str, headless: bool = True, wait_after_load: float = 2.0,
) -> Dict[str, Any]:
    """采集浏览器性能指标 (便捷函数)

    Args:
        url: 目标页面 URL
        headless: 是否无头模式
        wait_after_load: 页面加载后额外等待时间

    Returns:
        性能报告字典
    """
    collector = CDPCollector(headless=headless)
    report = await collector.collect(url, wait_after_load=wait_after_load)
    return report.to_dict()


async def get_page_load_metrics(url: str) -> Dict[str, Any]:
    """获取页面加载指标 (便捷函数)"""
    collector = CDPCollector()
    return await collector.collect_page_metrics(url)


async def get_network_performance(url: str) -> Dict[str, Any]:
    """获取网络性能指标 (便捷函数)"""
    collector = CDPCollector()
    return await collector.collect_network_metrics(url)
