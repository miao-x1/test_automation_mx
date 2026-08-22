"""
get_network_metrics — 网络性能指标采集工具

通过 Chrome DevTools Protocol 采集网络请求性能:
  - 网络请求列表 (URL/方法/状态码/资源类型)
  - 资源大小 (传输大小/解压大小)
  - 请求耗时 (持续时间/平均耗时)
  - 按资源类型和状态码分组统计
  - 最慢和最大的请求
  - 缓存命中率
  - 失败请求
"""
import asyncio
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "get_network_metrics"
TOOL_DESCRIPTION = """网络性能指标采集工具。通过 Chrome DevTools Protocol 采集页面加载过程中的所有网络请求。

采集指标:
- 请求总数和总大小
- 按资源类型分组统计 (document/script/stylesheet/image/xhr/fetch/font/other)
- 按HTTP状态码分组统计
- 最慢的10个请求
- 最大的10个请求
- 失败请求列表
- 缓存命中率
- 平均请求耗时

返回: 网络请求汇总统计、分组分布、Top请求详情。"""

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
            "description": "页面加载后额外等待时间(秒),用于采集延迟加载的资源。默认2.0",
            "default": 2.0,
        },
    },
    "required": ["url"],
}


async def execute(**kwargs) -> Dict[str, Any]:
    """执行网络性能指标采集

    Args:
        url: 目标页面URL
        headless: 无头模式 (默认True)
        wait_until: 加载完成判定 (默认networkidle)
        wait_after_load: 加载后等待秒数 (默认2.0)

    Returns:
        网络性能指标字典
    """
    url = kwargs.get("url", "")
    headless = kwargs.get("headless", True)
    wait_until = kwargs.get("wait_until", "networkidle")
    wait_after_load = kwargs.get("wait_after_load", 2.0)

    if not url:
        return {"error": "url 参数为必填项"}

    log.info(f"MCP get_network_metrics | url={url}")

    try:
        from app.domains.performance.cdp_collector import CDPCollector

        collector = CDPCollector(
            headless=headless,
            wait_until=wait_until,
        )
        network_metrics = await collector.collect_network_metrics(url)

        return {
            "status": "success",
            "url": url,
            "network_metrics": network_metrics,
        }

    except ImportError:
        return {
            "status": "error",
            "error": "CDP采集器依赖未安装, 请确保 playwright 已安装",
        }
    except Exception as e:
        log.exception(f"get_network_metrics 执行失败: {e}")
        return {
            "status": "error",
            "error": str(e)[:500],
            "url": url,
        }
