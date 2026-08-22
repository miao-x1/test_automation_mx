"""
get_performance_report — 综合性能报告工具

采集完整的浏览器性能指标并生成综合报告:
  1. 页面加载指标 (Navigation Timing + Web Vitals)
  2. 网络请求指标 (CDP Network domain)
  3. JS 执行指标 (长任务/布局重计算/样式重计算)
  4. 自动接入 PerformanceAnalysisAgent 进行 LLM 分析

流程:
  浏览器 → CDP 采集 → 综合报告 → PerformanceAnalysisAgent → 分析结论
"""
import asyncio
import json
from typing import Any, Dict, List

from app.core.logger import log

TOOL_NAME = "get_performance_report"
TOOL_DESCRIPTION = """综合浏览器性能报告工具。采集完整的浏览器性能指标并生成综合分析报告。

采集维度:
1. 页面加载: DNS/TCP/SSL/TTFB/DOM解析/加载完成时间, FCP/LCP/CLS
2. 网络请求: 请求总数/资源大小/按类型分组/最慢最大请求/失败请求/缓存命中率
3. JS执行: 长任务数量/总阻塞时间/布局重计算/样式重计算/GC统计
4. DOM统计: 节点数量/树深度/JS堆内存

分析能力:
- 采集完成后自动接入 PerformanceAnalysisAgent 进行 LLM 性能分析
- 识别性能瓶颈 (慢请求/大资源/过多DOM/长任务等)
- 给出优化建议

参数:
- url: 目标页面URL (必填)
- analyze: 是否自动调用AI分析 (默认true)
- headless: 无头浏览器模式 (默认true)

返回: 完整性能报告 + AI分析结论 (当analyze=true时)。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "目标页面URL。如: https://example.com",
        },
        "analyze": {
            "type": "boolean",
            "description": "是否自动调用AI性能分析。默认true",
            "default": True,
        },
        "headless": {
            "type": "boolean",
            "description": "是否使用无头浏览器模式。默认true",
            "default": True,
        },
        "wait_until": {
            "type": "string",
            "enum": ["load", "domcontentloaded", "networkidle"],
            "description": "页面加载完成判定条件。默认networkidle",
            "default": "networkidle",
        },
        "wait_after_load": {
            "type": "number",
            "description": "页面加载后额外等待时间(秒)。默认2.0",
            "default": 2.0,
        },
    },
    "required": ["url"],
}


async def execute(**kwargs) -> Dict[str, Any]:
    """执行综合性能报告采集和分析

    流程:
      1. CDP 采集器采集完整浏览器性能指标
      2. (可选) 调用 PerformanceAnalysisAgent 进行 LLM 分析

    Args:
        url: 目标页面URL
        analyze: 是否调用AI分析 (默认True)
        headless: 无头模式 (默认True)
        wait_until: 加载完成判定
        wait_after_load: 加载后等待秒数

    Returns:
        综合性能报告 + AI分析结论
    """
    url = kwargs.get("url", "")
    do_analyze = kwargs.get("analyze", True)
    headless = kwargs.get("headless", True)
    wait_until = kwargs.get("wait_until", "networkidle")
    wait_after_load = kwargs.get("wait_after_load", 2.0)

    if not url:
        return {"error": "url 参数为必填项"}

    log.info(f"MCP get_performance_report | url={url}, analyze={do_analyze}")

    try:
        from app.domains.performance.cdp_collector import CDPCollector

        # 1. 采集完整性能数据
        collector = CDPCollector(
            headless=headless,
            wait_until=wait_until,
        )
        report = await collector.collect(url, wait_after_load=wait_after_load)
        report_dict = report.to_dict()

        result: Dict[str, Any] = {
            "status": "success",
            "url": url,
            "report": report_dict,
        }

        # 2. (可选) 调用 PerformanceAnalysisAgent 进行 LLM 分析
        if do_analyze and not report.errors:
            analysis = await _run_browser_analysis(report_dict)
            if analysis:
                result["analysis"] = analysis

        return result

    except ImportError:
        return {
            "status": "error",
            "error": "CDP采集器依赖未安装, 请确保 playwright 已安装",
        }
    except Exception as e:
        log.exception(f"get_performance_report 执行失败: {e}")
        return {
            "status": "error",
            "error": str(e)[:500],
            "url": url,
        }


async def _run_browser_analysis(report: Dict[str, Any]) -> Dict[str, Any]:
    """调用 PerformanceAnalysisAgent 分析浏览器性能数据

    将浏览器性能报告转换为 Agent 可分析的格式,
    通过 AgentFactory 创建 PerformanceAnalysisAgent 并执行 browser_analyze action。
    """
    try:
        from app.agents.factory.factory import AgentFactory

        factory = AgentFactory()
        agent = await factory.create("performance_analysis_agent")

        result = await agent.execute({
            "action": "browser_analyze",
            "browser_report": report,
            "url": report.get("page", {}).get("url", ""),
        }, ctx=None)

        return result

    except Exception as e:
        log.warning(f"浏览器性能AI分析失败, 返回规则分析: {e}")
        return _fallback_browser_analysis(report)


def _fallback_browser_analysis(report: Dict[str, Any]) -> Dict[str, Any]:
    """降级分析 (LLM 不可用时, 基于规则)"""
    page = report.get("page", {})
    network = report.get("network", {})
    js = report.get("js", {})

    problems = []
    score = 100

    # 页面加载时间分析
    load_time = page.get("load_complete_ms", 0)
    if load_time > 5000:
        score -= 25
        problems.append(f"页面加载时间过长: {load_time:.0f}ms (建议<3000ms)")
    elif load_time > 3000:
        score -= 10
        problems.append(f"页面加载时间偏慢: {load_time:.0f}ms")

    # TTFB 分析
    ttfb = page.get("ttfb_ms", 0)
    if ttfb > 1000:
        score -= 15
        problems.append(f"TTFB过高: {ttfb:.0f}ms (建议<600ms)")

    # LCP 分析
    lcp = page.get("lcp_ms", 0)
    if lcp > 4000:
        score -= 20
        problems.append(f"LCP(最大内容绘制)过慢: {lcp:.0f}ms (建议<2500ms)")
    elif lcp > 2500:
        score -= 10
        problems.append(f"LCP偏慢: {lcp:.0f}ms")

    # CLS 分析
    cls = page.get("cls", 0)
    if cls > 0.25:
        score -= 15
        problems.append(f"CLS(布局偏移)严重: {cls} (建议<0.1)")
    elif cls > 0.1:
        score -= 5

    # DOM 数量分析
    dom_nodes = page.get("dom_nodes", 0)
    if dom_nodes > 2000:
        score -= 15
        problems.append(f"DOM节点过多: {dom_nodes} (建议<1500)")
    elif dom_nodes > 1500:
        score -= 5

    # 网络请求分析
    total_req = network.get("total_requests", 0)
    if total_req > 100:
        score -= 10
        problems.append(f"网络请求过多: {total_req} (建议<80)")

    total_size_mb = network.get("total_size_mb", 0)
    if total_size_mb > 5:
        score -= 15
        problems.append(f"资源总大小过大: {total_size_mb}MB (建议<3MB)")
    elif total_size_mb > 3:
        score -= 5

    failed = network.get("failed_requests", [])
    if failed:
        score -= 10
        problems.append(f"失败请求: {len(failed)}个")

    # 长任务分析
    long_tasks = js.get("long_tasks_count", 0)
    if long_tasks > 10:
        score -= 15
        problems.append(f"长任务过多: {long_tasks}个 (建议<5)")
    elif long_tasks > 5:
        score -= 5

    tbt = js.get("tbt_ms", 0)
    if tbt > 600:
        score -= 15
        problems.append(f"总阻塞时间过长: {tbt:.0f}ms (建议<300ms)")

    score = max(0, score)
    verdict = "PASS" if score >= 80 else ("CONDITIONAL" if score >= 60 else "FAIL")

    return {
        "status": "success",
        "analysis": {
            "summary": f"浏览器性能评分: {score}/100, {'良好' if verdict == 'PASS' else '需优化'}",
            "score": score,
            "problems": problems,
            "bottlenecks": problems[:3],
            "recommendations": _generate_recommendations(page, network, js, problems),
            "verdict": verdict,
        },
    }


def _generate_recommendations(
    page: Dict, network: Dict, js: Dict, problems: List[str],
) -> List[str]:
    """基于检测结果生成优化建议"""
    recs = []

    if page.get("ttfb_ms", 0) > 600:
        recs.append("优化服务端响应时间: 使用CDN、启用缓存、优化数据库查询")

    if page.get("lcp_ms", 0) > 2500:
        recs.append("优化LCP: 压缩首屏图片、预加载关键资源、减少渲染阻塞资源")

    if page.get("cls", 0) > 0.1:
        recs.append("优化CLS: 为图片/视频设置尺寸属性、避免动态插入内容")

    if page.get("dom_nodes", 0) > 1500:
        recs.append("精简DOM结构: 减少不必要的嵌套、使用虚拟滚动、延迟渲染非可视内容")

    if network.get("total_requests", 0) > 80:
        recs.append("减少网络请求: 合并CSS/JS文件、使用雪碧图、内联关键资源")

    if network.get("total_size_mb", 0) > 3:
        recs.append("减小资源体积: 启用Gzip/Brotli压缩、压缩图片、使用WebP格式")

    if js.get("long_tasks_count", 0) > 5:
        recs.append("优化长任务: 拆分大块JS执行、使用requestIdleCallback、代码分割")

    if not recs:
        recs.append("页面性能良好, 建议持续监控")

    return recs
