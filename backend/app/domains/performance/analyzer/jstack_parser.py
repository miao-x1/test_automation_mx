"""
JStack Dump 解析器

解析 Java 线程转储 (jstack 输出), 检测:
  1. 死锁 (deadlock) — 通过 "Found one Java-level deadlock" 或锁等待环检测
  2. 线程阻塞 (blocking) — BLOCKED 状态线程 + 锁等待链
  3. CPU 热点 (CPU hotspot) — RUNNABLE 线程的栈帧频次统计
  4. 线程状态分布统计

设计原则:
  - 纯解析, 不依赖外部服务
  - 结构化输出, 供 PerformanceDiagnosticAgent 使用
  - 兼容 JDK 8-21 的 jstack 输出格式
"""
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class ThreadState(str, Enum):
    """Java 线程状态"""
    NEW = "NEW"
    RUNNABLE = "RUNNABLE"
    BLOCKED = "BLOCKED"
    WAITING = "WAITING"
    TIMED_WAITING = "TIMED_WAITING"
    TERMINATED = "TERMINATED"
    UNKNOWN = "UNKNOWN"


@dataclass
class ThreadInfo:
    """单个线程信息"""
    name: str = ""
    tid: str = ""
    nid: str = ""  # native id (十六进制)
    daemon: bool = False
    prio: int = 0
    state: ThreadState = ThreadState.UNKNOWN
    stack: List[str] = field(default_factory=list)  # 栈帧列表
    locked_ownables: List[str] = field(default_factory=list)
    waiting_on: str = ""        # 等待的锁
    locked: str = ""             # 持有的锁
    parking_to_wait: str = ""    # parking 等待

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nid": self.nid,
            "state": self.state.value,
            "daemon": self.daemon,
            "stack_depth": len(self.stack),
            "top_frame": self.stack[0] if self.stack else "",
            "stack": self.stack[:20],  # 最多保留 20 帧
            "waiting_on": self.waiting_on,
            "locked": self.locked,
        }


@dataclass
class DeadlockInfo:
    """死锁信息"""
    involved_threads: List[str] = field(default_factory=list)
    description: str = ""
    cycle: List[Dict[str, str]] = field(default_factory=list)  # [{thread, waiting_on, held_by}]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "involved_threads": self.involved_threads,
            "description": self.description,
            "cycle": self.cycle,
        }


@dataclass
class BlockingInfo:
    """线程阻塞信息"""
    thread_name: str = ""
    state: str = ""
    waiting_on_lock: str = ""
    lock_owner: str = ""           # 持有该锁的线程名
    blocked_duration_hint: str = "" # jstack 可能给出等待时间提示
    top_frame: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_name": self.thread_name,
            "state": self.state,
            "waiting_on_lock": self.waiting_on_lock,
            "lock_owner": self.lock_owner,
            "blocked_duration_hint": self.blocked_duration_hint,
            "top_frame": self.top_frame,
        }


@dataclass
class CPUHotspot:
    """CPU 热点栈帧"""
    frame: str = ""
    runnable_thread_count: int = 0  # 多少个 RUNNABLE 线程在此帧
    thread_names: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame": self.frame,
            "runnable_thread_count": self.runnable_thread_count,
            "thread_names": self.thread_names[:10],
        }


@dataclass
class JStackReport:
    """完整的 jstack 分析报告"""
    total_threads: int = 0
    state_distribution: Dict[str, int] = field(default_factory=dict)
    deadlocks: List[DeadlockInfo] = field(default_factory=list)
    blocked_threads: List[BlockingInfo] = field(default_factory=list)
    waiting_threads: List[Dict] = field(default_factory=list)  # WAITING/TIMED_WAITING 摘要
    cpu_hotspots: List[CPUHotspot] = field(default_factory=list)
    daemon_count: int = 0
    raw_thread_count: int = 0
    has_deadlock_section: bool = False
    parse_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_threads": self.total_threads,
            "state_distribution": self.state_distribution,
            "daemon_count": self.daemon_count,
            "deadlocks": [d.to_dict() for d in self.deadlocks],
            "blocked_threads": [b.to_dict() for b in self.blocked_threads],
            "waiting_summary": self.waiting_threads,
            "cpu_hotspots": [h.to_dict() for h in self.cpu_hotspots],
            "has_deadlock_section": self.has_deadlock_section,
            "parse_errors": self.parse_errors,
        }

    @property
    def severity(self) -> str:
        """判定严重程度"""
        if self.deadlocks:
            return "critical"
        if len(self.blocked_threads) > 5:
            return "high"
        if self.blocked_threads:
            return "medium"
        return "low"


class JStackParser:
    """JStack Dump 解析器"""

    # 正则表达式模式
    _THREAD_HEADER_RE = re.compile(
        r'^"(.+?)"\s*(?:#(\d+)\s+)?daemon\s+prio=(\d+)\s+os_prio=(\d+)\s+tid=(\S+)\s+nid=(\S+)',
        re.MULTILINE,
    )
    _THREAD_HEADER_NON_DAEMON_RE = re.compile(
        r'^"(.+?)"\s*(?:#(\d+)\s+)?prio=(\d+)\s+os_prio=(\d+)\s+tid=(\S+)\s+nid=(\S+)',
        re.MULTILINE,
    )
    _STATE_RE = re.compile(r'\s*java\.lang\.Thread\.State:\s*(\w+)')
    _WAITING_ON_RE = re.compile(r'- waiting on <(0x[0-9a-fA-F]+)>\s*\(a\s+(.+?)\)')
    _LOCKED_RE = re.compile(r'- locked <(0x[0-9a-fA-F]+)>\s*\(a\s+(.+?)\)')
    _BLOCKED_ON_RE = re.compile(r'- waiting to lock <(0x[0-9a-fA-F]+)>\s*\(a\s+(.+?)\)')
    _PARKING_RE = re.compile(r'- parking to wait for\s+<(0x[0-9a-fA-F]+)>')
    _DEADLOCK_RE = re.compile(r'Found one Java-level deadlock:', re.IGNORECASE)
    _DEADLOCK_DETAIL_RE = re.compile(r'"(.+?)":', re.MULTILINE)

    def parse(self, dump_text: str) -> JStackReport:
        """解析 jstack dump 文本

        Args:
            dump_text: jstack 命令输出的完整文本

        Returns:
            JStackReport 分析报告
        """
        if not dump_text or not dump_text.strip():
            return JStackReport(parse_errors=["Empty dump text"])

        report = JStackReport()

        # 1. 检测死锁节
        self._parse_deadlock_section(dump_text, report)

        # 2. 解析所有线程
        threads = self._parse_threads(dump_text)
        report.raw_thread_count = len(threads)
        report.total_threads = len(threads)
        report.daemon_count = sum(1 for t in threads if t.daemon)

        # 3. 状态分布
        state_counter = Counter(t.state.value for t in threads)
        report.state_distribution = dict(state_counter)

        # 4. 构建锁持有映射 (lock_id → thread_name)
        lock_owner_map = self._build_lock_owner_map(threads)

        # 5. 检测 BLOCKED 线程
        self._detect_blocked_threads(threads, lock_owner_map, report)

        # 6. WAITING/TIMED_WAITING 摘要
        self._summarize_waiting_threads(threads, report)

        # 7. CPU 热点分析 (RUNNABLE 线程栈帧频次)
        self._detect_cpu_hotspots(threads, report)

        return report

    def _parse_threads(self, dump_text: str) -> List[ThreadInfo]:
        """解析所有线程块"""
        threads: List[ThreadInfo] = []

        # 用 "线程头" 分割
        # 匹配以 " 开头的行 (线程名引号开始)
        lines = dump_text.split("\n")
        current: Optional[ThreadInfo] = None
        in_stack = False

        for line in lines:
            line_stripped = line.strip()

            # 检测线程头
            header_match = self._match_thread_header(line)
            if header_match:
                # 保存前一个线程
                if current:
                    threads.append(current)
                current = header_match
                in_stack = False
                continue

            if current is None:
                continue

            # 状态行
            state_match = self._STATE_RE.match(line_stripped)
            if state_match:
                try:
                    current.state = ThreadState(state_match.group(1))
                except ValueError:
                    current.state = ThreadState.UNKNOWN
                continue

            # 锁等待
            if "waiting to lock" in line_stripped:
                m = self._BLOCKED_ON_RE.search(line_stripped)
                if m:
                    current.waiting_on = f"<{m.group(1)}> ({m.group(2)})"
                continue

            if "waiting on" in line_stripped and "waiting to lock" not in line_stripped:
                m = self._WAITING_ON_RE.search(line_stripped)
                if m:
                    current.waiting_on = f"<{m.group(1)}> ({m.group(2)})"
                continue

            # 持有锁
            if "locked" in line_stripped:
                m = self._LOCKED_RE.search(line_stripped)
                if m:
                    current.locked = f"<{m.group(1)}> ({m.group(2)})"
                continue

            # parking
            if "parking to wait" in line_stripped:
                m = self._PARKING_RE.search(line_stripped)
                if m:
                    current.parking_to_wait = m.group(1)
                continue

            # 栈帧 (以 "at " 开头)
            if line_stripped.startswith("at "):
                current.stack.append(line_stripped[3:].strip())
                in_stack = True
                continue

            # 空行或分隔符 → 可能是线程块结束
            if in_stack and (not line_stripped or line_stripped == "=" * 80):
                in_stack = False

        # 保存最后一个线程
        if current:
            threads.append(current)

        return threads

    def _match_thread_header(self, line: str) -> Optional[ThreadInfo]:
        """匹配线程头行, 返回 ThreadInfo"""
        # 先尝试 daemon 模式
        m = self._THREAD_HEADER_RE.match(line)
        if m:
            return ThreadInfo(
                name=m.group(1),
                tid=m.group(5),
                nid=m.group(6),
                daemon=True,
                prio=int(m.group(3)) if m.group(3) else 0,
            )

        # 非 daemon 模式
        m = self._THREAD_HEADER_NON_DAEMON_RE.match(line)
        if m:
            return ThreadInfo(
                name=m.group(1),
                tid=m.group(5),
                nid=m.group(6),
                daemon=False,
                prio=int(m.group(3)) if m.group(3) else 0,
            )

        return None

    def _build_lock_owner_map(self, threads: List[ThreadInfo]) -> Dict[str, str]:
        """构建锁 ID → 持有线程名 的映射"""
        lock_map: Dict[str, str] = {}
        for t in threads:
            if t.locked:
                # 提取 lock id
                m = re.search(r'<(0x[0-9a-fA-F]+)>', t.locked)
                if m:
                    lock_map[m.group(1)] = t.name
        return lock_map

    def _detect_blocked_threads(
        self,
        threads: List[ThreadInfo],
        lock_owner_map: Dict[str, str],
        report: JStackReport,
    ) -> None:
        """检测 BLOCKED 线程及其阻塞链"""
        for t in threads:
            if t.state != ThreadState.BLOCKED:
                continue

            # 提取等待的 lock id
            lock_id = ""
            m = re.search(r'<(0x[0-9a-fA-F]+)>', t.waiting_on) if t.waiting_on else None
            if m:
                lock_id = m.group(1)

            owner = lock_owner_map.get(lock_id, "unknown")
            report.blocked_threads.append(BlockingInfo(
                thread_name=t.name,
                state=t.state.value,
                waiting_on_lock=t.waiting_on,
                lock_owner=owner,
                top_frame=t.stack[0] if t.stack else "",
            ))

    def _summarize_waiting_threads(
        self, threads: List[ThreadInfo], report: JStackReport
    ) -> None:
        """汇总 WAITING / TIMED_WAITING 线程"""
        waiting_groups: Dict[str, List[str]] = defaultdict(list)

        for t in threads:
            if t.state in (ThreadState.WAITING, ThreadState.TIMED_WAITING):
                # 按 top_frame 分类
                top = t.stack[0] if t.stack else "no_stack"
                waiting_groups[top].append(t.name)

        for top_frame, names in waiting_groups.items():
            if len(names) >= 2:  # 只报告有聚集的
                report.waiting_threads.append({
                    "top_frame": top_frame,
                    "thread_count": len(names),
                    "sample_threads": names[:5],
                })

    def _detect_cpu_hotspots(
        self, threads: List[ThreadInfo], report: JStackReport
    ) -> None:
        """检测 CPU 热点 (RUNNABLE 线程的栈帧频次)"""
        frame_counter: Dict[str, List[str]] = defaultdict(list)

        for t in threads:
            if t.state != ThreadState.RUNNABLE:
                continue
            # 统计每个栈帧出现在多少个 RUNNABLE 线程中
            seen_frames: Set[str] = set()
            for frame in t.stack:
                if frame not in seen_frames:
                    frame_counter[frame].append(t.name)
                    seen_frames.add(frame)

        # 按出现次数排序, 取 Top 10
        sorted_frames = sorted(
            frame_counter.items(),
            key=lambda x: len(x[1]),
            reverse=True,
        )[:10]

        for frame, names in sorted_frames:
            if len(names) >= 2:  # 至少 2 个线程共享
                report.cpu_hotspots.append(CPUHotspot(
                    frame=frame,
                    runnable_thread_count=len(names),
                    thread_names=names,
                ))

    def _parse_deadlock_section(self, dump_text: str, report: JStackReport) -> None:
        """解析死锁节 (jstack 自动检测到的死锁)"""
        if not self._DEADLOCK_RE.search(dump_text):
            return

        report.has_deadlock_section = True

        # 截取死_lock 节
        deadlock_start = dump_text.find("Found one Java-level deadlock")
        if deadlock_start == -1:
            return

        # 死锁节到文件末尾或下一个空行分隔
        deadlock_section = dump_text[deadlock_start:]

        # 解析死锁描述
        lines = deadlock_section.split("\n")
        current_deadlock = DeadlockInfo()
        description_lines: List[str] = []
        in_cycle = False

        for line in lines:
            line = line.strip()
            if not line:
                if current_deadlock.involved_threads:
                    current_deadlock.description = " ".join(description_lines)
                    report.deadlocks.append(current_deadlock)
                    current_deadlock = DeadlockInfo()
                    description_lines = []
                    in_cycle = False
                continue

            if line.startswith("Found"):
                description_lines.append(line)
                continue

            # 匹配线程名
            thread_match = re.match(r'^"(.+?)":', line)
            if thread_match:
                thread_name = thread_match.group(1)
                current_deadlock.involved_threads.append(thread_name)

                # 解析等待关系
                if "waiting to lock" in line:
                    lock_m = re.search(r'<(0x[0-9a-fA-F]+)>', line)
                    held_m = re.search(r'held by\s+"(.+?)"', line)
                    current_deadlock.cycle.append({
                        "thread": thread_name,
                        "waiting_on": lock_m.group(1) if lock_m else "",
                        "held_by": held_m.group(1) if held_m else "",
                    })
                in_cycle = True
                continue

            if in_cycle:
                description_lines.append(line)

        # 保存最后一个
        if current_deadlock.involved_threads:
            current_deadlock.description = " ".join(description_lines)
            report.deadlocks.append(current_deadlock)


# ================================================================
# 便捷函数
# ================================================================

def parse_jstack(dump_text: str) -> Dict[str, Any]:
    """解析 jstack dump 并返回字典报告

    Args:
        dump_text: jstack 命令输出文本

    Returns:
        分析报告字典
    """
    parser = JStackParser()
    report = parser.parse(dump_text)
    return report.to_dict()


def detect_deadlock(dump_text: str) -> Optional[Dict[str, Any]]:
    """快速检测死锁

    Returns:
        死锁信息字典, 无死锁返回 None
    """
    parser = JStackParser()
    report = parser.parse(dump_text)
    if report.deadlocks:
        return report.deadlocks[0].to_dict()
    return None


def find_blocked_threads(dump_text: str) -> List[Dict[str, Any]]:
    """查找所有 BLOCKED 线程

    Returns:
        阻塞线程列表
    """
    parser = JStackParser()
    report = parser.parse(dump_text)
    return [b.to_dict() for b in report.blocked_threads]


def find_cpu_hotspots(dump_text: str, top_n: int = 10) -> List[Dict[str, Any]]:
    """查找 CPU 热点栈帧

    Returns:
        热点列表 (按出现次数降序)
    """
    parser = JStackParser()
    report = parser.parse(dump_text)
    return [h.to_dict() for h in report.cpu_hotspots[:top_n]]
