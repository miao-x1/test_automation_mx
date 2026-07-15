"""
Execution Engine - 执行引擎模块

核心组件：
- LegacyExecutionRunner: Playwright 脚本执行器（旧版）
- ExecutionQueryService: 执行记录查询服务
- ExecutionContext: 执行上下文
- HttpRunner: HTTP请求执行器
- CaseRunner: 用例执行器
- AssertionEngine: 断言引擎
- ResultWriter: 结果写入器
- ReportGenerator: 报告生成器
- ExecutionQueue: 执行队列

兼容导出：
- ExecutionService = LegacyExecutionRunner（旧引用兼容）
"""
from app.services.execution.legacy_runner import LegacyExecutionRunner as ExecutionService
from app.services.execution.query_service import ExecutionQueryService

__all__ = ["ExecutionService", "LegacyExecutionRunner", "ExecutionQueryService"]
