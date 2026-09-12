"""
ExecutionAgent - 执行Playwright脚本

职责：
1. 读取数据库中的Playwright脚本
2. 保存临时脚本文件
3. 执行Playwright（subprocess）
4. 实时输出日志（通过回调）
5. 保存执行截图
6. 生成HTML测试报告
7. 返回执行结果
8. 失败分析：截图+日志 → LLM分析 → 原因+建议
"""
import os
import sys

from app.utils.browser_launcher import get_launch_code_snippet
import json
import time
import tempfile
import subprocess
import threading
import base64
from datetime import datetime
from typing import Callable, Dict, Any, Optional, List
from app.core.logger import log
from app.core.config import settings
from app.core.llm import call_llm
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ExecutionAgent(NewBaseAgent):
    """Playwright脚本执行Agent"""

    agent_name = "execution_agent"
    display_name = "脚本执行Agent"
    description = "执行Playwright脚本，实时输出日志，生成HTML测试报告并分析失败原因"
    capabilities = [AgentCapability.SCRIPT_EXECUTE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "execution"
        self.model = None
        self.system_prompt = None

    def execute_script(
        self,
        script_content: str,
        task_id: int,
        execution_id: int,
        on_log: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """
        执行Playwright脚本

        Args:
            script_content: 脚本内容
            task_id: 任务ID
            execution_id: 执行记录ID
            on_log: 日志回调函数，用于SSE实时推送

        Returns:
            执行结果字典
        """
        # [DEBUG] 进入函数 / 执行脚本前
        _exec_start = datetime.now()
        _start_ts = time.time()
        log.info(f"[DEBUG] 开始：ExecutionAgent.execute_script | 输入：task_id={task_id}, execution_id={execution_id}, script_length={len(script_content)}")

        start_time = datetime.now()
        result = {
            "status": "failed",
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "end_time": None,
            "duration": 0,
            "success_count": 0,
            "failed_count": 0,
            "error_message": None,
            "log_content": "",
            "screenshot_path": None,
            "report_path": None,
        }

        # 确保目录存在（使用系统临时目录，避免WatchFiles误触发重启）
        import tempfile
        reports_dir = os.path.join(tempfile.gettempdir(), "test_automation_reports")
        screenshots_dir = os.path.join(reports_dir, "screenshots")
        os.makedirs(screenshots_dir, exist_ok=True)

        # 构建带截图和日志的增强脚本
        enhanced_script = self._build_enhanced_script(
            script_content, task_id, execution_id, screenshots_dir
        )

        # 保存临时脚本文件（使用系统临时目录，避免WatchFiles误触发重启）
        import tempfile
        script_dir = os.path.join(tempfile.gettempdir(), "test_automation_scripts")
        os.makedirs(script_dir, exist_ok=True)
        script_path = os.path.join(script_dir, f"task_{task_id}_exec_{execution_id}.py")

        hang_timer = None
        timed_out = False
        try:
            with open(script_path, "w", encoding="utf-8") as f:
                f.write(enhanced_script)
            log.info(f"执行脚本已保存: {script_path}")

            self._emit_log(on_log, "开始执行", 10, f"脚本文件已准备: {os.path.basename(script_path)}")

            # 执行脚本
            log_lines = []
            success_count = 0
            failed_count = 0

            self._emit_log(on_log, "执行脚本", 20, "正在启动Playwright...")

            # 使用subprocess执行，实时读取输出
            env = os.environ.copy()
            env["PYTHONIOENCODING"] = "utf-8"
            env["PLAYWRIGHT_BROWSERS_PATH"] = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "")
            env["PLAYWRIGHT_CHROME_PATH"] = os.environ.get("PLAYWRIGHT_CHROME_PATH", "")
            env["PLAYWRIGHT_HEADLESS"] = os.environ.get("PLAYWRIGHT_HEADLESS", "True")

            proc = subprocess.Popen(
                [sys.executable, "-u", script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                bufsize=1,
            )

            def _kill_hung_process():
                nonlocal timed_out
                if proc.poll() is None:
                    timed_out = True
                    proc.kill()
                    self._emit_log(on_log, "执行异常", 100, "测试执行超时，已停止浏览器")

            hang_timer = threading.Timer(90, _kill_hung_process)
            hang_timer.daemon = True
            hang_timer.start()

            # 实时读取输出
            progress = 20
            for line in iter(proc.stdout.readline, b""):
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace").rstrip()
                log_lines.append(line_str)

                # 解析特殊标记行
                if line_str.startswith("##TEST_START##"):
                    test_name = line_str.replace("##TEST_START##", "").strip()
                    progress = min(progress + 8, 85)
                    self._emit_log(on_log, f"执行: {test_name}", progress, f"开始执行测试: {test_name}")

                elif line_str.startswith("##TEST_PASS##"):
                    test_name = line_str.replace("##TEST_PASS##", "").strip()
                    success_count += 1
                    self._emit_log(on_log, f"通过: {test_name}", progress, f"✓ 测试通过: {test_name}")

                elif line_str.startswith("##TEST_FAIL##"):
                    parts = line_str.replace("##TEST_FAIL##", "").strip()
                    failed_count += 1
                    result["error_message"] = parts
                    self._emit_log(on_log, f"失败: {parts}", progress, f"✗ 测试失败: {parts}")

                elif line_str.startswith("##LOCATOR_DIAG##"):
                    raw_diag = line_str.replace("##LOCATOR_DIAG##", "").strip()
                    try:
                        result["locator_diagnosis"] = json.loads(raw_diag)
                    except Exception:
                        result["locator_diagnosis"] = {"raw": raw_diag[:1000]}
                    diag = result["locator_diagnosis"] if isinstance(result.get("locator_diagnosis"), dict) else {}
                    self._emit_log(
                        on_log,
                        "定位诊断",
                        progress,
                        (
                            f"url={diag.get('url')} locator={diag.get('locator')} "
                            f"count={diag.get('count')} screenshot={diag.get('screenshot')}"
                        ),
                    )

                elif line_str.startswith("##STEP##"):
                    step_info = line_str.replace("##STEP##", "").strip()
                    self._emit_log(on_log, "执行步骤", progress, step_info)

                elif "Error" in line_str or "error" in line_str.lower():
                    self._emit_log(on_log, "执行日志", progress, line_str)

            proc.wait()
            hang_timer.cancel()
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()

            result["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
            result["duration"] = round(duration, 2)
            result["success_count"] = success_count
            result["failed_count"] = failed_count
            result["log_content"] = "\n".join(log_lines)

            # 检查截图
            screenshot_file = os.path.join(screenshots_dir, f"exec_{execution_id}_final.png")
            if os.path.exists(screenshot_file):
                result["screenshot_path"] = screenshot_file

            if timed_out:
                result["status"] = "failed"
                result["error_message"] = result.get("error_message") or "测试执行超时"
                if failed_count == 0:
                    result["failed_count"] = 1
                    failed_count = 1
                self._emit_log(on_log, "执行失败", 90, "测试执行超时")
            elif proc.returncode == 0:
                result["status"] = "success"
                self._emit_log(on_log, "执行完成", 90, f"脚本执行完成 | 通过: {success_count}, 失败: {failed_count}, 耗时: {duration:.1f}s")
            else:
                result["status"] = "failed"
                if failed_count == 0 and not result["error_message"]:
                    result["error_message"] = f"进程退出码: {proc.returncode}"
                self._emit_log(on_log, "执行失败", 90, f"脚本执行失败 | 退出码: {proc.returncode}")

            # 生成HTML报告
            self._emit_log(on_log, "生成报告", 95, "正在生成测试报告...")
            report_path = self._generate_html_report(
                task_id, execution_id, result, start_time, end_time, screenshots_dir
            )
            result["report_path"] = report_path
            self._emit_log(on_log, "任务完成", 100, "测试报告已生成")

        except Exception as e:
            try:
                hang_timer.cancel()
            except Exception:
                pass
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            result["status"] = "failed"
            result["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
            result["duration"] = round(duration, 2)
            result["error_message"] = err_msg
            result["log_content"] = "\n".join(log_lines) if log_lines else err_msg
            self._emit_log(on_log, "执行异常", 100, f"执行异常: {err_msg}")
            log.error(f"ExecutionAgent执行异常 | task={task_id}, exec={execution_id}: {err_msg}")

        finally:
            # 清理临时脚本
            if os.path.exists(script_path):
                try:
                    os.remove(script_path)
                except Exception:
                    pass

        # [DEBUG] 结束
        _exec_elapsed = time.time() - _start_ts
        log.info(f"[DEBUG] 结束：ExecutionAgent.execute_script | 输出：status={result['status']}, duration={result['duration']}, success={result['success_count']}, failed={result['failed_count']} | 耗时：{_exec_elapsed:.2f}s")

        return result

    def _build_enhanced_script(
        self,
        original_script: str,
        task_id: int,
        execution_id: int,
        screenshots_dir: str
    ) -> str:
        """
        构建增强脚本：在原始脚本外层包裹日志输出和截图逻辑

        原始脚本中的 test_xxx 函数会被自动发现并执行
        """
        screenshot_file = os.path.join(screenshots_dir, f"exec_{execution_id}_final.png")

        wrapper = f'''"""自动执行脚本 - 由ExecutionAgent生成"""
import json
import re
import sys
import traceback

# 标记输出函数
def _log(tag, msg=""):
    print(f"##{{tag}}## {{msg}}", flush=True)

def _step(msg):
    print(f"##STEP## {{msg}}", flush=True)

# Playwright fixture
from playwright.sync_api import sync_playwright

_log("STEP", "初始化Playwright...")

pw = sync_playwright().start()
{get_launch_code_snippet()}
context = browser.new_context(
    viewport={{"width": 1920, "height": 1080}},
    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    locale="zh-CN",
)
context.add_init_script("""
    Object.defineProperty(navigator, 'webdriver', {{get: () => undefined}});
""")
page = context.new_page()
page.set_default_timeout(20000)
page.set_default_navigation_timeout(25000)

# 注入 page fixture 到全局
import builtins
builtins.page = page

# ============ 原始脚本内容 ============
{original_script}
# ============ 原始脚本结束 ============

# 自动发现并执行 test_ 开头的函数
import inspect
_test_funcs = []
for _name, _obj in sorted(globals().items()):
    if _name.startswith("test_") and callable(_obj):
        _test_funcs.append((_name, _obj))
    elif inspect.isclass(_obj) and _name.startswith("Test"):
        _inst = _obj()
        for _mname, _meth in inspect.getmembers(_inst, predicate=inspect.ismethod):
            if _mname.startswith("test_"):
                _test_funcs.append((_mname, _meth))

_log("STEP", f"发现 {{len(_test_funcs)}} 个测试用例")

_passed = 0
_failed = 0

if not _test_funcs:
    _log("TEST_FAIL", "未发现可执行的 test_ 函数，拒绝将空执行记为成功")
    _failed = 1

for _name, _func in _test_funcs:
    _log("TEST_START", _name)
    try:
        _func(page)
        _log("TEST_PASS", _name)
        _passed += 1
    except Exception as _e:
        _err = f"{{_name}}: {{type(_e).__name__}}: {{_e}}"
        _log("TEST_FAIL", _err)
        try:
            _diag = {{
                "url": page.url,
                "error": str(_e),
                "locator": "",
                "count": None,
                "html_snippet": "",
                "screenshot": r"{screenshot_file}",
            }}
            _m = re.search(r"(page\\.(?:get_by_\\w+|locator)\\([^)]*\\))", str(_e))
            if _m:
                _diag["locator"] = _m.group(1)
                try:
                    _loc = eval(_m.group(1), {{"page": page}})
                    _diag["count"] = _loc.count()
                    if _diag["count"]:
                        _diag["html_snippet"] = (_loc.first.evaluate("el => el.outerHTML") or "")[:500]
                except Exception as _pe:
                    _diag["probe_error"] = str(_pe)
            if not _diag["html_snippet"]:
                try:
                    _diag["html_snippet"] = (page.content() or "")[:800]
                except Exception:
                    pass
            try:
                page.screenshot(path=r"{screenshot_file}")
            except Exception:
                pass
            _log("LOCATOR_DIAG", json.dumps(_diag, ensure_ascii=False))
        except Exception:
            traceback.print_exc()
        _failed += 1
        traceback.print_exc()

# 保存最终截图
try:
    page.screenshot(path=r"{screenshot_file}")
    _log("STEP", "最终截图已保存")
except Exception:
    pass

# 清理
try:
    page.close()
    context.close()
    browser.close()
    pw.stop()
except Exception:
    pass

_log("STEP", f"执行完毕 | 通过: {{_passed}}, 失败: {{_failed}}")
sys.exit(1 if _failed > 0 else 0)
'''
        return wrapper

    def _generate_html_report(
        self,
        task_id: int,
        execution_id: int,
        result: Dict[str, Any],
        start_time: datetime,
        end_time: datetime,
        screenshots_dir: str
    ) -> str:
        """生成HTML测试报告"""
        import tempfile
        reports_dir = os.path.join(tempfile.gettempdir(), "test_automation_reports")
        os.makedirs(reports_dir, exist_ok=True)
        report_path = os.path.join(reports_dir, f"report_{execution_id}.html")

        status_color = "#52c41a" if result["status"] == "success" else "#ff4d4f"
        status_text = "通过" if result["status"] == "success" else "失败"

        # 读取截图转base64
        screenshot_base64 = ""
        if result.get("screenshot_path") and os.path.exists(result["screenshot_path"]):
            import base64
            with open(result["screenshot_path"], "rb") as f:
                screenshot_base64 = base64.b64encode(f.read()).decode("utf-8")

        # 格式化日志
        log_lines = (result.get("log_content") or "").split("\n")
        log_html = ""
        for line in log_lines:
            color = "#333"
            if "##TEST_PASS##" in line:
                color = "#52c41a"
            elif "##TEST_FAIL##" in line:
                color = "#ff4d4f"
            elif "##STEP##" in line:
                color = "#1890ff"
            elif "Error" in line or "error" in line.lower():
                color = "#ff4d4f"
            log_html += f'<div style="color:{color};padding:2px 0;font-family:Consolas,monospace;font-size:13px;">{self._html_escape(line)}</div>\n'

        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>测试报告 - 任务{task_id}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; color: #333; }}
        .container {{ max-width: 1000px; margin: 0 auto; padding: 24px; }}
        .header {{ background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .header h1 {{ font-size: 24px; margin-bottom: 16px; }}
        .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 4px; color: white; font-weight: 600; background: {status_color}; }}
        .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 16px; }}
        .stat-card {{ background: #fafafa; border-radius: 6px; padding: 16px; text-align: center; }}
        .stat-card .value {{ font-size: 28px; font-weight: 700; }}
        .stat-card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
        .section {{ background: white; border-radius: 8px; padding: 24px; margin-bottom: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        .section h2 {{ font-size: 18px; margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid #eee; }}
        .log-container {{ background: #1e1e1e; border-radius: 6px; padding: 16px; max-height: 500px; overflow-y: auto; }}
        .screenshot {{ max-width: 100%; border-radius: 6px; border: 1px solid #eee; }}
        .error {{ background: #fff2f0; border: 1px solid #ffccc7; border-radius: 6px; padding: 12px; color: #ff4d4f; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>测试报告 <span class="status-badge">{status_text}</span></h1>
            <div class="stats">
                <div class="stat-card">
                    <div class="value">{result.get('success_count', 0)}</div>
                    <div class="label">通过用例</div>
                </div>
                <div class="stat-card">
                    <div class="value" style="color:#ff4d4f">{result.get('failed_count', 0)}</div>
                    <div class="label">失败用例</div>
                </div>
                <div class="stat-card">
                    <div class="value">{result.get('duration', 0):.1f}s</div>
                    <div class="label">执行耗时</div>
                </div>
                <div class="stat-card">
                    <div class="value">{result.get('success_count', 0) + result.get('failed_count', 0)}</div>
                    <div class="label">总用例数</div>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>执行信息</h2>
            <table style="width:100%;border-collapse:collapse;">
                <tr><td style="padding:8px;color:#888;width:120px;">任务ID</td><td style="padding:8px;">{task_id}</td></tr>
                <tr><td style="padding:8px;color:#888;">执行ID</td><td style="padding:8px;">{execution_id}</td></tr>
                <tr><td style="padding:8px;color:#888;">开始时间</td><td style="padding:8px;">{result.get('start_time', '-')}</td></tr>
                <tr><td style="padding:8px;color:#888;">结束时间</td><td style="padding:8px;">{result.get('end_time', '-')}</td></tr>
                <tr><td style="padding:8px;color:#888;">执行耗时</td><td style="padding:8px;">{result.get('duration', 0):.2f}秒</td></tr>
            </table>
        </div>

        {"<div class='section'><h2>错误信息</h2><div class='error'>" + self._html_escape(result.get('error_message', '')) + "</div></div>" if result.get('error_message') else ""}

        <div class="section">
            <h2>执行日志</h2>
            <div class="log-container">
                {log_html}
            </div>
        </div>

        {"<div class='section'><h2>执行截图</h2><img class='screenshot' src='data:image/png;base64," + screenshot_base64 + "' /></div>" if screenshot_base64 else ""}
    </div>
</body>
</html>"""

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(html)

        log.info(f"测试报告已生成: {report_path}")
        return report_path

    @staticmethod
    def _emit_log(on_log: Optional[Callable], step: str, progress: int, message: str):
        """发送日志回调"""
        if on_log:
            on_log({
                "step": step,
                "progress": progress,
                "message": message,
            })

    @staticmethod
    def _html_escape(text: str) -> str:
        """HTML转义"""
        if not text:
            return ""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    def analyze_failure(
        self,
        log_content: str,
        error_message: str = "",
        script_content: str = "",
        screenshot_path: str = "",
    ) -> Dict[str, Any]:
        """
        LLM分析执行失败原因

        流程：截图 + 日志 + 错误信息 → LLM分析 → 原因 + 建议

        Args:
            log_content: 执行日志
            error_message: 错误信息
            script_content: 原始脚本内容
            screenshot_path: 截图文件路径

        Returns:
            {
                "success": bool,
                "fail_step": str,
                "root_cause": str,
                "suggestion": str
            }
        """
        # [DEBUG] 进入函数
        _analyze_start = time.time()
        log.info(f"[DEBUG] 开始：ExecutionAgent.analyze_failure | 输入：log_length={len(log_content or '')}, error={error_message[:50] if error_message else 'None'}")

        log.info("ExecutionAgent.analyze_failure | 开始LLM失败分析")

        # 构建分析Prompt
        prompt = self._build_analysis_prompt(log_content, error_message, script_content, screenshot_path)

        try:
            # [DEBUG] 调用LLM前
            log.info(f"[DEBUG] 调用LLM前：ExecutionAgent.analyze_failure._call_llm | 输入：prompt_length={len(prompt)}")
    
            raw = self._call_llm(prompt)
            result = self._parse_analysis_result(raw)

            # [DEBUG] LLM返回后
            _analyze_elapsed = time.time() - _analyze_start
            log.info(f"[DEBUG] 结束：ExecutionAgent.analyze_failure | 输出：root_cause={result.get('root_cause', '')[:50]} | 耗时：{_analyze_elapsed:.2f}s")
    
            log.info(f"ExecutionAgent.analyze_failure | 分析完成 | 原因: {result.get('root_cause', '')[:50]}")
            return result
        except Exception as e:
            # [DEBUG] 异常
            _analyze_elapsed = time.time() - _analyze_start
            log.warning(f"[DEBUG] 异常：ExecutionAgent.analyze_failure | 错误：{e} | 耗时：{_analyze_elapsed:.2f}s")
    
            log.warning(f"ExecutionAgent.analyze_failure | LLM分析失败，使用规则分析: {e}")
            return self._rule_based_analysis(log_content, error_message)

    def _build_analysis_prompt(
        self,
        log_content: str,
        error_message: str,
        script_content: str,
        screenshot_path: str,
    ) -> str:
        """构建失败分析Prompt"""
        # 截取日志（避免过长）
        log_preview = (log_content or "")[-3000:] if log_content else "无日志"
        script_preview = (script_content or "")[-2000:] if script_content else "无脚本"
        error_preview = (error_message or "")[:500] if error_message else "无明确错误信息"

        # 截图描述
        screenshot_desc = ""
        if screenshot_path and os.path.exists(screenshot_path):
            screenshot_desc = "（已提供执行截图，请结合截图分析页面状态）"
        else:
            screenshot_desc = "（无执行截图）"

        expert = ""
        try:
            from app.knowledge.testing_expert import expert_prompt_for
            expert = expert_prompt_for(f"{error_preview} flaky timeout locator 失败诊断")
        except Exception:
            expert = ""
        expert_block = f"\n测试专家知识:\n{expert}\n" if expert else ""

        return f"""你是一名资深自动化测试工程师，请分析以下Playwright脚本执行失败的原因。
先区分：环境问题、测试数据、定位/等待脚本问题、产品缺陷。不要把超时一律报成产品Bug。
{expert_block}

执行错误信息:
{error_preview}

执行日志（最后部分）:
{log_preview}

原始脚本（最后部分）:
{script_preview}

{screenshot_desc}

请分析失败原因，并严格按以下JSON格式输出（不要输出其他内容）:
{{
    "success": false,
    "fail_step": "失败的步骤描述",
    "root_cause": "根本原因分析",
    "suggestion": "修复建议"
}}"""

    def _parse_analysis_result(self, raw: str) -> Dict[str, Any]:
        """解析LLM返回的分析结果"""
        # 尝试提取JSON
        text = raw.strip()
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()

        try:
            result = json.loads(text)
            # 确保必要字段存在
            return {
                "success": bool(result.get("success", False)),
                "fail_step": str(result.get("fail_step", "")),
                "root_cause": str(result.get("root_cause", "")),
                "suggestion": str(result.get("suggestion", "")),
            }
        except json.JSONDecodeError:
            # JSON解析失败，尝试从文本中提取
            return {
                "success": False,
                "fail_step": "解析失败",
                "root_cause": text[:300] if text else "LLM返回格式异常",
                "suggestion": "请检查脚本和日志手动分析",
            }

    def _rule_based_analysis(self, log_content: str, error_message: str) -> Dict[str, Any]:
        """基于规则的失败分析（LLM不可用时的降级方案）"""
        fail_step = "未知步骤"
        root_cause = "执行失败"
        suggestion = "请检查脚本和日志"

        combined = f"{log_content or ''}\n{error_message or ''}".lower()

        # 常见错误模式匹配
        if "timeout" in combined or "waiting for selector" in combined or "locator." in combined or "get_by_" in combined:
            fail_step = "元素未找到"
            root_cause = "目标元素在当前页面不存在，或定位方式无法匹配"
            suggestion = "请核对当前页面、目标元素和已尝试的定位方式"
        elif "navigation" in combined or "net::err" in combined:
            fail_step = "页面导航失败"
            root_cause = "页面URL无法访问或导航超时"
            suggestion = "建议检查目标URL是否可访问，增加导航超时时间"
        elif "assertion" in combined or "expect" in combined:
            fail_step = "断言失败"
            root_cause = "页面实际状态与预期不符"
            suggestion = "建议检查断言条件是否合理，页面是否已正确加载"
        elif "no element matching" in combined or "locator" in combined:
            fail_step = "元素定位失败"
            root_cause = "CSS选择器或XPath无法匹配到页面元素"
            suggestion = "建议检查定位器是否正确，元素是否在当前页面存在"
        elif "click" in combined:
            fail_step = "点击操作失败"
            root_cause = "元素可能被遮挡、不可点击或已从DOM中移除"
            suggestion = "建议添加等待、检查元素可见性或使用force点击"
        elif "fill" in combined or "type" in combined:
            fail_step = "输入操作失败"
            root_cause = "输入框不可用或不可见"
            suggestion = "建议先点击输入框使其获得焦点，再输入内容"
        elif error_message:
            fail_step = "脚本执行异常"
            root_cause = error_message[:200]
            suggestion = "建议根据错误信息检查脚本逻辑"
        elif "import" in combined or "module" in combined or "syntaxerror" in combined:
            fail_step = "脚本语法错误"
            root_cause = "脚本存在语法错误或导入失败"
            suggestion = "建议检查脚本语法，确保所有依赖已安装"

        return {
            "success": False,
            "fail_step": fail_step,
            "root_cause": root_cause,
            "suggestion": suggestion,
        }

    def _call_llm(self, prompt: str) -> str:
        """调用LLM API进行失败分析"""
        return call_llm(
            "你是一名资深自动化测试工程师，擅长分析Playwright脚本执行失败的原因。请严格按照JSON格式输出分析结果。",
            prompt,
            temperature=0.2,
        )
