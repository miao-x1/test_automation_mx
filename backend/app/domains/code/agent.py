"""
CodeAgent — 代码执行型 Agent

流程:
  用户需求 → LLM 生成代码 → 代码安全检查 → Sandbox 执行 → 返回结果

设计约束:
  1. 禁止直接执行用户代码 — 所有代码由 LLM 生成, 并经过安全检查
  2. 所有代码在沙箱中执行 (Docker 隔离 / 本地子进程)
  3. 限制权限 — 非 root 用户、只读文件系统、网络禁用
  4. 限制时间 — 执行超时自动终止
  5. 限制资源 — CPU / 内存上限
  6. LLM 调用必须通过 LLMGateway (BaseRoutedAgent.call_llm)

支持的任务类型:
  - analyze_excel:      分析 Excel 数据
  - process_data:       处理测试数据 (清洗 / 转换)
  - generate_stats:     生成统计结果
  - visualize:          数据可视化 (matplotlib)
  - execute_code:       通用代码执行 (直接提供代码)
  - generate_and_run:   LLM 生成代码并执行 (默认)

Action:
  generate_code:    仅生成代码 (不执行)
  run:              生成代码 + 安全检查 + 沙箱执行
  execute:          直接执行已有代码 (仍经过安全检查)
  check_security:   仅检查代码安全性
"""
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.runtime.base_agent import BaseRoutedAgent, action_handler
from app.sandbox.executor import (
    SandboxExecutor,
    ExecutionConfig,
    ExecutionMode,
    ExecutionResult,
)
from app.sandbox.security import CodeSecurityChecker, SecurityLevel

logger = logging.getLogger(__name__)


# ================================================================
# System Prompt — LLM 代码生成
# ================================================================

CODE_GENERATION_PROMPT = """你是一个 Python 代码生成专家。
根据用户的自然语言需求, 生成可执行的 Python 代码。

任务类型:
  - analyze_excel:      分析 Excel 数据 (使用 openpyxl/pandas)
  - process_data:       处理测试数据 (清洗 / 转换 / 格式化)
  - generate_stats:     生成统计结果 (描述统计 / 频率 / 分组聚合)
  - visualize:          数据可视化 (matplotlib)
  - execute_code:       通用计算

代码约束:
  1. 只能使用以下模块 (白名单):
     数据处理: json, csv, re, math, statistics, collections, itertools
     日期: datetime, calendar
     数据分析: pandas, numpy, scipy, sklearn
     Excel: openpyxl, xlrd
     可视化: matplotlib, seaborn
     其他: typing, dataclasses, copy, pprint

  2. 禁止使用以下模块 (黑名单):
     os, sys, subprocess, socket, shutil, ctypes, threading, multiprocessing,
     importlib, pickle, tempfile, signal

  3. 禁止操作:
     - 文件写入 (open() 仅允许只读模式)
     - 网络访问 (socket, urllib, requests)
     - 进程操作 (os.system, subprocess)
     - eval / exec / compile / __import__

  4. 代码规范:
     - 使用 print() 输出结果
     - 处理异常, 不要让代码崩溃
     - 代码简洁, 最多 200 行
     - 中文注释

输出格式 (严格 JSON):
{
  "code": "完整的 Python 代码",
  "description": "代码功能描述",
  "expected_output": "预期输出说明",
  "required_packages": ["需要的额外pip包"]
}

注意: code 字段必须是合法的 Python 代码, 不要用 markdown 代码块包裹。"""

# 降级代码模板 (LLM 不可用时使用)
# 使用 __DATA_PLACEHOLDER__ 占位符, 避免 .format() 与 f-string 花括号冲突
_DATA_PLACEHOLDER = "__DATA_PLACEHOLDER__"

_FALLBACK_TEMPLATES = {
    "generate_stats": '''\
"""统计结果生成 (降级模板)"""
import statistics

_data = __DATA_PLACEHOLDER__

if isinstance(_data, list) and all(isinstance(x, (int, float)) for x in _data):
    print("=== 描述统计 ===")
    print(f"数据量: {len(_data)}")
    print(f"总和: {sum(_data)}")
    print(f"平均值: {statistics.mean(_data):.4f}")
    print(f"中位数: {statistics.median(_data):.4f}")
    if len(_data) > 1:
        print(f"标准差: {statistics.stdev(_data):.4f}")
        print(f"方差: {statistics.variance(_data):.4f}")
    print(f"最小值: {min(_data)}")
    print(f"最大值: {max(_data)}")
else:
    from collections import Counter
    print("=== 频率统计 ===")
    freq = Counter(_data)
    for item, count in freq.most_common():
        print(f"  {item}: {count}")
''',
    "process_data": '''\
"""数据处理 (降级模板)"""
import json

_data = __DATA_PLACEHOLDER__

print("=== 数据处理结果 ===")
if isinstance(_data, list):
    print(f"原始数据量: {len(_data)}")
    # 去重
    unique_data = list(set(_data)) if all(isinstance(x, (str, int, float)) for x in _data) else _data
    print(f"去重后数据量: {len(unique_data)}")
    print(f"前10条: {unique_data[:10]}")
elif isinstance(_data, dict):
    print(f"字段数: {len(_data)}")
    for k, v in list(_data.items())[:10]:
        print(f"  {k}: {type(v).__name__} = {v}")
else:
    print(f"数据类型: {type(_data).__name__}")
    print(f"值: {_data}")
''',
}


class CodeAgent(BaseRoutedAgent):
    """代码执行型 Agent

    LLM 生成代码 → 安全检查 → Sandbox 执行 → 返回结果

    使用方式:
        # 通过 Runtime 调用
        result = await runtime.run_agent("code_agent", message)

        # 直接调用
        agent = CodeAgent()
        result = await agent.handle_run({
            "task_type": "generate_stats",
            "user_request": "计算这组数据的平均值和标准差",
            "data": [1, 2, 3, 4, 5],
        })

    安全保证:
      1. 代码由 LLM 生成 (非用户直接提供)
      2. 执行前经过 AST 静态分析
      3. 在沙箱中隔离执行
      4. 限制时间 / 资源 / 权限
    """

    def __init__(self) -> None:
        super().__init__(
            description="代码执行Agent, LLM生成代码并安全执行 (分析Excel/处理数据/生成统计)",
            display_name="CodeAgent",
            capabilities=["code_generation", "code_execution", "data_analysis"],
        )
        self._executor = SandboxExecutor()
        self._checker = CodeSecurityChecker()

    def _register_default_actions(self) -> None:
        """注册所有 action handlers (覆盖父类)"""
        super()._register_default_actions()
        self._action_handlers["run"] = self.handle_run
        self._action_handlers["generate_code"] = self.handle_generate_code
        self._action_handlers["execute"] = self.handle_execute
        self._action_handlers["check_security"] = self.handle_check_security

    # ================================================================
    # Action: run — 生成代码 + 安全检查 + 沙箱执行 (主流程)
    # ================================================================

    @action_handler("run")
    async def handle_run(self, payload: Dict[str, Any], ctx: Any = None) -> Dict[str, Any]:
        """主流程: 用户需求 → LLM 生成代码 → 安全检查 → 沙箱执行

        payload:
          - user_request:  用户自然语言需求 (必须)
          - task_type:     任务类型 (generate_stats/process_data/analyze_excel/visualize/execute_code)
          - data:          输入数据 (可选, 传入代码中)
          - timeout:       执行超时秒数 (默认 30)
          - mode:          执行模式 (auto/docker/local)
          - extra_packages: 额外 pip 包
        """
        start = time.time()
        user_request = payload.get("user_request", "")
        task_type = payload.get("task_type", "execute_code")
        data = payload.get("data")
        timeout = payload.get("timeout", 30)
        mode_str = payload.get("mode", "auto")
        extra_packages = payload.get("extra_packages", [])

        if not user_request and not data:
            return {"status": "error", "error": "必须提供 user_request 或 data"}

        # 1. LLM 生成代码
        generated = await self._generate_code(user_request, task_type, data)

        if not generated.get("code"):
            return {
                "status": "error",
                "error": generated.get("error", "LLM 代码生成失败"),
                "duration_ms": round((time.time() - start) * 1000, 2),
            }

        code = generated["code"]
        description = generated.get("description", "")
        required_packages = generated.get("required_packages", [])

        # 合并需要的额外包
        all_packages = list(set(extra_packages + required_packages))

        # 2. 安全检查
        security_report = self._checker.check(code)
        if not security_report.is_allowed:
            return {
                "status": "blocked",
                "error": "代码安全检查未通过, 禁止执行",
                "code": code,
                "description": description,
                "security_report": security_report.to_dict(),
                "duration_ms": round((time.time() - start) * 1000, 2),
            }

        # 3. 沙箱执行
        exec_config = self._build_config(mode_str, timeout, all_packages)
        result = await self._executor.execute(code, exec_config)

        # 4. 返回结果
        return {
            "status": "success" if result.success else "execution_failed",
            "code": code,
            "description": description,
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "execution_mode": result.execution_mode,
            "timed_out": result.timed_out,
            "security_report": result.security_report,
            "duration_ms": round((time.time() - start) * 1000, 2),
            "required_packages": all_packages,
        }

    # ================================================================
    # Action: generate_code — 仅生成代码 (不执行)
    # ================================================================

    @action_handler("generate_code")
    async def handle_generate_code(
        self, payload: Dict[str, Any], ctx: Any = None
    ) -> Dict[str, Any]:
        """仅生成代码, 不执行"""
        user_request = payload.get("user_request", "")
        task_type = payload.get("task_type", "execute_code")
        data = payload.get("data")

        generated = await self._generate_code(user_request, task_type, data)

        if not generated.get("code"):
            return {"status": "error", "error": generated.get("error", "代码生成失败")}

        # 附带安全检查报告
        security_report = self._checker.check(generated["code"])

        return {
            "status": "success",
            "code": generated["code"],
            "description": generated.get("description", ""),
            "expected_output": generated.get("expected_output", ""),
            "required_packages": generated.get("required_packages", []),
            "security_report": security_report.to_dict(),
        }

    # ================================================================
    # Action: execute — 直接执行已有代码
    # ================================================================

    @action_handler("execute")
    async def handle_execute(
        self, payload: Dict[str, Any], ctx: Any = None
    ) -> Dict[str, Any]:
        """直接执行已有代码 (仍经过安全检查)

        payload:
          - code:           Python 代码 (必须)
          - timeout:        超时秒数
          - mode:           执行模式
          - extra_packages: 额外 pip 包
        """
        code = payload.get("code", "")
        if not code:
            return {"status": "error", "error": "必须提供 code"}

        timeout = payload.get("timeout", 30)
        mode_str = payload.get("mode", "auto")
        extra_packages = payload.get("extra_packages", [])

        exec_config = self._build_config(mode_str, timeout, extra_packages)
        result = await self._executor.execute(code, exec_config)

        return {
            "status": "success" if result.success else "execution_failed",
            "output": result.output,
            "error": result.error,
            "exit_code": result.exit_code,
            "execution_mode": result.execution_mode,
            "timed_out": result.timed_out,
            "security_report": result.security_report,
            "security_blocked": result.security_blocked,
        }

    # ================================================================
    # Action: check_security — 仅检查代码安全性
    # ================================================================

    @action_handler("check_security")
    async def handle_check_security(
        self, payload: Dict[str, Any], ctx: Any = None
    ) -> Dict[str, Any]:
        """检查代码安全性, 不执行"""
        code = payload.get("code", "")
        if not code:
            return {"status": "error", "error": "必须提供 code"}

        report = self._checker.check(code)
        return {
            "status": "success",
            "is_allowed": report.is_allowed,
            "security_level": report.level.value,
            "report": report.to_dict(),
        }

    # ================================================================
    # 内部方法
    # ================================================================

    async def _generate_code(
        self,
        user_request: str,
        task_type: str,
        data: Any = None,
    ) -> Dict[str, Any]:
        """调用 LLM 生成代码

        Returns:
            {"code": "...", "description": "...", "required_packages": [...]}
            或 {"error": "..."}
        """
        # 构建用户 prompt
        user_prompt_data = {
            "task_type": task_type,
            "user_request": user_request,
        }
        if data is not None:
            # 序列化数据, 限制大小
            try:
                data_str = json.dumps(data, ensure_ascii=False, default=str)
                if len(data_str) > 10000:
                    data_str = data_str[:10000] + "...(truncated)"
                user_prompt_data["data"] = data_str
            except Exception:
                user_prompt_data["data"] = str(data)[:10000]

        user_prompt = json.dumps(user_prompt_data, ensure_ascii=False, indent=2)

        try:
            raw = await self.call_llm(
                system_prompt=CODE_GENERATION_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=4096,
            )

            # 尝试解析 JSON
            result = self._parse_llm_response(raw)
            if result and result.get("code"):
                logger.info(
                    f"[CodeAgent] LLM 代码生成成功: "
                    f"task_type={task_type}, "
                    f"code_lines={len(result['code'].splitlines())}"
                )
                return result

            # LLM 返回了内容但无法解析为 JSON, 尝试提取代码
            code = self._extract_code_from_text(raw)
            if code:
                logger.info(f"[CodeAgent] 从 LLM 文本中提取代码成功")
                return {
                    "code": code,
                    "description": user_request,
                    "required_packages": [],
                }

            logger.warning(f"[CodeAgent] LLM 响应无法解析为代码")
            return {"error": "LLM 响应无法解析为代码", "raw_response": raw[:500]}

        except Exception as e:
            logger.warning(f"[CodeAgent] LLM 调用失败, 使用降级模板: {e}")
            return self._fallback_generate(task_type, data, user_request)

    @staticmethod
    def _parse_llm_response(raw: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的 JSON"""
        if not raw:
            return None

        # 直接尝试 JSON 解析
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass

        # 尝试从 markdown 代码块中提取 JSON
        json_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except (json.JSONDecodeError, ValueError):
                pass

        # 尝试提取第一个 { 到最后一个 } 的内容
        first_brace = raw.find("{")
        last_brace = raw.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            try:
                return json.loads(raw[first_brace : last_brace + 1])
            except (json.JSONDecodeError, ValueError):
                pass

        return None

    @staticmethod
    def _extract_code_from_text(text: str) -> Optional[str]:
        """从文本中提取 Python 代码块"""
        # ```python ... ``` 或 ``` ... ```
        code_match = re.search(r"```(?:python)?\s*\n(.*?)\n```", text, re.DOTALL)
        if code_match:
            return code_match.group(1).strip()

        # 检查是否整段都是代码 (以 import 或 def 或 print 开头)
        lines = text.strip().splitlines()
        if lines and (lines[0].startswith("import ") or lines[0].startswith("from ")
                       or lines[0].startswith("print(") or lines[0].startswith("#")):
            return text.strip()

        return None

    @staticmethod
    def _fallback_generate(
        task_type: str, data: Any, user_request: str
    ) -> Dict[str, Any]:
        """LLM 不可用时的降级代码生成"""
        template = _FALLBACK_TEMPLATES.get(task_type)

        if template:
            # 使用占位符替换, 避免 .format() 与 f-string 冲突
            code = template.replace(_DATA_PLACEHOLDER, repr(data))
            return {
                "code": code,
                "description": f"降级模板: {task_type}",
                "required_packages": [],
            }

        # 通用降级: 打印数据信息
        code = f'''"""代码执行 (降级模式 - LLM不可用)"""
import json

_data = {data!r}

print("=== 执行结果 ===")
print(f"任务类型: {task_type}")
print(f"用户需求: {user_request}")
print(f"输入数据: {{json.dumps(_data, ensure_ascii=False, default=str)[:1000]}}")

if isinstance(_data, list):
    print(f"数据量: {{len(_data)}}")
    print(f"数据类型: {{type(_data[0]).__name__ if _data else 'empty'}}")
elif isinstance(_data, dict):
    print(f"字段数: {{len(_data)}}")
    print(f"字段列表: {{list(_data.keys())}}")
'''
        return {
            "code": code,
            "description": "降级模式 (LLM 不可用)",
            "required_packages": [],
        }

    @staticmethod
    def _build_config(
        mode_str: str, timeout: int, extra_packages: List[str]
    ) -> ExecutionConfig:
        """构建执行配置"""
        mode_map = {
            "auto": ExecutionMode.AUTO,
            "docker": ExecutionMode.DOCKER,
            "local": ExecutionMode.LOCAL,
        }
        mode = mode_map.get(mode_str, ExecutionMode.AUTO)

        return ExecutionConfig(
            mode=mode,
            timeout=timeout,
            extra_packages=extra_packages if extra_packages else None,
        )
