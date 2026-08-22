"""
MCP Server - Model Context Protocol 适配层

将平台能力开放给外部AI客户端（如 Claude、Cursor、Cherry Studio 等）。

支持3种传输协议：
  - stdio:           独立进程模式，通过标准输入输出通信
  - sse:             /mcp/sse，Server-Sent Events（MCP 2024-11-05 协议）
  - streamable-http:  /mcp/，Streamable HTTP（MCP 2025-03-26 协议）

暴露12个工具（7新 + 5旧）：

  核心测试工具（tools/ 目录，4个）：
    1. analyze_page          — 页面分析（URL抓取/图片识别）
    2. generate_testcase     — 生成测试用例（需求→用例）
    3. generate_script       — 生成测试脚本（需求→脚本，支持类型自动识别）
    4. execute_test          — 执行测试（任务ID/脚本内容/资产ID）

  浏览器性能监控工具（tools/ 目录，3个）：
    5. get_page_metrics      — 页面性能指标采集 (加载时间/DOM/Web Vitals)
    6. get_network_metrics   — 网络性能指标采集 (请求/资源大小/分组统计)
    7. get_performance_report — 综合性能报告 + AI分析

  保留5个旧工具（兼容已有客户端）：
    8. create_task        — 创建测试任务
    9. execute_task       — 执行测试任务（旧版）
   10. query_task         — 查询任务状态
   11. query_graph        — 查询知识图谱
   12. generate_script    — 生成测试脚本（旧版，已被新工具替代但保留兼容）

架构：
  tools/         — 4个新工具模块（每个导出 TOOL_NAME/SCHEMA/DESCRIPTION/execute）
  server.py      — MCP Server 定义 + FastAPI 集成 + stdio 入口
"""
import json
import asyncio
from typing import Any
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import StreamableHTTPServerTransport
from mcp.types import Tool, TextContent

from app.core.logger import log


# ==================== 工具实现（适配层） ====================

def _create_task(requirement: str, additional_info: str = "", script_format: str = "playwright") -> dict:
    """创建测试任务（同步，收集SSE结果）"""
    from app.services.requirement_flow_service import RequirementFlowService

    results = []
    task_id = None
    final_data = None

    for chunk in RequirementFlowService.generate(
        requirement=requirement,
        execute=False,
        additional_info=additional_info or None,
        script_format=script_format,
    ):
        try:
            data = json.loads(chunk)
            step = data.get("step", "")
            if "任务创建" in step and data.get("data", {}).get("task_id"):
                task_id = data["data"]["task_id"]
            if step == "任务完成":
                final_data = data.get("data", {})
            results.append({"step": step, "progress": data.get("progress", 0), "message": data.get("message", "")})
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "task_id": task_id,
        "status": "completed",
        "steps": results,
        "final": final_data,
    }


def _execute_task(task_id: int) -> dict:
    """执行测试任务"""
    from app.services.requirement_flow_service import RequirementFlowService
    from app.db.database import SessionLocal
    from app.models.requirement_task import RequirementTask

    db = SessionLocal()
    try:
        req_task = db.query(RequirementTask).filter(RequirementTask.id == task_id).first()
        if not req_task:
            return {"error": f"任务 {task_id} 不存在"}
    finally:
        db.close()

    results = []
    final_data = None

    for chunk in RequirementFlowService.execute_only(requirement_id=task_id):
        try:
            data = json.loads(chunk)
            step = data.get("step", "")
            if step in ("执行完成", "任务完成"):
                final_data = data.get("data", {})
            results.append({"step": step, "progress": data.get("progress", 0), "message": data.get("message", "")})
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "task_id": task_id,
        "status": "completed",
        "steps": results,
        "final": final_data,
    }


def _query_task(task_id: int) -> dict:
    """查询任务状态"""
    from app.db.database import SessionLocal
    from app.models.requirement_task import RequirementTask
    from app.models.task import Task
    from app.models.execution_record import ExecutionRecord

    db = SessionLocal()
    try:
        req_task = db.query(RequirementTask).filter(RequirementTask.id == task_id).first()
        if not req_task:
            return {"error": f"需求任务 {task_id} 不存在"}

        result = {
            "requirement_task": {
                "id": req_task.id,
                "requirement": req_task.requirement,
                "status": req_task.status.value if req_task.status else None,
                "task_type": req_task.task_type,
                "created_at": str(req_task.created_at) if req_task.created_at else None,
                "updated_at": str(req_task.updated_at) if req_task.updated_at else None,
            }
        }

        # 关联的Task
        if req_task.task_id:
            task = db.query(Task).filter(Task.id == req_task.task_id).first()
            if task:
                result["task"] = {
                    "id": task.id,
                    "name": task.task_name,
                    "status": task.status.value if task.status else None,
                    "task_type": task.task_type.value if task.task_type else None,
                }

                # 执行记录
                exec_records = db.query(ExecutionRecord).filter(
                    ExecutionRecord.task_id == task.id
                ).order_by(ExecutionRecord.created_at.desc()).limit(5).all()

                if exec_records:
                    result["executions"] = [{
                        "id": r.id,
                        "status": r.status.value if r.status else None,
                        "duration": r.duration,
                        "success_count": r.success_count,
                        "failed_count": r.failed_count,
                        "error_message": r.error_message,
                        "created_at": str(r.created_at) if r.created_at else None,
                    } for r in exec_records]

        # 脚本
        if req_task.generated_script:
            result["script"] = {
                "length": len(req_task.generated_script),
                "preview": req_task.generated_script[:500] if req_task.generated_script else None,
            }

        return result
    finally:
        db.close()


def _query_graph(keyword: str = "", node_types: str = "", limit: int = 30) -> dict:
    """查询知识图谱"""
    from app.services.graph_service import GraphService
    from app.db.neo4j_client import is_available, get_statistics

    if not is_available():
        return {"error": "Neo4j不可用", "available": False}

    result = {"available": True}

    # 统计
    try:
        stats = get_statistics()
        result["statistics"] = stats
    except Exception:
        pass

    # 搜索
    if keyword:
        try:
            nodes = GraphService.search_nodes(keyword, limit=limit)
            result["search"] = {
                "keyword": keyword,
                "results": nodes,
                "count": len(nodes),
            }
        except Exception as e:
            result["search_error"] = str(e)

    # 图谱数据
    try:
        types = node_types.split(",") if node_types else None
        data = GraphService.get_graph_data(node_types=types, limit=limit)
        result["graph_data"] = data
    except Exception as e:
        result["graph_data_error"] = str(e)

    return result


def _generate_script(requirement: str, additional_info: str = "", script_format: str = "playwright", execute: bool = False) -> dict:
    """生成测试脚本"""
    from app.services.requirement_flow_service import RequirementFlowService

    results = []
    task_id = None
    script_content = None
    final_data = None

    for chunk in RequirementFlowService.generate(
        requirement=requirement,
        execute=execute,
        additional_info=additional_info or None,
        script_format=script_format,
    ):
        try:
            data = json.loads(chunk)
            step = data.get("step", "")
            if "任务创建" in step and data.get("data", {}).get("task_id"):
                task_id = data["data"]["task_id"]
            if "脚本生成完成" in step and data.get("data", {}).get("script"):
                script_content = data["data"]["script"]
            if step in ("任务完成",):
                final_data = data.get("data", {})
            results.append({"step": step, "progress": data.get("progress", 0), "message": data.get("message", "")})
        except (json.JSONDecodeError, TypeError):
            continue

    return {
        "task_id": task_id,
        "script": script_content,
        "executed": execute,
        "steps": results,
        "final": final_data,
    }


# ==================== MCP Server 定义 ====================

def create_mcp_server() -> Server:
    """创建MCP Server实例（向后兼容不同版本的 mcp 包）"""
    # 兼容性保护：如果 mcp.Server 不存在预期的装饰器接口（list_tools / call_tool），
    # 则退化为一个 DummyServer，避免在应用启动时因 MCP API 不兼容导致整个服务启动失败。
    try:
        server = Server("test-automation-mcp")
    except Exception as e:
        log.warning(f"MCP Server 初始化失败，使用 DummyServer 退化启动: {e}")

        class DummyServer:
            def create_initialization_options(self):
                return {}

            async def run(self, read_stream, write_stream, init_options):
                # no-op implementation for compatibility
                return

        return DummyServer()

    # 如果 server 缺少预期的装饰器接口，退化为 DummyServer
    if not hasattr(server, "list_tools") or not hasattr(server, "call_tool"):
        log.warning("MCP Server 版本不支持 list_tools/call_tool 装饰器，使用 DummyServer 退化")

        class DummyServer:
            def create_initialization_options(self):
                return {}

            async def run(self, read_stream, write_stream, init_options):
                return

        return DummyServer()

    # 如果能正常创建 server，则按原逻辑注册工具
    from app.mcp.tools import ALL_TOOLS

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        # 新工具
        tools = []
        for name, desc, schema, _ in ALL_TOOLS:
            tools.append(Tool(name=name, description=desc, inputSchema=schema))

        # 旧工具（保留兼容）
        tools.extend([
            Tool(
                name="create_task",
                description="创建测试任务。输入需求描述，系统自动识别测试类型（WEB/API/ANDROID/PERFORMANCE），生成测试用例和脚本。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "requirement": {
                            "type": "string",
                            "description": "测试需求描述，如：测试登录功能、测试商品搜索接口",
                        },
                        "additional_info": {
                            "type": "string",
                            "description": "附加信息，如URL、swagger地址、APK路径等",
                        },
                        "script_format": {
                            "type": "string",
                            "enum": ["playwright", "midscene", "yaml"],
                            "description": "脚本格式，默认playwright",
                        },
                    },
                    "required": ["requirement"],
                },
            ),
            Tool(
                name="execute_task",
                description="执行已有的测试任务。根据任务类型自动选择执行器（Playwright/API/Appium/性能测试）。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "integer",
                            "description": "需求任务ID",
                        },
                    },
                    "required": ["task_id"],
                },
            ),
            Tool(
                name="query_task",
                description="查询任务状态和结果。返回需求任务信息、关联Task、执行记录、脚本内容等。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "integer",
                            "description": "需求任务ID",
                        },
                    },
                    "required": ["task_id"],
                },
            ),
            Tool(
                name="query_graph",
                description="查询知识图谱。搜索节点、获取图谱可视化数据、查看统计信息。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {
                            "type": "string",
                            "description": "搜索关键词",
                        },
                        "node_types": {
                            "type": "string",
                            "description": "节点类型过滤，逗号分隔，如：Page,Element,TestCase",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "返回数量限制，默认30",
                        },
                    },
                },
            ),
        ])
        return tools

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
        log.info(f"MCP工具调用 | tool={name}, args={json.dumps(arguments, ensure_ascii=False)[:200]}")

        try:
            # === 新工具路由 ===
            new_tool_map = {t[0]: t[3] for t in ALL_TOOLS}
            if name in new_tool_map:
                result = await new_tool_map[name](**arguments)
            # === 旧工具路由 ===
            elif name == "create_task":
                result = _create_task(
                    requirement=arguments["requirement"],
                    additional_info=arguments.get("additional_info", ""),
                    script_format=arguments.get("script_format", "playwright"),
                )
            elif name == "execute_task":
                result = _execute_task(task_id=arguments["task_id"])
            elif name == "query_task":
                result = _query_task(task_id=arguments["task_id"])
            elif name == "query_graph":
                result = _query_graph(
                    keyword=arguments.get("keyword", ""),
                    node_types=arguments.get("node_types", ""),
                    limit=arguments.get("limit", 30),
                )
            else:
                result = {"error": f"未知工具: {name}"}

            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, default=str))]

        except Exception as e:
            log.error(f"MCP工具执行失败 | tool={name}, error={e}", exc_info=True)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

    return server


# ==================== FastAPI 集成 ====================

def setup_mcp_routes(app):
    """将MCP SSE和Streamable HTTP路由注册到FastAPI应用"""
    from starlette.routing import Route
    from starlette.responses import Response as StarletteResponse

    mcp_server = create_mcp_server()

    # SSE 传输
    sse_transport = SseServerTransport("/mcp/messages")

    async def handle_sse(request):
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )

    async def handle_sse_messages(request):
        await sse_transport.handle_post_message(
            request.scope, request.receive, request._send
        )

    # Streamable HTTP 传输
    streamable_transport = StreamableHTTPServerTransport(mcp_session_id=None)

    async def handle_streamable_http(request):
        await streamable_transport.handle_request(
            request.scope, request.receive, request._send
        )

    # 直接挂载到app（绕过FastAPI的依赖注入，使用Starlette原生路由）
    app.routes.insert(0, Route("/mcp/sse", endpoint=handle_sse))
    app.routes.insert(0, Route("/mcp/messages", endpoint=handle_sse_messages, methods=["POST"]))
    app.routes.insert(0, Route("/mcp/", endpoint=handle_streamable_http, methods=["POST", "GET"]))

    log.info("MCP路由已注册 | SSE=/mcp/sse, Messages=/mcp/messages, StreamableHTTP=/mcp/")


# ==================== stdio 入口 ====================

def run_stdio():
    """stdio模式入口，供外部Agent通过标准输入输出调用"""
    from mcp.server.stdio import stdio_server

    async def _run():
        mcp_server = create_mcp_server()
        async with stdio_server() as (read_stream, write_stream):
            await mcp_server.run(
                read_stream, write_stream, mcp_server.create_initialization_options()
            )

    log.info("MCP Server (stdio模式) 启动")
    asyncio.run(_run())


if __name__ == "__main__":
    run_stdio()
