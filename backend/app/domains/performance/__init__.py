"""
app.domains.performance — 性能测试域

包含四个 Agent + 执行引擎 + 诊断分析模块:
  1. PerformancePlanAgent       — 生成性能测试方案 (并发/持续时间/TPS目标)
  2. PerformanceScriptAgent     — 生成 Locust 脚本 / JMeter 配置 (支持 API/Web)
  3. PerformanceAnalysisAgent   — 分析实时指标 + 日志 (TPS/RT/CPU/Memory/日志)
  4. PerformanceDiagnosticAgent — 诊断 jstack/日志/监控数据, 定位线程阻塞/死锁/CPU热点
  5. PerformanceExecutor        — Locust 执行引擎, 实时采集指标
  6. analyzer                   — dump 解析模块 (jstack_parser + log_analyzer + diagnostic_report)

设计原则:
  - 不使用 RAG 分析实时性能数据
  - 使用实时指标 + 日志 + LLM 直接分析
  - Agent 从 ApplicationContainer 获取 LLM Gateway (禁止内部创建模型)
  - 支持 API 性能测试和 Web 性能测试
  - 诊断模块纯解析, 不依赖外部服务
"""
from app.domains.performance.agents import (
    PerformancePlanAgent,
    PerformanceScriptAgent,
    PerformanceAnalysisAgent,
    PerformanceDiagnosticAgent,
)
from app.domains.performance.executor import (
    PerformanceExecutor,
    get_performance_executor,
)

__all__ = [
    "PerformancePlanAgent",
    "PerformanceScriptAgent",
    "PerformanceAnalysisAgent",
    "PerformanceDiagnosticAgent",
    "PerformanceExecutor",
    "get_performance_executor",
]
