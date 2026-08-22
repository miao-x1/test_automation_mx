"""
日志分析器

分析应用日志, 提取:
  1. 错误/异常堆栈 (ERROR / Exception / StackTrace)
  2. 警告聚集 (WARN 频次)
  3. 慢操作日志 (Slow query / timeout / latency)
  4. 错误模式聚类 (按异常类型分组)
  5. 时间线异常 (错误突增检测)

设计原则:
  - 纯解析, 不依赖外部服务
  - 支持多种日志格式 (JSON / 纯文本 / log4j)
  - 结构化输出, 供 PerformanceDiagnosticAgent 使用
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class LogEntry:
    """单条日志条目"""
    timestamp: str = ""
    level: str = ""
    logger: str = ""
    message: str = ""
    raw: str = ""
    exception_type: str = ""
    stack_trace: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level,
            "logger": self.logger,
            "message": self.message[:500],
            "exception_type": self.exception_type,
            "stack_trace": self.stack_trace[:15],
        }


@dataclass
class ErrorCluster:
    """错误聚类"""
    error_type: str = ""           # 异常类型 (如 NullPointerException)
    message_pattern: str = ""      # 消息模式 (去具体值后的模板)
    count: int = 0
    first_occurrence: str = ""
    last_occurrence: str = ""
    sample_stack: List[str] = field(default_factory=list)
    sample_entries: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.error_type,
            "message_pattern": self.message_pattern,
            "count": self.count,
            "first_occurrence": self.first_occurrence,
            "last_occurrence": self.last_occurrence,
            "sample_stack": self.sample_stack[:10],
            "sample_entries": self.sample_entries[:3],
        }


@dataclass
class SlowOperation:
    """慢操作记录"""
    operation: str = ""
    duration_ms: float = 0.0
    timestamp: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "detail": self.detail[:300],
        }


@dataclass
class LogReport:
    """日志分析报告"""
    total_lines: int = 0
    level_distribution: Dict[str, int] = field(default_factory=dict)
    error_clusters: List[ErrorCluster] = field(default_factory=list)
    warn_clusters: List[ErrorCluster] = field(default_factory=list)
    slow_operations: List[SlowOperation] = field(default_factory=list)
    error_spike: Optional[Dict[str, Any]] = None  # 错误突增检测
    top_errors: List[Dict] = field(default_factory=list)
    top_warns: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_lines": self.total_lines,
            "level_distribution": self.level_distribution,
            "error_clusters": [e.to_dict() for e in self.error_clusters],
            "warn_clusters": [w.to_dict() for w in self.warn_clusters],
            "slow_operations": [s.to_dict() for s in self.slow_operations],
            "error_spike": self.error_spike,
            "top_errors": self.top_errors,
            "top_warns": self.top_warns,
        }

    @property
    def severity(self) -> str:
        """判定严重程度"""
        if any(e.count > 50 for e in self.error_clusters):
            return "critical"
        if self.error_clusters:
            return "high"
        if self.warn_clusters and sum(w.count for w in self.warn_clusters) > 20:
            return "medium"
        return "low"


class LogAnalyzer:
    """日志分析器"""

    # 日志级别正则
    _LEVEL_PATTERNS = [
        # JSON 格式: {"level": "ERROR", ...}
        re.compile(r'"(?:level|severity)"\s*:\s*"(\w+)"', re.IGNORECASE),
        # log4j 格式: 2024-01-01 12:00:00 ERROR [logger] message
        re.compile(r'\b(ERROR|WARN|WARNING|INFO|DEBUG|TRACE|FATAL|CRITICAL)\b', re.IGNORECASE),
    ]

    # 时间戳正则
    _TIMESTAMP_RE = re.compile(
        r'(\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'
    )

    # 异常类型正则
    _EXCEPTION_RE = re.compile(
        r'(?:Exception|Error|Throwable|RuntimeException)[:\s]'
        r'([\w.]+(?:Exception|Error|Throwable))?',
        re.IGNORECASE,
    )

    # 慢操作正则
    _SLOW_RE = re.compile(
        r'(?:slow|took|elapsed|duration|latency)[:\s=]+(\d+(?:\.\d+)?)\s*(ms|milliseconds|seconds|s)\b',
        re.IGNORECASE,
    )
    _SLOW_QUERY_RE = re.compile(r'(slow\s+query|slow\s+sql)[:\s]*(.+)', re.IGNORECASE)
    _TIMEOUT_RE = re.compile(r'(timeout|timed?\s*out|connection\s+refused|read\s+timeout)', re.IGNORECASE)

    # Java 栈帧
    _JAVA_FRAME_RE = re.compile(r'\s*at\s+([\w.$]+\([\w.$]+:\d+\))')

    # logger 名称
    _LOGGER_RE = re.compile(r'\[([\w.]+)\]')
    _JSON_LOGGER_RE = re.compile(r'"(?:logger|logger_name|source)"\s*:\s*"([\w.]+)"', re.IGNORECASE)

    # 通用消息模板化 (将数字/UUID/IP 替换为占位符)
    _NORMALIZE_RE = re.compile(
        r'\b\d{4,}\b'           # 4位以上数字
        r'|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'  # UUID
        r'|\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'  # IP
        , re.IGNORECASE
    )

    def analyze(self, logs: List[Any]) -> LogReport:
        """分析日志列表

        Args:
            logs: 日志列表, 每条可以是:
                  - dict (JSON 格式: {level, message, timestamp, ...})
                  - str (纯文本日志行)

        Returns:
            LogReport 分析报告
        """
        if not logs:
            return LogReport()

        report = LogReport()
        report.total_lines = len(logs)

        # 1. 解析所有日志条目
        entries: List[LogEntry] = []
        for log in logs:
            entry = self._parse_log_entry(log)
            entries.append(entry)

        # 2. 级别分布
        level_counter = Counter(e.level for e in entries if e.level)
        report.level_distribution = dict(level_counter)

        # 3. 错误聚类
        self._cluster_errors(entries, report)

        # 4. 警告聚类
        self._cluster_warns(entries, report)

        # 5. 慢操作检测
        self._detect_slow_operations(entries, report)

        # 6. 错误突增检测 (按时间窗口)
        self._detect_error_spike(entries, report)

        # 7. Top 错误/警告
        report.top_errors = self._get_top_messages(entries, "ERROR", 10)
        report.top_warns = self._get_top_messages(entries, "WARN", 10)

        return report

    def _parse_log_entry(self, log: Any) -> LogEntry:
        """解析单条日志为 LogEntry"""
        entry = LogEntry()

        if isinstance(log, dict):
            entry.level = str(log.get("level", log.get("severity", ""))).upper()
            entry.message = str(log.get("message", log.get("msg", log.get("text", ""))))
            entry.timestamp = str(log.get("timestamp", log.get("time", log.get("@timestamp", ""))))
            entry.logger = str(log.get("logger", log.get("logger_name", log.get("source", ""))))
            entry.raw = str(log.get("message", ""))

            # 检测异常
            if log.get("stack_trace") or log.get("exception"):
                stack = log.get("stack_trace", log.get("exception", ""))
                if isinstance(stack, str):
                    entry.stack_trace = [
                        line.strip() for line in stack.split("\n")
                        if line.strip()
                    ][:20]
                elif isinstance(stack, list):
                    entry.stack_trace = [str(s) for s in stack[:20]]

                # 提取异常类型
                exc_match = self._EXCEPTION_RE.search(entry.raw)
                if exc_match:
                    entry.exception_type = exc_match.group(1) or exc_match.group(0)

        elif isinstance(log, str):
            entry.raw = log
            entry.message = log.strip()

            # 提取级别
            for pattern in self._LEVEL_PATTERNS:
                m = pattern.search(log)
                if m:
                    entry.level = m.group(1).upper()
                    if entry.level == "WARNING":
                        entry.level = "WARN"
                    break

            # 提取时间戳
            ts_match = self._TIMESTAMP_RE.search(log)
            if ts_match:
                entry.timestamp = ts_match.group(1)

            # 提取 logger
            logger_match = self._LOGGER_RE.search(log)
            if logger_match:
                entry.logger = logger_match.group(1)

            # 检测异常和堆栈
            exc_match = self._EXCEPTION_RE.search(log)
            if exc_match:
                entry.exception_type = exc_match.group(1) or exc_match.group(0)

                # 提取 Java 栈帧
                frames = self._JAVA_FRAME_RE.findall(log)
                if frames:
                    entry.stack_trace = frames[:20]
        else:
            entry.raw = str(log)
            entry.message = str(log)

        # 如果没有检测到异常类型, 但有常见异常关键字
        if not entry.exception_type:
            for keyword in ("NullPointerException", "OutOfMemoryError", "StackOverflowError",
                            "ArrayIndexOutOfBoundsException", "ClassCastException",
                            "IllegalStateException", "SQLException", "ConnectException"):
                if keyword.lower() in entry.raw.lower():
                    entry.exception_type = keyword
                    break

        return entry

    def _cluster_errors(self, entries: List[LogEntry], report: LogReport) -> None:
        """按异常类型 + 消息模式 聚类 ERROR 日志"""
        clusters: Dict[str, ErrorCluster] = {}

        for entry in entries:
            if entry.level not in ("ERROR", "FATAL", "CRITICAL"):
                continue

            # 聚类 key: 异常类型 + 规范化消息前 100 字符
            exc_type = entry.exception_type or "GenericError"
            msg_pattern = self._normalize_message(entry.message[:100])
            cluster_key = f"{exc_type}::{msg_pattern}"

            if cluster_key not in clusters:
                clusters[cluster_key] = ErrorCluster(
                    error_type=exc_type,
                    message_pattern=msg_pattern,
                    first_occurrence=entry.timestamp,
                    last_occurrence=entry.timestamp,
                )

            cluster = clusters[cluster_key]
            cluster.count += 1
            if entry.timestamp:
                if not cluster.first_occurrence or entry.timestamp < cluster.first_occurrence:
                    cluster.first_occurrence = entry.timestamp
                if entry.timestamp > cluster.last_occurrence:
                    cluster.last_occurrence = entry.timestamp
            if not cluster.sample_stack and entry.stack_trace:
                cluster.sample_stack = entry.stack_trace
            if len(cluster.sample_entries) < 3:
                cluster.sample_entries.append(entry.to_dict())

        # 按数量排序
        report.error_clusters = sorted(clusters.values(), key=lambda x: x.count, reverse=True)

    def _cluster_warns(self, entries: List[LogEntry], report: LogReport) -> None:
        """聚类 WARN 日志"""
        clusters: Dict[str, ErrorCluster] = {}

        for entry in entries:
            if entry.level != "WARN":
                continue

            msg_pattern = self._normalize_message(entry.message[:100])
            cluster_key = msg_pattern

            if cluster_key not in clusters:
                clusters[cluster_key] = ErrorCluster(
                    error_type="WARN",
                    message_pattern=msg_pattern,
                    first_occurrence=entry.timestamp,
                    last_occurrence=entry.timestamp,
                )

            cluster = clusters[cluster_key]
            cluster.count += 1
            if entry.timestamp:
                if not cluster.first_occurrence or entry.timestamp < cluster.first_occurrence:
                    cluster.first_occurrence = entry.timestamp
                if entry.timestamp > cluster.last_occurrence:
                    cluster.last_occurrence = entry.timestamp
            if len(cluster.sample_entries) < 3:
                cluster.sample_entries.append(entry.to_dict())

        report.warn_clusters = sorted(clusters.values(), key=lambda x: x.count, reverse=True)

    def _detect_slow_operations(self, entries: List[LogEntry], report: LogReport) -> None:
        """检测慢操作"""
        for entry in entries:
            # 慢查询
            slow_match = self._SLOW_RE.search(entry.raw)
            if slow_match:
                duration = float(slow_match.group(1))
                unit = slow_match.group(2).lower()
                if "s" in unit and "ms" not in unit:
                    duration *= 1000  # 转为毫秒
                report.slow_operations.append(SlowOperation(
                    operation=self._extract_operation(entry),
                    duration_ms=duration,
                    timestamp=entry.timestamp,
                    detail=entry.message[:300],
                ))
                continue

            # 超时
            if self._TIMEOUT_RE.search(entry.raw):
                report.slow_operations.append(SlowOperation(
                    operation="timeout",
                    duration_ms=0,
                    timestamp=entry.timestamp,
                    detail=entry.message[:300],
                ))
                continue

            # 慢 SQL
            slow_sql_match = self._SLOW_QUERY_RE.search(entry.raw)
            if slow_sql_match:
                report.slow_operations.append(SlowOperation(
                    operation="slow_query",
                    duration_ms=0,
                    timestamp=entry.timestamp,
                    detail=slow_sql_match.group(2)[:300],
                ))

        # 按 duration 降序
        report.slow_operations.sort(key=lambda x: x.duration_ms, reverse=True)
        # 限制 50 条
        report.slow_operations = report.slow_operations[:50]

    def _detect_error_spike(self, entries: List[LogEntry], report: LogReport) -> None:
        """检测错误突增 (简单时间窗口分析)"""
        error_entries = [e for e in entries if e.level in ("ERROR", "FATAL", "CRITICAL") and e.timestamp]

        if len(error_entries) < 3:
            return

        # 按时间戳排序
        sorted_errors = sorted(error_entries, key=lambda x: x.timestamp)

        # 简化: 将时间戳按分钟分组, 找出错误数最多的窗口
        time_buckets: Dict[str, int] = defaultdict(int)
        for e in sorted_errors:
            # 截取到分钟
            bucket = e.timestamp[:16] if len(e.timestamp) >= 16 else e.timestamp
            time_buckets[bucket] += 1

        if not time_buckets:
            return

        max_bucket = max(time_buckets, key=time_buckets.get)
        max_count = time_buckets[max_bucket]
        avg_count = sum(time_buckets.values()) / len(time_buckets)

        # 突增条件:
        #   1. 最大窗口错误数 >= 3 且 是平均值的 3 倍以上 (多窗口场景)
        #   2. 或仅有一个窗口但错误数 >= 5 (集中爆发场景)
        is_spike = (
            (max_count >= 3 and max_count > avg_count * 3)
            or (len(time_buckets) == 1 and max_count >= 5)
        )

        if is_spike:
            report.error_spike = {
                "peak_time": max_bucket,
                "peak_error_count": max_count,
                "avg_error_count": round(avg_count, 1),
                "spike_ratio": round(max_count / avg_count, 1) if avg_count > 0 else 0,
            }

    def _get_top_messages(
        self, entries: List[LogEntry], level: str, top_n: int
    ) -> List[Dict]:
        """获取指定级别的 Top N 消息"""
        msg_counter: Dict[str, int] = defaultdict(int)

        for entry in entries:
            if entry.level != level:
                continue
            # 截取前 200 字符作为消息标识
            msg_key = self._normalize_message(entry.message[:200])
            msg_counter[msg_key] += 1

        return [
            {"message": msg, "count": count}
            for msg, count in sorted(msg_counter.items(), key=lambda x: x[1], reverse=True)[:top_n]
        ]

    def _normalize_message(self, msg: str) -> str:
        """规范化消息 (替换具体值为占位符, 用于聚类)"""
        return self._NORMALIZE_RE.sub('*', msg).strip()

    def _extract_operation(self, entry: LogEntry) -> str:
        """从日志中提取操作名称"""
        # 尝试从 logger 或消息中提取
        if entry.logger:
            return entry.logger.split(".")[-1]

        # 从消息中提取 HTTP 方法 + URL
        http_match = re.search(r'(GET|POST|PUT|DELETE|PATCH)\s+(\S+)', entry.raw)
        if http_match:
            return f"{http_match.group(1)} {http_match.group(2)}"

        return "unknown"


# ================================================================
# 便捷函数
# ================================================================

def analyze_logs(logs: List[Any]) -> Dict[str, Any]:
    """分析日志列表并返回字典报告"""
    analyzer = LogAnalyzer()
    report = analyzer.analyze(logs)
    return report.to_dict()


def extract_errors(logs: List[Any]) -> List[Dict]:
    """提取所有 ERROR 级别日志"""
    analyzer = LogAnalyzer()
    entries = [analyzer._parse_log_entry(log) for log in logs]
    return [e.to_dict() for e in entries if e.level in ("ERROR", "FATAL", "CRITICAL")]


def find_slow_operations(logs: List[Any]) -> List[Dict]:
    """查找慢操作"""
    analyzer = LogAnalyzer()
    report = analyzer.analyze(logs)
    return [s.to_dict() for s in report.slow_operations]
