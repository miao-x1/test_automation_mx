"""
代码执行型 Agent 测试

测试覆盖:
  1. SecurityChecker: 安全检查器 (白名单/黑名单导入/危险调用/属性访问/文件写入/代码长度)
  2. SandboxExecutor: 统一执行器 (安全拦截/本地执行/超时控制/模式选择)
  3. CodeAgent: Agent (action注册/LLM响应解析/降级模板/代码生成+执行)
  4. Agent 注册验证 (definitions.py)
  5. API 路由验证 (code 路由注册)
  6. 端到端流程 (生成→检查→执行)
"""
import asyncio
import json
import os
import sys
import types
from unittest.mock import AsyncMock, MagicMock, patch

# ===== Stub 3rd-party modules (与 test_performance_diagnostic.py 一致) =====
_STUB_MODULES = ["redis", "pymilvus", "neo4j"]
for mod_name in _STUB_MODULES:
    if mod_name not in sys.modules:
        sys.modules[mod_name] = types.ModuleType(mod_name)

_pm = sys.modules.get("pymilvus") or types.ModuleType("pymilvus")
if not hasattr(_pm, "DataType"):
    _pm.DataType = type("DataType", (), {"INT64": "int64", "VARCHAR": "varchar", "FLOAT_VECTOR": "float_vector", "BOOL": "bool"})
    _pm.MilvusClient = type("MilvusClient", (), {"__init__": lambda *a, **kw: None})
    _pm.CollectionSchema = type("CollectionSchema", (), {})
    _pm.FieldSchema = type("FieldSchema", (), {})
sys.modules["pymilvus"] = _pm

_pymysql = types.ModuleType("pymysql")
_pymysql.paramstyle = "format"
_pymysql.install_as_MySQLdb = lambda: None
_pymysql.connect = lambda *a, **kw: None
sys.modules["pymysql"] = _pymysql

_neo = sys.modules.get("neo4j") or types.ModuleType("neo4j")
_neo.GraphDatabase = type("GraphDatabase", (), {"driver": lambda *a, **kw: MagicMock()})
_neo.Driver = type("Driver", (), {"session": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.Session = type("Session", (), {"run": lambda *a, **kw: MagicMock(), "close": lambda *a, **kw: None})
_neo.basic_auth = lambda *a, **kw: MagicMock()
sys.modules["neo4j"] = _neo

# autogen stub
_ag = types.ModuleType("autogen_core")
def _make_class(name):
    return type(name, (), {"__init__": lambda self, *a, **kw: None})
_ag.RoutedAgent = _make_class("RoutedAgent")
_ag.message_handler = lambda *a, **kw: (lambda f: f)
_ag.MessageContext = _make_class("MessageContext")
_ag.AgentId = _make_class("AgentId")
_ag.AgentRuntime = _make_class("AgentRuntime")
_ag.CancellationToken = _make_class("CancellationToken")
_ag.DefaultTopicId = _make_class("DefaultTopicId")
_ag.SingleThreadedAgentRuntime = _make_class("SingleThreadedAgentRuntime")
_ag.ComponentBase = _make_class("ComponentBase")
_ag.default_subscription = lambda *a, **kw: (lambda f: f)
sys.modules["autogen_core"] = _ag

_aac = types.ModuleType("autogen_agentchat")
_aac_base = types.ModuleType("autogen_agentchat.base")
_aac_base.ChatAgent = _make_class("ChatAgent")
_aac_base.Response = _make_class("Response")
_aac_base.TaskResult = _make_class("TaskResult")
_aac_messages = types.ModuleType("autogen_agentchat.messages")
_aac_messages.TextMessage = _make_class("TextMessage")
_aac_messages.BaseChatMessage = _make_class("BaseChatMessage")
_aac_messages.BaseAgentEvent = _make_class("BaseAgentEvent")
_aac_teams = types.ModuleType("autogen_agentchat.teams")
_aac_teams.DiGraphBuilder = _make_class("DiGraphBuilder")
_aac_teams.GraphFlow = _make_class("GraphFlow")
_aac.base = _aac_base
_aac.messages = _aac_messages
_aac.teams = _aac_teams
sys.modules["autogen_agentchat"] = _aac
sys.modules["autogen_agentchat.base"] = _aac_base
sys.modules["autogen_agentchat.messages"] = _aac_messages
sys.modules["autogen_agentchat.teams"] = _aac_teams

_sse = types.ModuleType("sse_starlette")
_sse_sse = types.ModuleType("sse_starlette.sse")
_sse_sse.EventSourceResponse = type("EventSourceResponse", (), {"__init__": lambda *a, **kw: None})
sys.modules["sse_starlette"] = _sse
sys.modules["sse_starlette.sse"] = _sse_sse


# ===== 测试工具 =====
RESULTS = []

def record(name: str, ok: bool, detail: str = ""):
    status = "[PASS]" if ok else "[FAIL]"
    msg = f"{status} {name}"
    if detail and not ok:
        msg += f" | {detail}"
    print(msg)
    RESULTS.append((name, ok))


# ================================================================== #
#  1. SecurityChecker 测试                                            #
# ================================================================== #

def test_security_checker():
    """测试代码安全检查器"""
    print("\n=== 1. SecurityChecker 测试 ===")

    from app.sandbox.security import (
        CodeSecurityChecker,
        SecurityLevel,
        SecurityReport,
        SecurityPolicy,
    )

    checker = CodeSecurityChecker()

    # 1.1 安全代码 — 基本数学计算
    safe_code = '''
import math
import statistics
import json

data = [1, 2, 3, 4, 5]
avg = statistics.mean(data)
print(f"Average: {avg}")
print(f"Pi: {math.pi}")
'''
    report = checker.check(safe_code)
    record("1.1 安全代码 - 基本数学计算", report.level == SecurityLevel.SAFE,
           f"level={report.level}, issues={report.issues}")

    # 1.2 安全代码 — pandas/numpy
    safe_code2 = '''
import pandas as pd
import numpy as np

df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
print(df.describe())
print(np.mean(df["a"]))
'''
    report2 = checker.check(safe_code2)
    record("1.2 安全代码 - pandas/numpy", report2.level == SecurityLevel.SAFE,
           f"level={report2.level}, issues={report2.issues}")

    # 1.3 危险代码 — 导入 os
    dangerous_os = "import os\nos.system('rm -rf /')"
    report3 = checker.check(dangerous_os)
    record("1.3 危险代码 - 导入os", not report3.is_allowed,
           f"level={report3.level}, blocked={report3.blocked_imports}")

    # 1.4 危险代码 — 导入 subprocess
    dangerous_sub = "import subprocess\nsubprocess.Popen(['ls'])"
    report4 = checker.check(dangerous_sub)
    record("1.4 危险代码 - 导入subprocess", not report4.is_allowed,
           f"level={report4.level}, blocked={report4.blocked_imports}")

    # 1.5 危险代码 — 导入 socket
    dangerous_sock = "import socket\ns = socket.socket()"
    report5 = checker.check(dangerous_sock)
    record("1.5 危险代码 - 导入socket", not report5.is_allowed,
           f"level={report5.level}, blocked={report5.blocked_imports}")

    # 1.6 危险代码 — eval 调用
    dangerous_eval = "result = eval('1+1')"
    report6 = checker.check(dangerous_eval)
    record("1.6 危险代码 - eval调用", not report6.is_allowed,
           f"level={report6.level}")

    # 1.7 危险代码 — exec 调用
    dangerous_exec = "exec('print(1)')"
    report7 = checker.check(dangerous_exec)
    record("1.7 危险代码 - exec调用", not report7.is_allowed,
           f"level={report7.level}")

    # 1.8 危险代码 — __builtins__ 访问
    dangerous_builtins = "x = obj.__builtins__"
    report8 = checker.check(dangerous_builtins)
    record("1.8 危险代码 - __builtins__访问", not report8.is_allowed,
           f"level={report8.level}")

    # 1.9 危险代码 — __subclasses__ 访问
    dangerous_subclasses = "subs = object.__subclasses__()"
    report9 = checker.check(dangerous_subclasses)
    record("1.9 危险代码 - __subclasses__访问", not report9.is_allowed,
           f"level={report9.level}")

    # 1.10 危险代码 — 文件写入
    dangerous_write = "f = open('test.txt', 'w')\nf.write('hello')"
    report10 = checker.check(dangerous_write)
    record("1.10 危险代码 - 文件写入", not report10.is_allowed,
           f"level={report10.level}")

    # 1.11 安全代码 — 文件只读
    safe_read = "f = open('data.csv', 'r')\ndata = f.read()\nf.close()"
    report11 = checker.check(safe_read)
    record("1.11 安全代码 - 文件只读open", report11.is_allowed,
           f"level={report11.level}")

    # 1.12 语法错误
    syntax_error = "import json\nprint('hello'"
    report12 = checker.check(syntax_error)
    record("1.12 语法错误检测", not report12.is_allowed and not report12.ast_valid,
           f"level={report12.level}, ast_valid={report12.ast_valid}")

    # 1.13 代码过长
    long_code = "\n".join([f"x_{i} = {i}" for i in range(600)])
    report13 = checker.check(long_code)
    record("1.13 代码过长检测", not report13.is_allowed,
           f"level={report13.level}, lines={report13.code_lines}")

    # 1.14 SecurityPolicy 白名单检查
    record("1.14 白名单包含pandas", "pandas" in SecurityPolicy.ALLOWED_MODULES)
    record("1.15 黑名单包含os", "os" in SecurityPolicy.BLOCKED_MODULES)
    record("1.16 is_module_allowed(os)=False", SecurityPolicy.is_module_allowed("os") is False)
    record("1.17 is_module_allowed(pandas)=True", SecurityPolicy.is_module_allowed("pandas") is True)

    # 1.18 SecurityReport.to_dict
    report_dict = report.to_dict()
    record("1.18 SecurityReport.to_dict", "level" in report_dict and "is_allowed" in report_dict,
           f"keys={list(report_dict.keys())}")


# ================================================================== #
#  2. SandboxExecutor 测试                                            #
# ================================================================== #

def test_sandbox_executor():
    """测试统一沙箱执行器"""
    print("\n=== 2. SandboxExecutor 测试 ===")

    from app.sandbox.executor import (
        SandboxExecutor,
        ExecutionConfig,
        ExecutionMode,
        ExecutionResult,
    )

    # 2.1 安全拦截 — 危险代码不执行
    async def test_security_block():
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        result = await executor.execute("import os\nos.system('ls')")

        ok = result.security_blocked and not result.success
        record("2.1 安全拦截 - 危险代码不执行", ok,
               f"blocked={result.security_blocked}, success={result.success}")
        record("2.2 安全拦截 - 返回安全报告", result.security_report is not None,
               f"report={result.security_report is not None}")

    asyncio.run(test_security_block())

    # 2.3 本地执行 — 安全代码
    async def test_local_execution():
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        code = "print('Hello from sandbox!')\nimport math\nprint(f'Pi={math.pi:.2f}')"
        result = await executor.execute(code)

        record("2.3 本地执行 - 成功执行", result.success,
               f"success={result.success}, output={result.output[:100]}, error={result.error[:200]}")
        record("2.4 本地执行 - 输出包含Hello", "Hello from sandbox" in result.output,
               f"output={result.output[:100]}")
        record("2.5 本地执行 - 执行模式为local", result.execution_mode == "local",
               f"mode={result.execution_mode}")

    asyncio.run(test_local_execution())

    # 2.6 超时控制
    async def test_timeout():
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        config = ExecutionConfig(mode=ExecutionMode.LOCAL, timeout=2)
        # 死循环代码
        code = "while True:\n    pass"
        result = await executor.execute(code, config)

        record("2.6 超时控制 - 超时终止", result.timed_out,
               f"timed_out={result.timed_out}, error={result.error[:100]}")

    asyncio.run(test_timeout())

    # 2.7 执行配置
    config = ExecutionConfig(timeout=60, memory_limit="512m", cpu_limit="2.0")
    config_dict = config.to_dict()
    record("2.7 ExecutionConfig.to_dict", config_dict["timeout"] == 60 and config_dict["memory_limit"] == "512m",
           f"config={config_dict}")

    # 2.8 ExecutionResult.to_dict
    result = ExecutionResult(success=True, output="test", execution_mode="local")
    result_dict = result.to_dict()
    record("2.8 ExecutionResult.to_dict", result_dict["success"] and result_dict["execution_mode"] == "local",
           f"keys={list(result_dict.keys())}")

    # 2.9 执行数学计算
    async def test_math_execution():
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        code = """
import statistics
data = [10, 20, 30, 40, 50]
print(f"Mean: {statistics.mean(data)}")
print(f"Median: {statistics.median(data)}")
print(f"Stdev: {statistics.stdev(data):.2f}")
"""
        result = await executor.execute(code)
        record("2.9 数学计算执行", result.success and "Mean: 30" in result.output,
               f"output={result.output[:200]}")

    asyncio.run(test_math_execution())

    # 2.10 可用性检查
    async def test_availability():
        executor = SandboxExecutor()
        avail = await executor.check_availability()
        record("2.10 可用性检查 - local始终可用", avail["local"] is True,
               f"avail={avail}")

    asyncio.run(test_availability())


# ================================================================== #
#  3. CodeAgent 测试                                                 #
# ================================================================== #

def test_code_agent():
    """测试 CodeAgent"""
    print("\n=== 3. CodeAgent 测试 ===")

    from app.domains.code.agent import CodeAgent, CODE_GENERATION_PROMPT

    # 3.1 Agent 实例化
    try:
        agent = CodeAgent()
        record("3.1 CodeAgent实例化", True)
    except Exception as e:
        record("3.1 CodeAgent实例化", False, str(e))
        return

    # 3.2 Action handler 注册
    record("3.2 Action: run注册", "run" in agent._action_handlers,
           f"handlers={list(agent._action_handlers.keys())}")
    record("3.3 Action: generate_code注册", "generate_code" in agent._action_handlers)
    record("3.4 Action: execute注册", "execute" in agent._action_handlers)
    record("3.5 Action: check_security注册", "check_security" in agent._action_handlers)

    # 3.3 LLM 响应解析 — 纯JSON
    raw_json = json.dumps({
        "code": "print('hello')",
        "description": "测试代码",
        "required_packages": [],
    })
    parsed = CodeAgent._parse_llm_response(raw_json)
    record("3.6 LLM响应解析 - 纯JSON", parsed is not None and parsed.get("code") == "print('hello')",
           f"parsed={parsed}")

    # 3.4 LLM 响应解析 — markdown代码块中的JSON
    raw_md = '''这是生成的代码:
```json
{"code": "print(42)", "description": "输出42", "required_packages": []}
```
'''
    parsed_md = CodeAgent._parse_llm_response(raw_md)
    record("3.7 LLM响应解析 - markdown JSON", parsed_md is not None and parsed_md.get("code") == "print(42)",
           f"parsed={parsed_md}")

    # 3.5 LLM 响应解析 — 花括号提取
    raw_text = '好的，这是结果 {"code": "x=1", "description": "赋值"} 请使用'
    parsed_text = CodeAgent._parse_llm_response(raw_text)
    record("3.8 LLM响应解析 - 花括号提取", parsed_text is not None and parsed_text.get("code") == "x=1",
           f"parsed={parsed_text}")

    # 3.6 代码提取 — python代码块
    text_with_code = '''这里是一些说明:
```python
import math
print(math.sqrt(16))
```
'''
    code = CodeAgent._extract_code_from_text(text_with_code)
    record("3.9 代码提取 - python代码块", code is not None and "import math" in code,
           f"code={code}")

    # 3.7 代码提取 — 纯代码文本
    pure_code = "import json\nprint(json.dumps({'a': 1}))"
    code2 = CodeAgent._extract_code_from_text(pure_code)
    record("3.10 代码提取 - 纯代码", code2 is not None and "import json" in code2,
           f"code={code2}")

    # 3.8 降级模板 — generate_stats
    fallback = CodeAgent._fallback_generate("generate_stats", [1, 2, 3, 4, 5], "计算统计")
    record("3.11 降级模板 - generate_stats", fallback.get("code") is not None and "statistics" in fallback["code"],
           f"code_preview={fallback['code'][:80]}")

    # 3.9 降级模板 — process_data
    fallback2 = CodeAgent._fallback_generate("process_data", [1, 2, 3], "处理数据")
    record("3.12 降级模板 - process_data", fallback2.get("code") is not None and "数据处理" in fallback2["code"],
           f"code_preview={fallback2['code'][:80]}")

    # 3.10 降级模板 — 通用
    fallback3 = CodeAgent._fallback_generate("unknown_type", {"key": "value"}, "测试")
    record("3.13 降级模板 - 通用", fallback3.get("code") is not None and "降级" in fallback3["code"],
           f"code_preview={fallback3['code'][:80]}")

    # 3.11 构建执行配置
    config = CodeAgent._build_config("local", 60, ["pandas"])
    record("3.14 构建配置 - local模式", config.mode.value == "local" and config.timeout == 60,
           f"mode={config.mode}, timeout={config.timeout}")

    config2 = CodeAgent._build_config("docker", 30, [])
    record("3.15 构建配置 - docker模式", config2.mode.value == "docker",
           f"mode={config2.mode}")

    # 3.12 check_security action — 安全代码
    async def test_check_security_safe():
        result = await agent.handle_check_security({
            "code": "import math\nprint(math.pi)",
        })
        record("3.16 check_security - 安全代码", result["status"] == "success" and result["is_allowed"],
               f"status={result['status']}, allowed={result.get('is_allowed')}")

    asyncio.run(test_check_security_safe())

    # 3.13 check_security action — 危险代码
    async def test_check_security_dangerous():
        result = await agent.handle_check_security({
            "code": "import os\nos.system('rm -rf /')",
        })
        record("3.17 check_security - 危险代码", result["status"] == "success" and not result["is_allowed"],
               f"status={result['status']}, allowed={result.get('is_allowed')}")

    asyncio.run(test_check_security_dangerous())

    # 3.14 execute action — 安全代码执行
    async def test_execute_safe():
        result = await agent.handle_execute({
            "code": "print('test output')\nimport json\nprint(json.dumps({'result': 42}))",
            "timeout": 10,
            "mode": "local",
        })
        record("3.18 execute action - 安全代码执行", result["status"] == "success",
               f"status={result['status']}, output={result.get('output', '')[:100]}, error={result.get('error', '')[:200]}")
        record("3.19 execute action - 输出包含test output", "test output" in result.get("output", ""),
               f"output={result.get('output', '')[:100]}")

    asyncio.run(test_execute_safe())

    # 3.15 execute action — 危险代码拦截
    async def test_execute_dangerous():
        result = await agent.handle_execute({
            "code": "import subprocess\nsubprocess.Popen(['ls'])",
            "timeout": 10,
            "mode": "local",
        })
        record("3.20 execute action - 危险代码拦截", result.get("security_blocked") is True,
               f"blocked={result.get('security_blocked')}, status={result.get('status')}")

    asyncio.run(test_execute_dangerous())

    # 3.16 execute action — 空代码
    async def test_execute_empty():
        result = await agent.handle_execute({"code": ""})
        record("3.21 execute action - 空代码报错", result["status"] == "error",
               f"status={result['status']}")

    asyncio.run(test_execute_empty())

    # 3.17 run action — 降级模式 (LLM不可用, 使用模板)
    async def test_run_fallback():
        result = await agent.handle_run({
            "user_request": "计算平均值和标准差",
            "task_type": "generate_stats",
            "data": [10, 20, 30, 40, 50],
            "timeout": 10,
            "mode": "local",
        })
        # LLM 不可用时会降级到模板, 仍然能执行
        record("3.22 run action - 降级模式执行", result["status"] in ("success", "execution_failed"),
               f"status={result['status']}, error={result.get('error', '')[:200]}")
        record("3.23 run action - 包含生成的代码", "code" in result and len(result["code"]) > 0,
               f"code_preview={result.get('code', '')[:80]}")

    asyncio.run(test_run_fallback())

    # 3.18 run action — 无需求无数据
    async def test_run_empty():
        result = await agent.handle_run({
            "user_request": "",
            "task_type": "execute_code",
        })
        record("3.24 run action - 空需求报错", result["status"] == "error",
               f"status={result['status']}")

    asyncio.run(test_run_empty())

    # 3.19 System Prompt 验证
    record("3.25 System Prompt 包含白名单约束", "白名单" in CODE_GENERATION_PROMPT)
    record("3.26 System Prompt 包含黑名单约束", "黑名单" in CODE_GENERATION_PROMPT)
    record("3.27 System Prompt 包含JSON输出格式", "JSON" in CODE_GENERATION_PROMPT)


# ================================================================== #
#  4. Agent 注册验证                                                  #
# ================================================================== #

def test_agent_registration():
    """测试 Agent 注册"""
    print("\n=== 4. Agent 注册验证 ===")

    # 4.1 definitions.py 中注册了 code_agent
    try:
        # 直接读取文件检查
        import importlib
        defs_path = os.path.join(
            os.path.dirname(__file__), "..",
            "app", "agents", "factory", "definitions.py"
        )
        defs_path = os.path.abspath(defs_path)

        with open(defs_path, "r", encoding="utf-8") as f:
            content = f.read()

        record("4.1 definitions.py 包含code_agent", "code_agent" in content)
        record("4.2 definitions.py 包含CodeAgent类", "CodeAgent" in content)
        record("4.3 definitions.py 包含domains.code.agent", "app.domains.code.agent" in content)
        record("4.4 definitions.py 包含code_generation能力", "code_generation" in content)
        record("4.5 definitions.py 包含code_execution能力", "code_execution" in content)
    except Exception as e:
        record("4.1 definitions.py 包含code_agent", False, str(e))


# ================================================================== #
#  5. API 路由验证                                                    #
# ================================================================== #

def test_api_routes():
    """测试 API 路由"""
    print("\n=== 5. API 路由验证 ===")

    # 5.1 code.py 路由文件存在且包含端点
    try:
        api_path = os.path.join(
            os.path.dirname(__file__), "..",
            "app", "api", "code.py"
        )
        api_path = os.path.abspath(api_path)

        with open(api_path, "r", encoding="utf-8") as f:
            content = f.read()

        record("5.1 API包含 /run 端点", "/run" in content)
        record("5.2 API包含 /generate 端点", "/generate" in content)
        record("5.3 API包含 /execute 端点", "/execute" in content)
        record("5.4 API包含 /check-security 端点", "check-security" in content)
        record("5.5 API包含 /sandbox/status 端点", "sandbox/status" in content)
    except Exception as e:
        record("5.1 API包含 /run 端点", False, str(e))

    # 5.2 __init__.py 注册了 code_router
    try:
        init_path = os.path.join(
            os.path.dirname(__file__), "..",
            "app", "api", "__init__.py"
        )
        init_path = os.path.abspath(init_path)

        with open(init_path, "r", encoding="utf-8") as f:
            content = f.read()

        record("5.6 __init__.py 导入code_router", "code_router" in content)
        record("5.7 __init__.py 注册/code前缀", 'prefix="/code"' in content)
    except Exception as e:
        record("5.6 __init__.py 导入code_router", False, str(e))


# ================================================================== #
#  6. 端到端流程测试                                                  #
# ================================================================== #

def test_end_to_end():
    """端到端流程: 生成 → 检查 → 执行"""
    print("\n=== 6. 端到端流程测试 ===")

    from app.domains.code.agent import CodeAgent
    from app.sandbox.security import CodeSecurityChecker

    agent = CodeAgent()
    checker = CodeSecurityChecker()

    # 6.1 完整流程: 数据统计 (使用降级模板确保一致性)
    async def test_e2e_stats():
        # Step 1: 生成代码 (使用降级模板, 避免 LLM 响应不一致)
        generated = CodeAgent._fallback_generate(
            "generate_stats", [10, 20, 30, 40, 50], "计算数据的平均值、中位数和标准差"
        )
        record("6.1 E2E - 代码生成", generated.get("code") is not None,
               f"has_code={'code' in generated}")

        if not generated.get("code"):
            return

        code = generated["code"]

        # Step 2: 安全检查
        report = checker.check(code)
        record("6.2 E2E - 安全检查通过", report.is_allowed,
               f"level={report.level}, issues={len(report.issues)}, issues_detail={report.issues[:3]}")

        if not report.is_allowed:
            return

        # Step 3: 沙箱执行
        from app.sandbox.executor import SandboxExecutor, ExecutionConfig, ExecutionMode
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        config = ExecutionConfig(mode=ExecutionMode.LOCAL, timeout=10)
        result = await executor.execute(code, config)

        record("6.3 E2E - 沙箱执行成功", result.success,
               f"success={result.success}, output={result.output[:200]}, error={result.error[:200]}")
        record("6.4 E2E - 输出包含统计结果", "Mean" in result.output or "平均值" in result.output or "统计" in result.output,
               f"output={result.output[:200]}")

    asyncio.run(test_e2e_stats())

    # 6.2 完整流程: 数据处理
    async def test_e2e_process():
        generated = await agent._generate_code(
            "处理这组数据, 去重并统计",
            "process_data",
            ["apple", "banana", "apple", "cherry", "banana", "apple"],
        )
        record("6.5 E2E - 数据处理代码生成", generated.get("code") is not None)

        if not generated.get("code"):
            return

        code = generated["code"]
        report = checker.check(code)
        record("6.6 E2E - 数据处理安全检查", report.is_allowed,
               f"level={report.level}")

        if not report.is_allowed:
            return

        from app.sandbox.executor import SandboxExecutor, ExecutionConfig, ExecutionMode
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        result = await executor.execute(code, ExecutionConfig(mode=ExecutionMode.LOCAL, timeout=10))
        record("6.7 E2E - 数据处理执行", result.success,
               f"output={result.output[:200]}")

    asyncio.run(test_e2e_process())

    # 6.3 安全拦截端到端
    async def test_e2e_blocked():
        # 模拟 LLM 生成危险代码 (直接构造)
        dangerous_code = "import os\nos.system('whoami')"
        report = checker.check(dangerous_code)
        record("6.8 E2E - 危险代码被拦截", not report.is_allowed,
               f"level={report.level}")

        if report.is_allowed:
            return

        from app.sandbox.executor import SandboxExecutor, ExecutionConfig, ExecutionMode
        executor = SandboxExecutor(mode=ExecutionMode.LOCAL)
        result = await executor.execute(dangerous_code, ExecutionConfig(mode=ExecutionMode.LOCAL))
        record("6.9 E2E - 危险代码未执行", result.security_blocked and not result.success,
               f"blocked={result.security_blocked}")

    asyncio.run(test_e2e_blocked())


# ================================================================== #
#  7. Sandbox 模块完整性测试                                          #
# ================================================================== #

def test_sandbox_modules():
    """测试 Sandbox 模块完整性"""
    print("\n=== 7. Sandbox 模块完整性 ===")

    # 7.1 模块导入
    try:
        from app.sandbox.security import (
            CodeSecurityChecker,
            SecurityReport,
            SecurityLevel,
            SecurityPolicy,
        )
        record("7.1 security.py 导入", True)
    except ImportError as e:
        record("7.1 security.py 导入", False, str(e))

    try:
        from app.sandbox.docker_sandbox import DockerSandbox, DockerExecutionResult
        record("7.2 docker_sandbox.py 导入", True)
    except ImportError as e:
        record("7.2 docker_sandbox.py 导入", False, str(e))

    try:
        from app.sandbox.local_sandbox import LocalSandbox, LocalExecutionResult
        record("7.3 local_sandbox.py 导入", True)
    except ImportError as e:
        record("7.3 local_sandbox.py 导入", False, str(e))

    try:
        from app.sandbox.executor import (
            SandboxExecutor,
            ExecutionConfig,
            ExecutionMode,
            ExecutionResult,
        )
        record("7.4 executor.py 导入", True)
    except ImportError as e:
        record("7.4 executor.py 导入", False, str(e))

    # 7.5 __init__.py 导入
    try:
        from app.sandbox import (
            CodeSecurityChecker,
            DockerSandbox,
            LocalSandbox,
            SandboxExecutor,
            ExecutionResult,
            ExecutionConfig,
        )
        record("7.5 __init__.py 统一导入", True)
    except ImportError as e:
        record("7.5 __init__.py 统一导入", False, str(e))

    # 7.6 DockerSandbox 命令构建
    try:
        sandbox = DockerSandbox()
        cmd = sandbox._build_docker_command(
            script_path="/tmp/test.py",
            container_name="test-container",
            timeout=30,
            memory_limit="256m",
            cpu_limit="1.0",
            extra_packages=None,
        )
        record("7.6 Docker命令包含--network none", "--network" in cmd and "none" in cmd,
               f"cmd={cmd[:100]}")
        record("7.7 Docker命令包含--read-only", "--read-only" in cmd)
        record("7.8 Docker命令包含--user 65534", "65534:65534" in cmd)
        record("7.9 Docker命令包含--memory", "--memory" in cmd and "256m" in cmd)
        record("7.10 Docker命令包含--cpus", "--cpus" in cmd)
    except Exception as e:
        record("7.6 Docker命令构建", False, str(e))

    # 7.7 LocalSandbox 环境清理
    try:
        env = LocalSandbox._build_clean_env({"CUSTOM_VAR": "test"})
        record("7.11 LocalSandbox环境清理 - 保留CUSTOM_VAR", env.get("CUSTOM_VAR") == "test")
        record("7.12 LocalSandbox环境清理 - 设置PYTHONUNBUFFERED", env.get("PYTHONUNBUFFERED") == "1")
        record("7.13 LocalSandbox环境清理 - 设置PYTHONDONTWRITEBYTECODE",
               env.get("PYTHONDONTWRITEBYTECODE") == "1")
    except Exception as e:
        record("7.11 LocalSandbox环境清理", False, str(e))


# ================================================================== #
#  主函数                                                            #
# ================================================================== #

def main():
    print("=" * 60)
    print("  代码执行型 Agent 测试")
    print("=" * 60)

    test_security_checker()
    test_sandbox_executor()
    test_code_agent()
    test_agent_registration()
    test_api_routes()
    test_end_to_end()
    test_sandbox_modules()

    # 汇总
    print("\n" + "=" * 60)
    total = len(RESULTS)
    passed = sum(1 for _, ok in RESULTS if ok)
    failed = total - passed
    print(f"  总计: {total}  通过: {passed}  失败: {failed}")
    print("=" * 60)

    if failed > 0:
        print("\n失败用例:")
        for name, ok in RESULTS:
            if not ok:
                print(f"  [FAIL] {name}")
        sys.exit(1)
    else:
        print("\n全部测试通过!")


if __name__ == "__main__":
    main()
