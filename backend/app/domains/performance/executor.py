"""
性能测试执行引擎

功能:
  1. 将 PerformanceScriptAgent 生成的 Locust 脚本写入临时文件
  2. 使用 Locust Python API 运行 headless 性能测试
  3. 实时采集 TPS / RT / 错误数 (从 Locust 事件回调)
  4. 实时采集 CPU / Memory (psutil)
  5. 指标写入数据库 + 推送至 asyncio.Queue 供 SSE 消费
  6. 支持 API 性能测试和 Web 性能测试
  7. 支持停止/取消正在运行的测试

设计约束:
  - 不使用 RAG 分析实时性能数据
  - 实时指标 + LLM 分析 (由 PerformanceAnalysisAgent 负责)
  - 本引擎仅负责执行和指标采集
"""
import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ================================================================
# Locust runner 脚本模板 (独立子进程执行)
# ================================================================

_RUNNER_SCRIPT = '''#!/usr/bin/env python
"""Locust runner wrapper — 输出 JSON 格式的实时统计到 stdout"""
import sys, os, json, time, importlib.util, signal

def _load_user_class(script_path):
    """从脚本文件动态加载 Locust User 类"""
    spec = importlib.util.spec_from_file_location("locustfile", script_path)
    module = importlib.util.module_from_spec(spec)
    # 注入 locust 到模块全局命名空间
    spec.loader.exec_module(module)
    from locust import User
    candidates = []
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if (isinstance(attr, type) and issubclass(attr, User)
                and attr is not User and attr.__module__ == module.__name__):
            candidates.append(attr)
    if not candidates:
        # 退一步: 选取所有 User 子类
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and issubclass(attr, User)
                    and attr is not User):
                candidates.append(attr)
    if not candidates:
        print(json.dumps({"type": "error", "message": "No Locust User class found"}), flush=True)
        sys.exit(1)
    return candidates[0]

def run_test(script_path, host, concurrency, spawn_rate, duration):
    from locust import events
    from locust.env import Environment
    import gevent

    user_class = _load_user_class(script_path)
    env = Environment(user_classes=[user_class], events=events)
    env.create_local_runner()

    stats = {
        "requests": 0, "failures": 0,
        "total_rt": 0.0, "min_rt": float("inf"), "max_rt": 0.0,
        "rt_list": [],
    }
    lock = threading.Lock()

    @events.request.add_listener
    def _on_request(request_type, name, response_time, response_length,
                    response, context, exception, **kwargs):
        with lock:
            stats["requests"] += 1
            rt = response_time or 0
            stats["total_rt"] += rt
            if rt > 0:
                stats["rt_list"].append(rt)
                if rt < stats["min_rt"]:
                    stats["min_rt"] = rt
                if rt > stats["max_rt"]:
                    stats["max_rt"] = rt
            if exception:
                stats["failures"] += 1

    start_time = time.time()
    env.runner.start(user_count=concurrency, spawn_rate=spawn_rate)

    stopped = {"flag": False}

    def _emit_stats():
        while not stopped["flag"]:
            gevent.sleep(1)
            elapsed = time.time() - start_time
            with lock:
                reqs = stats["requests"]
                fails = stats["failures"]
                total_rt = stats["total_rt"]
                rts = sorted(stats["rt_list"])
            rps = reqs / elapsed if elapsed > 0 else 0
            avg_rt = total_rt / reqs if reqs > 0 else 0
            n = len(rts)
            p50 = rts[int(n * 0.5)] if n else 0
            p90 = rts[int(n * 0.9)] if n else 0
            p95 = rts[int(n * 0.95)] if n else 0
            p99 = rts[int(n * 0.99)] if n else 0
            out = {
                "type": "stats",
                "elapsed": round(elapsed, 1),
                "timestamp": time.time(),
                "requests": reqs,
                "failures": fails,
                "rps": round(rps, 2),
                "avg_rt": round(avg_rt, 2),
                "min_rt": round(stats["min_rt"], 2) if stats["min_rt"] != float("inf") else 0,
                "max_rt": round(stats["max_rt"], 2),
                "p50_rt": round(p50, 2),
                "p90_rt": round(p90, 2),
                "p95_rt": round(p95, 2),
                "p99_rt": round(p99, 2),
                "concurrent_users": env.runner.user_count if env.runner else 0,
            }
            print(json.dumps(out), flush=True)
            if elapsed >= duration:
                break

    gevent.spawn(_emit_stats)

    # 定时退出
    def _quit():
        gevent.sleep(duration)
        if env.runner:
            env.runner.quit()
    gevent.spawn(_quit)

    # 优雅退出
    def _sigterm(sig, frame):
        stopped["flag"] = True
        if env.runner:
            env.runner.quit()
    signal.signal(signal.SIGTERM, _sigterm)

    env.runner.greenlet.join()

    # 最终统计
    elapsed = time.time() - start_time
    with lock:
        reqs = stats["requests"]
        fails = stats["failures"]
        total_rt = stats["total_rt"]
        rts = sorted(stats["rt_list"])
    rps = reqs / elapsed if elapsed > 0 else 0
    avg_rt = total_rt / reqs if reqs > 0 else 0
    n = len(rts)
    p50 = rts[int(n * 0.5)] if n else 0
    p90 = rts[int(n * 0.9)] if n else 0
    p95 = rts[int(n * 0.95)] if n else 0
    p99 = rts[int(n * 0.99)] if n else 0
    final = {
        "type": "final",
        "elapsed": round(elapsed, 1),
        "requests": reqs,
        "failures": fails,
        "rps": round(rps, 2),
        "avg_rt": round(avg_rt, 2),
        "min_rt": round(stats["min_rt"], 2) if stats["min_rt"] != float("inf") else 0,
        "max_rt": round(stats["max_rt"], 2),
        "p50_rt": round(p50, 2),
        "p90_rt": round(p90, 2),
        "p95_rt": round(p95, 2),
        "p99_rt": round(p99, 2),
    }
    print(json.dumps(final), flush=True)

if __name__ == "__main__":
    import argparse, threading
    p = argparse.ArgumentParser()
    p.add_argument("--script", required=True)
    p.add_argument("--host", required=True)
    p.add_argument("--concurrency", type=int, default=10)
    p.add_argument("--spawn-rate", type=float, default=1)
    p.add_argument("--duration", type=int, default=60)
    a = p.parse_args()
    run_test(a.script, a.host, a.concurrency, a.spawn_rate, a.duration)
'''


# ================================================================
# 运行态数据结构
# ================================================================

@dataclass
class _RunningTask:
    """单个执行任务的运行态"""
    task_id: int
    result_id: int
    process: Optional[subprocess.Popen] = None
    stream_queue: Optional[asyncio.Queue] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    monitor_thread: Optional[threading.Thread] = None
    status: str = "running"          # running / completed / failed / stopped
    error: str = ""
    start_time: float = 0.0
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    final_stats: Dict[str, Any] = field(default_factory=dict)


# ================================================================
# 性能测试执行引擎 (单例)
# ================================================================

class PerformanceExecutor:
    """性能测试执行引擎

    使用方式:
        executor = PerformanceExecutor()
        result = await executor.execute(
            task_id=1,
            script_content="...",
            concurrency=50,
            duration_seconds=60,
            ramp_up=10,
            host="https://example.com",
        )
        # 获取实时流
        queue = executor.get_stream_queue(1)
        # 停止
        await executor.stop(1)
    """

    _instance: Optional["PerformanceExecutor"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "PerformanceExecutor":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._running: Dict[int, _RunningTask] = {}
        self._initialized = True

    # ----------------------------------------------------------------
    # 公开接口
    # ----------------------------------------------------------------

    async def execute(
        self,
        task_id: int,
        result_id: int,
        script_content: str,
        concurrency: int = 10,
        duration_seconds: int = 60,
        ramp_up: int = 10,
        host: str = "",
    ) -> Dict[str, Any]:
        """启动性能测试执行

        Returns:
            {"status": "started", "result_id": int, "task_id": int}
        """
        # 如果已有运行中的任务, 先停止
        if task_id in self._running and self._running[task_id].status == "running":
            await self.stop(task_id)

        # 创建 stream queue (在事件循环中创建)
        stream_queue = asyncio.Queue()

        rt = _RunningTask(
            task_id=task_id,
            result_id=result_id,
            stream_queue=stream_queue,
            start_time=time.time(),
        )
        self._running[task_id] = rt

        # 写入临时文件
        script_file = self._write_temp_script(script_content)
        runner_file = self._write_runner_script()

        # 构建命令
        cmd = [
            sys.executable, runner_file,
            "--script", script_file,
            "--host", host,
            "--concurrency", str(concurrency),
            "--spawn-rate", str(max(1, concurrency // max(ramp_up, 1))),
            "--duration", str(duration_seconds),
        ]

        logger.info(
            f"[PerformanceExecutor] 启动 Locust: task_id={task_id}, "
            f"concurrency={concurrency}, duration={duration_seconds}s, host={host}"
        )

        # 在线程中运行子进程 + 指标采集
        rt.monitor_thread = threading.Thread(
            target=self._monitor_subprocess,
            args=(rt, cmd, script_file, runner_file),
            daemon=True,
        )
        rt.monitor_thread.start()

        return {"status": "started", "result_id": result_id, "task_id": task_id}

    async def stop(self, task_id: int) -> Dict[str, Any]:
        """停止正在运行的测试"""
        rt = self._running.get(task_id)
        if not rt or rt.status != "running":
            return {"status": "not_running", "task_id": task_id}

        rt.stop_event.set()
        rt.status = "stopped"

        if rt.process:
            try:
                rt.process.terminate()
                # 等待 3 秒, 强制 kill
                try:
                    rt.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    rt.process.kill()
            except Exception as e:
                logger.warning(f"[PerformanceExecutor] 停止进程失败: {e}")

        # 推送停止事件到 SSE 队列
        if rt.stream_queue:
            await self._push_event(rt, {
                "type": "stopped",
                "task_id": task_id,
                "timestamp": time.time(),
                "message": "测试已手动停止",
            })

        logger.info(f"[PerformanceExecutor] 任务 {task_id} 已停止")
        return {"status": "stopped", "task_id": task_id}

    def get_stream_queue(self, task_id: int) -> Optional[asyncio.Queue]:
        """获取实时指标流队列 (供 SSE 端点消费)"""
        rt = self._running.get(task_id)
        if rt:
            return rt.stream_queue
        return None

    def get_status(self, task_id: int) -> Dict[str, Any]:
        """获取执行状态"""
        rt = self._running.get(task_id)
        if not rt:
            return {"status": "not_found", "task_id": task_id}

        elapsed = time.time() - rt.start_time if rt.status == "running" else 0
        return {
            "task_id": task_id,
            "result_id": rt.result_id,
            "status": rt.status,
            "elapsed": round(elapsed, 1),
            "error": rt.error,
            "metrics_count": len(rt.metrics),
            "final_stats": rt.final_stats if rt.final_stats else None,
        }

    def is_running(self, task_id: int) -> bool:
        """检查任务是否正在运行"""
        rt = self._running.get(task_id)
        return rt is not None and rt.status == "running"

    def cleanup(self, task_id: int) -> None:
        """清理已完成任务的运行态"""
        rt = self._running.get(task_id)
        if rt and rt.status in ("completed", "failed", "stopped"):
            self._running.pop(task_id, None)

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    @staticmethod
    def _write_temp_script(script_content: str) -> str:
        """将 Locust 脚本写入临时文件"""
        fd, path = tempfile.mkstemp(suffix=".py", prefix="locust_script_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(script_content)
        return path

    @staticmethod
    def _write_runner_script() -> str:
        """将 runner 脚本写入临时文件"""
        fd, path = tempfile.mkstemp(suffix=".py", prefix="locust_runner_")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(_RUNNER_SCRIPT)
        return path

    def _monitor_subprocess(
        self,
        rt: _RunningTask,
        cmd: List[str],
        script_file: str,
        runner_file: str,
    ) -> None:
        """在独立线程中监控子进程, 采集指标"""
        try:
            rt.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
            )

            # psutil 可用性检查
            psutil_ok = False
            try:
                import psutil
                psutil_ok = True
            except ImportError:
                logger.warning("[PerformanceExecutor] psutil 未安装, 跳过 CPU/Memory 采集")

            # CPU/Memory 采集线程
            if psutil_ok:
                cpu_thread = threading.Thread(
                    target=self._collect_resource_metrics,
                    args=(rt,),
                    daemon=True,
                )
                cpu_thread.start()

            # 读取子进程 stdout (JSON 行)
            last_metric = None
            for line in rt.process.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug(f"[PerformanceExecutor] 无法解析行: {line[:100]}")
                    continue

                if data.get("type") == "error":
                    rt.status = "failed"
                    rt.error = data.get("message", "Runner 脚本错误")
                    break

                if data.get("type") == "stats":
                    metric = self._build_metric(rt, data)
                    rt.metrics.append(metric)
                    last_metric = metric
                    # 异步推送
                    self._safe_put(rt, metric)

                elif data.get("type") == "final":
                    rt.final_stats = data
                    # 推送最终结果
                    self._safe_put(rt, {
                        "type": "final",
                        "task_id": rt.task_id,
                        "timestamp": time.time(),
                        "data": data,
                    })

            # 等待进程结束
            rt.process.wait()
            stderr_output = rt.process.stderr.read() if rt.process.stderr else ""

            if rt.status == "running":
                if rt.process.returncode == 0:
                    rt.status = "completed"
                elif rt.stop_event.is_set():
                    rt.status = "stopped"
                else:
                    rt.status = "failed"
                    if stderr_output:
                        rt.error = stderr_output[:500]

            # 推送结束事件
            self._safe_put(rt, {
                "type": "end",
                "task_id": rt.task_id,
                "status": rt.status,
                "timestamp": time.time(),
                "error": rt.error,
                "final_stats": rt.final_stats,
            })

            logger.info(
                f"[PerformanceExecutor] 任务 {rt.task_id} 结束: status={rt.status}, "
                f"metrics={len(rt.metrics)}"
            )

        except FileNotFoundError:
            rt.status = "failed"
            rt.error = "Locust 或 Python 环境不可用, 请确保 locust 包已安装"
            self._safe_put(rt, {
                "type": "end", "task_id": rt.task_id,
                "status": "failed", "error": rt.error,
                "timestamp": time.time(),
            })
        except Exception as e:
            rt.status = "failed"
            rt.error = str(e)
            logger.exception(f"[PerformanceExecutor] 监控线程异常: {e}")
            self._safe_put(rt, {
                "type": "end", "task_id": rt.task_id,
                "status": "failed", "error": str(e),
                "timestamp": time.time(),
            })
        finally:
            # 清理临时文件
            for f in (script_file, runner_file):
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def _collect_resource_metrics(self, rt: _RunningTask) -> None:
        """使用 psutil 采集 CPU / Memory (每秒一次)"""
        import psutil

        while not rt.stop_event.is_set() and rt.status == "running":
            try:
                cpu = psutil.cpu_percent(interval=1)
                mem = psutil.virtual_memory()

                # 将资源指标附加到最近的一条 metric
                if rt.metrics:
                    last = rt.metrics[-1]
                    if last.get("cpu_percent") is None:
                        last["cpu_percent"] = round(cpu, 1)
                        last["memory_mb"] = round(mem.used / 1024 / 1024, 1)

            except Exception as e:
                logger.debug(f"[PerformanceExecutor] 资源采集异常: {e}")
                break

    @staticmethod
    def _build_metric(rt: _RunningTask, data: Dict) -> Dict[str, Any]:
        """从 runner 输出构建 metric 字典"""
        return {
            "type": "metric",
            "task_id": rt.task_id,
            "result_id": rt.result_id,
            "timestamp": data.get("timestamp", time.time()),
            "elapsed": data.get("elapsed", 0),
            "tps": data.get("rps", 0),
            "avg_rt": data.get("avg_rt", 0),
            "concurrent_users": data.get("concurrent_users", 0),
            "error_count": data.get("failures", 0),
            "total_requests": data.get("requests", 0),
            "cpu_percent": None,
            "memory_mb": None,
            # 额外百分位数据 (供分析使用)
            "p50_rt": data.get("p50_rt"),
            "p90_rt": data.get("p90_rt"),
            "p95_rt": data.get("p95_rt"),
            "p99_rt": data.get("p99_rt"),
            "min_rt": data.get("min_rt"),
            "max_rt": data.get("max_rt"),
        }

    def _safe_put(self, rt: _RunningTask, event: Dict[str, Any]) -> None:
        """安全推送事件到 asyncio.Queue (线程安全)"""
        if rt.stream_queue is None:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    rt.stream_queue.put(event), loop
                )
            else:
                # 如果事件循环未运行, 直接 put (同步)
                rt.stream_queue.put_nowait(event)
        except RuntimeError:
            # 没有事件循环, 尝试创建新的
            try:
                rt.stream_queue.put_nowait(event)
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"[PerformanceExecutor] 推送事件失败: {e}")

    async def _push_event(self, rt: _RunningTask, event: Dict[str, Any]) -> None:
        """异步推送事件"""
        if rt.stream_queue:
            await rt.stream_queue.put(event)


# ================================================================
# 单例获取
# ================================================================

def get_performance_executor() -> PerformanceExecutor:
    """获取性能测试执行引擎单例"""
    return PerformanceExecutor()
