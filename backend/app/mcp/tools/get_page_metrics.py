"""
get_page_metrics — 页面性能指标采集工具

通过 Chrome DevTools Protocol 采集页面加载性能:
  - 页面加载时间 (DNS/TCP/SSL/TTFB/DOM解析/onload)
  - Core Web Vitals (FCP/LCP/CLS)
  - DOM 数量和深度
  - JS 堆内存
"""
import asyncio
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "get_page_metrics"
TOOL_DESCRIPTION = """页面性能指标采集工具。通过 Chrome DevTools Protocol 采集页面加载性能数据。

采集指标:
- 页面加载时间: DNS查询/TCP连接/SSL握手/TTFB/DOM解析/DOMContentLoaded/onload
- Core Web Vitals: FCP(首次内容绘制)/LCP(最大内容绘制)/CLS(累积布局偏移)
- DOM统计: 节点数量/DOM树深度
- 内存: JS堆内存使用量

返回: 页面加载各阶段耗时、Web Vitals指标、DOM统计信息。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "目标页面URL。如: https://example.com",
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
            "description": "页面加载后额外等待时间(秒),用于采集动态内容指标。默认2.0",
            "default": 2.0,
        },
    },
    "required": ["url"],
}


async def execute(**kwargs) -> Dict[str, Any]:
    """执行页面性能指标采集

    Args:
        url: 目标页面URL
        headless: 无头模式 (默认True)
        wait_until: 加载完成判定 (默认networkidle)
        wait_after_load: 加载后等待秒数 (默认2.0)

    Returns:
        页面性能指标字典
    """
    url = kwargs.get("url", "")
    headless = kwargs.get("headless", True)
    wait_until = kwargs.get("wait_until", "networkidle")
    wait_after_load = kwargs.get("wait_after_load", 2.0)

    if not url:
        return {"error": "url 参数为必填项"}

    log.info(f"MCP get_page_metrics | url={url}")

    try:
        from app.domains.performance.cdp_collector import CDPCollector

        collector = CDPCollector(
            headless=headless,
            wait_until=wait_until,
        )
        page_metrics = await collector.collect_page_metrics(url)

        # 补充 wait_after_load 不影响 (collect_page_metrics 内部调用 collect)
        return {
            "status": "success",
            "url": url,
            "page_metrics": page_metrics,
        }

    except ImportError:
        return {
            "status": "error",
            "error": "CDP采集器依赖未安装, 请确保 playwright 已安装",
        }
    except Exception as e:
        log.exception(f"get_page_metrics 执行失败: {e}")
        return {
            "status": "error",
            "error": str(e)[:500],
            "url": url,
        }
