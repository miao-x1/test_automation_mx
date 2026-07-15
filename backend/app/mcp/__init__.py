"""
MCP - Model Context Protocol 适配层

将平台能力开放给外部AI客户端（Claude、Cursor、Cherry Studio 等）。

支持3种传输协议：
  - stdio:           独立进程模式
  - sse:             /mcp/sse (Server-Sent Events)
  - streamable-http:  /mcp/   (Streamable HTTP)

暴露9个工具：
  新增4个：
    1. analyze_page       — 页面分析
    2. generate_testcase  — 生成测试用例
    3. generate_script    — 生成测试脚本
    4. execute_test       — 执行测试

  保留5个旧工具：
    5. create_task        — 创建测试任务
    6. execute_task       — 执行测试任务
    7. query_task         — 查询任务状态
    8. query_graph        — 查询知识图谱
"""
from app.mcp.server import create_mcp_server, setup_mcp_routes, run_stdio

__all__ = ["create_mcp_server", "setup_mcp_routes", "run_stdio"]
