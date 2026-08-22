"""
诊断报告生成器

将 jstack 分析报告 + 日志分析报告 + 监控数据 合并为统一的诊断报告,
并生成结构化的问题定位结果, 供 PerformanceDiagnosticAgent 使用。

职责:
  1. 聚合多源诊断数据 (线程 dump + 日志 + 监控指标)
  2. 关联分析 (如: BLOCKED 线程 + 同时段错误日志 + CPU 飙升)
  3. 生成问题列表 (每个问题包含: 类型/严重度/位置/证据/建议)
  4. 生成摘要供 LLM 进一步分析
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.domains.performance.analyzer.jstack_parser import JStackReport, JStackParser
from app.domains.performance.analyzer.log_analyzer import LogReport, LogAnalyzer


@dataclass
class DiagnosticProblem:
    """单个诊断问题"""
    problem_type: str = ""        # deadlock / thread_block / cpu_hotspot / error_spike / slow_operation / resource_exhaustion
    severity: str = "low"         # critical / high / medium / low
    title: str = ""
    description: str = ""
    location: str = ""            # 代码位置 / 线程名 / 日志来源
    evidence: List[str] = field(default_factory=list)
    affected_threads: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    source: str = ""              # jstack / log / monitoring / correlation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem_type": self.problem_type,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "location": self.location,
            "evidence": self.evidence,
            "affected_threads": self.affected_threads,
            "recommendations": self.recommendations,
            "source": self.source,
        }


@dataclass
class DiagnosticReport:
    """完整诊断报告"""
    problems: List[DiagnosticProblem] = field(default_factory=list)
    jstack_summary: Dict[str, Any] = field(default_factory=dict)
    log_summary: Dict[str, Any] = field(default_factory=dict)
    monitoring_summary: Dict[str, Any] = field(default_factory=dict)
    correlations: List[Dict[str, str]] = field(default_factory=list)
    overall_severity: str = "low"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problems": [p.to_dict() for p in self.problems],
            "jstack_summary": self.jstack_summary,
            "log_summary": self.log_summary,
            "monitoring_summary": self.monitoring_summary,
            "correlations": self.correlations,
            "overall_severity": self.overall_severity,
        }

    def to_llm_prompt(self) -> str:
        """生成供 LLM 分析的 prompt 文本"""
        import json
        return json.dumps({
            "problems_found": len(self.problems),
            "overall_severity": self.overall_severity,
            "jstack_summary": self.jstack_summary,
            "log_summary": self.log_summary,
            "monitoring_summary": self.monitoring_summary,
            "detected_problems": [p.to_dict() for p in self.problems],
            "correlations": self.correlations,
        }, ensure_ascii=False, indent=2, default=str)


class DiagnosticReportBuilder:
    """诊断报告生成器

    聚合 jstack 分析、日志分析、监控数据, 生成统一诊断报告。
    """

    def build(
        self,
        jstack_dump: str = "",
        logs: List[Any] = None,
        monitoring_data: Dict[str, Any] = None,
    ) -> DiagnosticReport:
        """构建诊断报告

        Args:
            jstack_dump: jstack 命令输出文本 (可选)
            logs: 应用日志列表 (可选)
            monitoring_data: 监控指标 (TPS/RT/CPU/Memory 等) (可选)

        Returns:
            DiagnosticReport 诊断报告
        """
        report = DiagnosticReport()
        logs = logs or []
        monitoring_data = monitoring_data or {}

        # 1. JStack 分析
        jstack_report: Optional[JStackReport] = None
        if jstack_dump:
            parser = JStackParser()
            jstack_report = parser.parse(jstack_dump)
            report.jstack_summary = jstack_report.to_dict()
            self._extract_jstack_problems(jstack_report, report)

        # 2. 日志分析
        log_report: Optional[LogReport] = None
        if logs:
            analyzer = LogAnalyzer()
            log_report = analyzer.analyze(logs)
            report.log_summary = log_report.to_dict()
            self._extract_log_problems(log_report, report)

        # 3. 监控数据摘要
        if monitoring_data:
            report.monitoring_summary = self._summarize_monitoring(monitoring_data)
            self._extract_monitoring_problems(monitoring_data, report)

        # 4. 关联分析
        self._correlate(jstack_report, log_report, monitoring_data, report)

        # 5. 计算总体严重度
        report.overall_severity = self._compute_severity(report.problems)

        return report

    def _extract_jstack_problems(self, report: JStackReport, diag: DiagnosticReport) -> None:
        """从 jstack 报告提取问题"""

        # 死锁
        for deadlock in report.deadlocks:
            diag.problems.append(DiagnosticProblem(
                problem_type="deadlock",
                severity="critical",
                title=f"检测到死锁: {' ↔ '.join(deadlock.involved_threads)}",
                description=deadlock.description or "线程间形成锁等待环, 导致永久阻塞",
                location="; ".join(deadlock.involved_threads),
                evidence=[f"线程 {c['thread']} 等待锁 {c['waiting_on']}, 持有者为 {c['held_by']}"
                          for c in deadlock.cycle],
                affected_threads=deadlock.involved_threads,
                recommendations=[
                    "检查锁获取顺序, 确保所有线程按相同顺序获取锁",
                    "使用 tryLock 设置超时, 避免永久等待",
                    "考虑使用并发工具类 (如 ConcurrentHashSet) 替代手动锁",
                ],
                source="jstack",
            ))

        # 线程阻塞
        for blocked in report.blocked_threads:
            diag.problems.append(DiagnosticProblem(
                problem_type="thread_block",
                severity="high" if len(report.blocked_threads) > 3 else "medium",
                title=f"线程阻塞: {blocked.thread_name} 等待锁 {blocked.waiting_on_lock}",
                description=f"线程 {blocked.thread_name} 处于 BLOCKED 状态, "
                           f"等待 {blocked.lock_owner} 释放锁 {blocked.waiting_on_lock}",
                location=blocked.top_frame or blocked.thread_name,
                evidence=[
                    f"阻塞线程: {blocked.thread_name}",
                    f"等待锁: {blocked.waiting_on_lock}",
                    f"锁持有者: {blocked.lock_owner}",
                    f"栈顶帧: {blocked.top_frame}",
                ],
                affected_threads=[blocked.thread_name, blocked.lock_owner],
                recommendations=[
                    f"检查 {blocked.lock_owner} 为何长时间持有锁",
                    "考虑减小同步代码块范围",
                    "使用读写锁替代排他锁 (如果读多写少)",
                ],
                source="jstack",
            ))

        # CPU 热点
        for hotspot in report.cpu_hotspots[:5]:
            diag.problems.append(DiagnosticProblem(
                problem_type="cpu_hotspot",
                severity="high" if hotspot.runnable_thread_count > 5 else "medium",
                title=f"CPU 热点: {hotspot.runnable_thread_count} 个线程在 {hotspot.frame[:80]}",
                description=f"{hotspot.runnable_thread_count} 个 RUNNABLE 线程执行同一栈帧, "
                           f"可能存在 CPU 密集型操作",
                location=hotspot.frame,
                evidence=[
                    f"栈帧: {hotspot.frame}",
                    f"线程数: {hotspot.runnable_thread_count}",
                    f"线程列表: {', '.join(hotspot.thread_names[:5])}",
                ],
                affected_threads=hotspot.thread_names,
                recommendations=[
                    "检查该方法的算法复杂度, 考虑优化或缓存",
                    "考虑将 CPU 密集型任务异步化",
                    "检查是否存在死循环或频繁计算",
                ],
                source="jstack",
            ))

        # 大量 WAITING 线程
        for waiting_group in report.waiting_threads[:3]:
            if waiting_group["thread_count"] > 10:
                diag.problems.append(DiagnosticProblem(
                    problem_type="thread_contention",
                    severity="medium",
                    title=f"线程等待聚集: {waiting_group['thread_count']} 个线程在 {waiting_group['top_frame'][:80]}",
                    description=f"大量线程在同一位置等待, 可能存在资源竞争或连接池耗尽",
                    location=waiting_group["top_frame"],
                    evidence=[
                        f"等待位置: {waiting_group['top_frame']}",
                        f"线程数: {waiting_group['thread_count']}",
                    ],
                    affected_threads=waiting_group["sample_threads"],
                    recommendations=[
                        "检查连接池/线程池配置是否足够",
                        "考虑增加连接池大小或减少连接持有时间",
                    ],
                    source="jstack",
                ))

    def _extract_log_problems(self, report: LogReport, diag: DiagnosticReport) -> None:
        """从日志报告提取问题"""

        # 错误聚类
        for cluster in report.error_clusters[:5]:
            severity = "critical" if cluster.count > 50 else ("high" if cluster.count > 10 else "medium")
            diag.problems.append(DiagnosticProblem(
                problem_type="error_cluster",
                severity=severity,
                title=f"错误聚集: {cluster.error_type} × {cluster.count} 次",
                description=f"检测到 {cluster.error_type} 类型的错误在日志中出现 {cluster.count} 次",
                location=cluster.sample_stack[0] if cluster.sample_stack else cluster.message_pattern,
                evidence=[
                    f"错误类型: {cluster.error_type}",
                    f"出现次数: {cluster.count}",
                    f"首次: {cluster.first_occurrence}",
                    f"末次: {cluster.last_occurrence}",
                    f"消息模式: {cluster.message_pattern}",
                ],
                recommendations=[
                    f"检查 {cluster.error_type} 的根因",
                    "查看 sample_stack 中的完整堆栈定位代码",
                    "考虑增加异常处理或重试机制",
                ],
                source="log",
            ))

        # 错误突增
        if report.error_spike:
            spike = report.error_spike
            diag.problems.append(DiagnosticProblem(
                problem_type="error_spike",
                severity="high",
                title=f"错误突增: {spike['peak_time']} 出现 {spike['peak_error_count']} 个错误 "
                      f"(平均 {spike['avg_error_count']}, {spike['spike_ratio']}倍)",
                description=f"在 {spike['peak_time']} 时间窗口检测到错误数突增, "
                           f"是平均值的 {spike['spike_ratio']} 倍",
                location=spike["peak_time"],
                evidence=[
                    f"峰值时间: {spike['peak_time']}",
                    f"峰值错误数: {spike['peak_error_count']}",
                    f"平均错误数: {spike['avg_error_count']}",
                    f"突增倍数: {spike['spike_ratio']}x",
                ],
                recommendations=[
                    "检查该时间段是否有部署变更或流量突增",
                    "关联监控指标查看该时段 CPU/内存/RT 变化",
                ],
                source="log",
            ))

        # 慢操作
        for slow in report.slow_operations[:5]:
            severity = "high" if slow.duration_ms > 5000 else "medium"
            diag.problems.append(DiagnosticProblem(
                problem_type="slow_operation",
                severity=severity,
                title=f"慢操作: {slow.operation} 耗时 {slow.duration_ms}ms",
                description=f"检测到 {slow.operation} 操作耗时 {slow.duration_ms}ms",
                location=slow.operation,
                evidence=[
                    f"操作: {slow.operation}",
                    f"耗时: {slow.duration_ms}ms",
                    f"时间: {slow.timestamp}",
                    f"详情: {slow.detail[:200]}",
                ],
                recommendations=[
                    "检查该操作的数据库查询是否命中索引",
                    "考虑增加缓存或异步处理",
                    "检查是否有 N+1 查询问题",
                ],
                source="log",
            ))

    def _summarize_monitoring(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """汇总监控数据"""
        summary: Dict[str, Any] = {}

        # 提取关键指标
        avg_tps = data.get("avg_tps", 0)
        peak_tps = data.get("peak_tps", 0)
        avg_rt = data.get("avg_rt", 0)
        p95_rt = data.get("p95_rt", 0)
        p99_rt = data.get("p99_rt", 0)
        error_rate = data.get("error_rate", 0)
        cpu_peak = data.get("cpu_peak_pct")
        mem_peak = data.get("mem_peak_mb")

        summary["avg_tps"] = avg_tps
        summary["peak_tps"] = peak_tps
        summary["avg_rt_ms"] = avg_rt
        summary["p95_rt_ms"] = p95_rt
        summary["p99_rt_ms"] = p99_rt
        summary["error_rate_pct"] = error_rate
        summary["cpu_peak_pct"] = cpu_peak
        summary["mem_peak_mb"] = mem_peak

        # 指标列表 (如果提供)
        metrics = data.get("metrics", [])
        if metrics:
            tps_values = [m.get("tps", 0) for m in metrics]
            rt_values = [m.get("avg_rt", 0) for m in metrics]
            cpu_values = [m.get("cpu_percent") for m in metrics if m.get("cpu_percent") is not None]
            summary["tps_trend"] = "rising" if len(tps_values) > 1 and tps_values[-1] > tps_values[0] * 1.1 else \
                                   "falling" if len(tps_values) > 1 and tps_values[-1] < tps_values[0] * 0.9 else "stable"
            summary["rt_trend"] = "rising" if len(rt_values) > 1 and rt_values[-1] > rt_values[0] * 1.1 else \
                                  "falling" if len(rt_values) > 1 and rt_values[-1] < rt_values[0] * 0.9 else "stable"
            summary["metric_count"] = len(metrics)

        return summary

    def _extract_monitoring_problems(
        self, data: Dict[str, Any], diag: DiagnosticReport
    ) -> None:
        """从监控数据提取问题"""

        # 高错误率
        error_rate = data.get("error_rate", 0)
        if error_rate > 5:
            diag.problems.append(DiagnosticProblem(
                problem_type="high_error_rate",
                severity="critical" if error_rate > 20 else "high",
                title=f"高错误率: {error_rate}%",
                description=f"性能测试期间错误率 {error_rate}%, 超过 5% 阈值",
                location="monitoring",
                evidence=[f"错误率: {error_rate}%"],
                recommendations=[
                    "结合日志分析定位错误根因",
                    "检查后端服务是否有容量瓶颈",
                ],
                source="monitoring",
            ))

        # CPU 过高
        cpu_peak = data.get("cpu_peak_pct")
        if cpu_peak and cpu_peak > 80:
            diag.problems.append(DiagnosticProblem(
                problem_type="resource_exhaustion",
                severity="high",
                title=f"CPU 峰值过高: {cpu_peak}%",
                description=f"CPU 使用率峰值 {cpu_peak}%, 超过 80% 阈值",
                location="monitoring",
                evidence=[f"CPU 峰值: {cpu_peak}%"],
                recommendations=[
                    "结合 jstack 分析 CPU 热点线程",
                    "考虑水平扩容或优化 CPU 密集型操作",
                ],
                source="monitoring",
            ))

        # RT 过高
        p95_rt = data.get("p95_rt", 0)
        if p95_rt > 2000:
            diag.problems.append(DiagnosticProblem(
                problem_type="high_latency",
                severity="high",
                title=f"P95 响应时间过高: {p95_rt}ms",
                description=f"P95 响应时间 {p95_rt}ms, 超过 2000ms 阈值",
                location="monitoring",
                evidence=[f"P95 RT: {p95_rt}ms"],
                recommendations=[
                    "结合 jstack 分析是否有线程阻塞",
                    "结合日志分析是否有慢查询",
                ],
                source="monitoring",
            ))

    def _correlate(
        self,
        jstack: Optional[JStackReport],
        logs: Optional[LogReport],
        monitoring: Dict[str, Any],
        diag: DiagnosticReport,
    ) -> None:
        """关联分析 — 将不同来源的问题关联起来"""

        # 关联: 线程阻塞 + 高 RT
        if jstack and jstack.blocked_threads and monitoring.get("p95_rt", 0) > 1000:
            diag.correlations.append({
                "type": "block_latency",
                "description": f"检测到 {len(jstack.blocked_threads)} 个 BLOCKED 线程, "
                              f"同时 P95 RT 为 {monitoring.get('p95_rt')}ms, "
                              f"线程阻塞可能是高延迟的根因",
                "sources": "jstack + monitoring",
            })

        # 关联: CPU 热点 + 高 CPU
        if jstack and jstack.cpu_hotspots and monitoring.get("cpu_peak_pct", 0) > 80:
            top_hotspot = jstack.cpu_hotspots[0]
            diag.correlations.append({
                "type": "cpu_hotspot",
                "description": f"CPU 峰值 {monitoring.get('cpu_peak_pct')}%, "
                              f"同时 jstack 显示 {top_hotspot.runnable_thread_count} 个线程在 "
                              f"{top_hotspot.frame[:60]}, 可能是 CPU 瓶颈根因",
                "sources": "jstack + monitoring",
            })

        # 关联: 错误突增 + TPS 下降
        if logs and logs.error_spike and monitoring.get("metrics"):
            metrics = monitoring.get("metrics", [])
            if len(metrics) > 2:
                tps_trend = "falling" if metrics[-1].get("tps", 0) < metrics[0].get("tps", 0) * 0.8 else "stable"
                if tps_trend == "falling":
                    diag.correlations.append({
                        "type": "error_tps_drop",
                        "description": f"错误突增时段 {logs.error_spike['peak_time']} "
                                      f"TPS 下降, 错误导致吞吐量降低",
                        "sources": "log + monitoring",
                    })

        # 关联: 死锁 + 高错误率
        if jstack and jstack.deadlocks and monitoring.get("error_rate", 0) > 10:
            diag.correlations.append({
                "type": "deadlock_error",
                "description": f"检测到死锁 ({len(jstack.deadlocks)} 个), "
                              f"同时错误率 {monitoring.get('error_rate')}%, "
                              f"死锁导致请求超时和错误",
                "sources": "jstack + monitoring",
            })

        # 关联: 慢操作 + 高 RT
        if logs and logs.slow_operations and monitoring.get("p95_rt", 0) > 1000:
            slow_count = len(logs.slow_operations)
            diag.correlations.append({
                "type": "slow_op_latency",
                "description": f"检测到 {slow_count} 个慢操作, "
                              f"同时 P95 RT 为 {monitoring.get('p95_rt')}ms, "
                              f"慢操作是高延迟的直接原因",
                "sources": "log + monitoring",
            })

    def _compute_severity(self, problems: List[DiagnosticProblem]) -> str:
        """计算总体严重度"""
        if not problems:
            return "low"
        severity_order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        max_severity = max(
            severity_order.get(p.severity, 1) for p in problems
        )
        for sev, order in severity_order.items():
            if order == max_severity:
                return sev
        return "low"


# ================================================================
# 便捷函数
# ================================================================

def build_diagnostic_report(
    jstack_dump: str = "",
    logs: List[Any] = None,
    monitoring_data: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """构建诊断报告 (便捷函数)

    Args:
        jstack_dump: jstack 命令输出文本
        logs: 应用日志列表
        monitoring_data: 监控指标 (TPS/RT/CPU/Memory 等)

    Returns:
        诊断报告字典
    """
    builder = DiagnosticReportBuilder()
    report = builder.build(jstack_dump, logs, monitoring_data)
    return report.to_dict()
