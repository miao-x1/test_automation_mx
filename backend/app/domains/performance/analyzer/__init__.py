"""
app.domains.performance.analyzer — 性能诊断分析模块

包含三个核心组件:
  1. jstack_parser    — JStack Dump 解析器 (死锁/阻塞/CPU热点检测)
  2. log_analyzer     — 日志分析器 (错误聚类/慢操作/错误突增检测)
  3. diagnostic_report — 诊断报告生成器 (多源关联分析 + 问题定位)

设计原则:
  - 纯解析, 不依赖外部服务
  - 结构化输出, 供 PerformanceDiagnosticAgent 使用
  - 支持 jstack + 日志 + 监控数据 三源关联分析
"""
from app.domains.performance.analyzer.jstack_parser import (
    JStackParser,
    JStackReport,
    ThreadInfo,
    ThreadState,
    DeadlockInfo,
    BlockingInfo,
    CPUHotspot,
    parse_jstack,
    detect_deadlock,
    find_blocked_threads,
    find_cpu_hotspots,
)
from app.domains.performance.analyzer.log_analyzer import (
    LogAnalyzer,
    LogReport,
    LogEntry,
    ErrorCluster,
    SlowOperation,
    analyze_logs,
    extract_errors,
    find_slow_operations,
)
from app.domains.performance.analyzer.diagnostic_report import (
    DiagnosticReportBuilder,
    DiagnosticReport,
    DiagnosticProblem,
    build_diagnostic_report,
)

__all__ = [
    # JStack
    "JStackParser",
    "JStackReport",
    "ThreadInfo",
    "ThreadState",
    "DeadlockInfo",
    "BlockingInfo",
    "CPUHotspot",
    "parse_jstack",
    "detect_deadlock",
    "find_blocked_threads",
    "find_cpu_hotspots",
    # Log
    "LogAnalyzer",
    "LogReport",
    "LogEntry",
    "ErrorCluster",
    "SlowOperation",
    "analyze_logs",
    "extract_errors",
    "find_slow_operations",
    # Diagnostic
    "DiagnosticReportBuilder",
    "DiagnosticReport",
    "DiagnosticProblem",
    "build_diagnostic_report",
]
