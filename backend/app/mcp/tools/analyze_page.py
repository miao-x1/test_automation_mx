"""
analyze_page - 页面分析工具

分析Web页面，提取UI元素、页面结构、交互信息。

支持两种模式：
1. URL模式：输入URL，自动抓取页面并分析
2. 图片模式：输入截图路径，使用视觉模型识别元素

调用后端能力：
  - PageCrawlerService: URL抓取 + DOM解析
  - ElementAgent: 视觉模型识别UI元素
  - InputRouterAgent: 多模态解析路由
"""
import json
from typing import Any, Dict

from app.core.logger import log

TOOL_NAME = "analyze_page"
TOOL_DESCRIPTION = """页面分析工具。分析Web页面，提取UI元素、页面结构和交互信息。

支持两种模式：
1. URL模式：输入页面URL，系统自动抓取页面DOM并提取可交互元素（按钮、输入框、链接等）。
2. 图片模式：输入截图文件路径，使用AI视觉模型识别页面元素和布局。

返回：页面标题、URL、元素列表（含标签、定位器、文本、类型等）。"""

TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "页面URL（URL模式）。如：https://example.com/login",
        },
        "image_paths": {
            "type": "array",
            "items": {"type": "string"},
            "description": "截图文件路径列表（图片模式）。如：[\"/uploads/screenshot1.png\"]",
        },
        "requirement": {
            "type": "string",
            "description": "附加需求描述（可选）。如：分析登录页面的表单元素",
        },
        "analyze_depth": {
            "type": "string",
            "enum": ["basic", "detailed"],
            "description": "分析深度。basic=仅提取元素列表，detailed=含元素关系和交互流。默认detailed",
        },
    },
}


async def execute(**kwargs) -> Dict[str, Any]:
    """
    执行页面分析

    Args:
        url: 页面URL（可选，与image_paths二选一）
        image_paths: 截图路径列表（可选）
        requirement: 附加需求描述
        analyze_depth: 分析深度 basic/detailed

    Returns:
        {
            "status": "success" | "error",
            "url": str,
            "title": str,
            "elements": [...],
            "element_count": int,
            "analysis": str,
            "duration": float,
        }
    """
    import time
    start = time.time()

    url = kwargs.get("url", "")
    image_paths = kwargs.get("image_paths", [])
    requirement = kwargs.get("requirement", "")
    analyze_depth = kwargs.get("analyze_depth", "detailed")

    if not url and not image_paths:
        return {"status": "error", "error": "必须提供 url 或 image_paths 参数"}

    log.info(f"[MCP analyze_page] 开始 | url={url}, images={len(image_paths)}")

    # 模式1：URL抓取
    if url:
        try:
            from app.services.page_crawler_service import PageCrawlerService
            from app.db.database import SessionLocal
            from app.models.task import Task, TaskStatus

            db = SessionLocal()
            try:
                # 创建抓取任务
                task = PageCrawlerService.create_crawl_task(db, url=url, task_name=f"MCP分析_{url[:30]}")
                task_id = task.id

                # 执行抓取
                elements = []
                async for chunk in PageCrawlerService.run_crawl(task_id, url):
                    try:
                        data = json.loads(chunk)
                        if data.get("step") == "元素提取完成":
                            elements = data.get("data", {}).get("elements", [])
                        elif data.get("step") == "页面分析完成":
                            page_info = data.get("data", {})
                            title = page_info.get("title", "")
                    except (json.JSONDecodeError, TypeError):
                        continue

                # 从数据库获取元素
                db_elements = PageCrawlerService.get_page_elements(db, task_id)

                result_elements = []
                for elem in db_elements:
                    result_elements.append({
                        "tag_name": elem.tag_name,
                        "text": elem.element_text,
                        "id": elem.element_id,
                        "class": elem.element_class,
                        "name": elem.element_name,
                        "placeholder": elem.placeholder,
                        "href": elem.href,
                        "aria_label": elem.aria_label,
                        "role": elem.role,
                        "xpath": elem.xpath,
                        "css_selector": elem.css_selector,
                    })

                duration = round(time.time() - start, 2)
                log.info(f"[MCP analyze_page] URL模式完成 | elements={len(result_elements)}, duration={duration}s")

                return {
                    "status": "success",
                    "mode": "url",
                    "url": url,
                    "task_id": task_id,
                    "title": elements[0].get("title", "") if elements else "",
                    "elements": result_elements,
                    "element_count": len(result_elements),
                    "duration": duration,
                }
            finally:
                db.close()

        except Exception as e:
            log.error(f"[MCP analyze_page] URL模式失败: {e}", exc_info=True)
            return {"status": "error", "error": f"URL分析失败: {e}", "duration": round(time.time() - start, 2)}

    # 模式2：图片分析
    if image_paths:
        try:
            from app.agent.requirement.parsers.image_analyzer_agent import ImageAnalyzerAgent

            agent = ImageAnalyzerAgent()
            import asyncio

            result = await agent.execute(
                payload={
                    "image_paths": image_paths,
                    "requirement": requirement,
                    "task_id": f"mcp_analyze_{int(time.time())}",
                    "session_key": "mcp",
                },
                ctx=None,
            )

            if result.get("status") == "success":
                ctx_data = result.get("context", {})
                duration = round(time.time() - start, 2)
                log.info(f"[MCP analyze_page] 图片模式完成 | duration={duration}s")

                return {
                    "status": "success",
                    "mode": "image",
                    "image_paths": image_paths,
                    "pages": ctx_data.get("pages", []),
                    "elements": ctx_data.get("elements", []),
                    "element_count": len(ctx_data.get("elements", [])),
                    "analysis": ctx_data.get("summary", ""),
                    "duration": duration,
                }
            else:
                return {"status": "error", "error": "图片分析返回失败", "duration": round(time.time() - start, 2)}

        except Exception as e:
            log.error(f"[MCP analyze_page] 图片模式失败: {e}", exc_info=True)
            return {"status": "error", "error": f"图片分析失败: {e}", "duration": round(time.time() - start, 2)}
