# Agent 架构冗余代码清理计划

## 概述

项目存在三代 Agent 架构并行的问题，产生大量重叠和冗余代码。前一轮清理已完成模型层、服务层、API 层和检索层的统一。本计划聚焦于 Agent 架构本身的冗余清理。

### 三代架构现状

| 代 | 目录 | 文件数 | 外部引用 | 状态 |
|----|------|--------|----------|------|
| Gen1 | `app/agent/` | ~60+ | 100 文件 | 活跃骨干，含死代码 |
| Gen2 | `app/agent_runtime/` | 9 | 3 文件 | 薄包装层，可移除 |
| Gen3 | `app/runtime/` + `app/agents/` | ~30 | 22 文件 | 新架构目标 |

### 关键发现

**死代码修正**：初始分析中 22 个"死代码"文件，经逐文件验证后有 **8 个仍被活跃引用**，不可删除：
- `scheduler_agent.py` → `main.py:47`, `api/schedule.py` 多处引用
- `task_executor.py` → `scheduler_agent.py:197`, `api/schedule.py:465`
- `script_executor.py` → `api/script_upload.py:15`
- `script_validator.py` → `api/script_upload.py:14`
- `script_parser.py` → `api/script_upload.py:13`
- `case/api_extraction_agent.py` → `api/workflow.py:452`
- `case/case_generator_v2.py` → `services/knowledge/case_generate_service.py:219`
- `case/retriever_agent.py` → `services/knowledge/case_generate_service.py:200`

**Gen2 消费者**：共 3 个（非 2 个）：
- `api/agent_runtime.py` — 导入 `get_task_orchestrator`, `get_agent_runtime`, `get_agent_factory`, `list_workflows`
- `api/testcase_generation.py` — 导入 `get_task_orchestrator`（行 19, 108, 119, 519, 520）
- `agent/testcase/testcase_generator_agent.py` — 惰性导入 `get_agent_factory`（行 226）

**Gen3 缺失注册**：Gen3 的 `agent_registry.py` 和 `agents/factory/definitions.py` 均缺少 testcase 模块的 5 个 Agent 定义，需在移除 Gen2 前补充。

---

## 阶段 1：Gen1 死代码删除（零风险）

### 1A. 删除根级死代码（4 个文件）

删除以下文件：
- `app/agent/graph_search_agent.py`
- `app/agent/mock_agent.py`
- `app/agent/router_agent.py`
- `app/agent/task_orchestrator.py`

### 1B. 清理 `agent/__init__.py`

`task_orchestrator.py` 仅被 `agent/__init__.py` 第 87-91 行重导出，且 `LegacyTaskOrchestrator`/`PipelineStep`/`TaskContext` 无任何外部消费者。

操作：
1. 删除 `from app.agent.task_orchestrator import (TaskOrchestrator as LegacyTaskOrchestrator, PipelineStep, TaskContext)`
2. 从 `__all__` 移除 `"LegacyTaskOrchestrator"`, `"PipelineStep"`, `"TaskContext"`

### 1C. 删除 case/ 子目录死代码（10 个文件）

删除以下文件：
- `app/agent/case/context_enricher_agent.py`
- `app/agent/case/context_splitter.py`
- `app/agent/case/execution_runner_agent.py`
- `app/agent/case/framework_adapter_agent.py`
- `app/agent/case/script_generator_agent.py`
- `app/agent/case/image_parser.py`
- `app/agent/case/storage_agent.py`
- `app/agent/case/video_parser.py`
- `app/agent/case/schema_parser.py`
- `app/agent/case/swagger_parser.py`

### 1D. 清理 `case/__init__.py`

删除对已删文件的 import 和 `__all__` 条目：
- `from app.agent.case.storage_agent import StorageAgent`
- `from app.agent.case.image_parser import ImageParserAgent`
- `from app.agent.case.video_parser import VideoParserAgent`
- `from app.agent.case.schema_parser import SchemaParserAgent`
- `from app.agent.case.swagger_parser import SwaggerParserAgent`

### 1E. 更新 Gen3 `agent_registry.py`

删除 `AGENT_DEFINITIONS` 中指向已删文件的 8 个 `AgentDefinition` 条目：
- `graph_search_agent` (module_path: `app.agent.graph_search_agent`)
- `mock_agent` (module_path: `app.agent.mock_agent`)
- `router_agent` (module_path: `app.agent.router_agent`)
- `image_parser` (module_path: `app.agent.case.image_parser`)
- `video_parser` (module_path: `app.agent.case.video_parser`)
- `schema_parser` (module_path: `app.agent.case.schema_parser`)
- `swagger_parser` (module_path: `app.agent.case.swagger_parser`)
- `case_storage` (module_path: `app.agent.case.storage_agent`)

### 1F. 更新 Gen3 `agents/factory/definitions.py`

同步删除上述 8 个 agent 在 `definitions.py` 中的注册条目。

### 阶段 1 验证

1. Grep 搜索 `graph_search_agent|mock_agent|router_agent|LegacyTaskOrchestrator|PipelineStep|context_enricher|context_splitter|execution_runner|framework_adapter|script_generator_agent|image_parser|storage_agent|video_parser|schema_parser|swagger_parser` → 应零结果
2. 执行 `python -c "from app.agent import *; from app.agent.case import *; print('OK')"` 确认包导入正常

---

## 阶段 2：Gen2（agent_runtime/）移除

### 2A. 在 Gen3 注册表中补充 testcase Agent 定义

在 `app/runtime/agent_registry.py` 的 `AGENT_DEFINITIONS` 列表中添加 5 个条目：

```python
AgentDefinition(
    agent_type="requirement_analysis_agent",
    module_path="app.agent.testcase.requirement_analysis_agent",
    class_name="RequirementAnalysisAgent",
    display_name="需求解析Agent(V2)",
    capabilities=["requirement_parse"],
),
AgentDefinition(
    agent_type="test_point_analysis_agent",
    module_path="app.agent.testcase.test_point_analysis_agent",
    class_name="TestPointAnalysisAgent",
    display_name="测试点分析Agent",
    capabilities=["case_generate"],
),
AgentDefinition(
    agent_type="testcase_generator_agent",
    module_path="app.agent.testcase.testcase_generator_agent",
    class_name="TestCaseGeneratorAgent",
    display_name="用例生成Agent(V3)",
    capabilities=["case_generate", "rag_retrieve"],
),
AgentDefinition(
    agent_type="testcase_review_agent",
    module_path="app.agent.testcase.testcase_review_agent",
    class_name="TestCaseReviewAgent",
    display_name="用例审核Agent(V2)",
    capabilities=["feedback"],
),
AgentDefinition(
    agent_type="knowledge_sync_agent",
    module_path="app.agent.testcase.knowledge_sync_agent",
    class_name="KnowledgeSyncAgent",
    display_name="数据同步Agent",
    capabilities=["knowledge_update"],
),
```

同步在 `app/agents/factory/definitions.py` 中添加对应条目。

### 2B. 迁移 `api/agent_runtime.py` 到 Gen3

**Gen2 → Gen3 函数映射**：

| Gen2 调用 | Gen3 替代 |
|----------|----------|
| `get_task_orchestrator().run(requirement, task_id, workflow_name)` | `get_task_runtime().execute_pipeline(steps=[...], user_id, session_id)` |
| `get_task_orchestrator().run_stream(...)` | `get_task_runtime().execute_pipeline_sse(steps=[...])` |
| `get_task_orchestrator().get_session_events(sid)` | 查询 `AgentExecutionLog` 数据库表 |
| `get_agent_runtime().get_session(sid)` | 查询 `AgentExecutionLog` 数据库表（已有回退逻辑） |
| `get_agent_runtime().get_stats()` | `get_task_runtime().get_stats()` |
| `get_agent_runtime().list_sessions(uid)` | `get_task_runtime().list_sessions(uid)` |
| `get_agent_factory().list_agents()` | `get_task_runtime().list_agents()` |
| `list_workflows()` | 返回静态工作流定义列表 |

**修改步骤**：

1. 替换 import：
   ```python
   # 删除
   from app.agent_runtime import (get_task_orchestrator, get_agent_runtime, get_agent_factory, list_workflows)
   # 替换为
   from app.runtime import get_task_runtime
   ```

2. `POST /task/run` — 根据 `task_type` 构建 pipeline 步骤列表，调用 `get_task_runtime().execute_pipeline(steps, user_id, session_id)`

3. `POST /task/run/stream` — 调用 `get_task_runtime().execute_pipeline_sse(steps, user_id, session_id)`

4. `GET /task/{sid}/stream` — 已查数据库，无需改动核心逻辑

5. `GET /task/{sid}/logs` — 已查数据库，无需改动

6. `GET /task/{sid}/status` — 已有数据库回退逻辑，删除 `get_agent_runtime()` 调用路径

7. `GET /agents` — 替换为 `await get_task_runtime().list_agents()`

8. `GET /workflows` — 返回静态定义的工作流列表

9. `GET /runtime/stats` — 替换为 `get_task_runtime().get_stats()`

10. `GET /sessions` — 替换为 `await get_task_runtime().list_sessions(uid)`

11. `GET /sessions/{sid}/events` — 查询 `AgentExecutionLog` 数据库表

### 2C. 迁移 `api/testcase_generation.py` 到 Gen3

**修改步骤**：

1. 替换 import（行 19）：
   ```python
   # 删除
   from app.agent_runtime.orchestrator import get_task_orchestrator
   # 替换为
   from app.runtime import get_task_runtime
   ```

2. `generate_test_cases` 函数（行 98-164）：将 `orchestrator.run(requirement=..., workflow_name="testcase_generation")` 替换为：
   ```python
   task_runtime = get_task_runtime()
   result = await task_runtime.execute_pipeline(
       steps=[
           {"agent_type": "requirement_analysis_agent", "action": "execute",
            "payload": {"requirement": requirement_text}, "output_key": "requirement_analysis"},
           {"agent_type": "test_point_analysis_agent", "action": "execute",
            "input_keys": ["requirement_analysis"], "output_key": "test_points"},
           {"agent_type": "testcase_generator_agent", "action": "execute",
            "input_keys": ["requirement_analysis", "test_points"], "output_key": "test_cases"},
           {"agent_type": "testcase_review_agent", "action": "execute",
            "input_keys": ["test_cases"], "output_key": "reviews"},
       ],
       user_id=0,
       session_id=request.task_id or "",
   )
   ```

3. **适配结果解析**（行 125-160 和 `_save_results` 函数 行 582+）：

   Gen2 返回结构 → Gen3 返回结构映射：
   ```
   result.get("results", {}).get("需求解析", {})        → result.get("context", {}).get("requirement_analysis", {})
   result.get("results", {}).get("测试点分析", {})       → result.get("context", {}).get("test_points", {})
   result.get("results", {}).get("用例生成", {})          → result.get("context", {}).get("test_cases", {})
   result.get("results", {}).get("用例审核", {})          → result.get("context", {}).get("reviews", {})
   result.get("session_id", "")                          → result.get("session_id", "") 或 session_id 参数
   result.get("task_id", "")                             → result.get("task_id", "") 或 task_id 参数
   result.get("duration", 0.0)                           → sum(s.get("duration", 0) for s in result.get("steps", []))
   ```

4. `regenerate_test_cases` 函数（行 479-538）：同样替换 `orchestrator.run(...)` 为 `task_runtime.execute_pipeline(...)`

### 2D. 重构 `testcase_generator_agent.py` 移除 Gen2 依赖

`app/agent/testcase/testcase_generator_agent.py` 第 226 行惰性导入 Gen2 工厂：

```python
# 当前（行 226-233）
from app.agent_runtime.factory import get_agent_factory
factory = get_agent_factory()
if not factory.exists("rag_agent"):
    return None
agent = factory.create_agent("rag_agent", context=...)
rag_result = agent.retrieve(query=query, top_k=self.RAG_TOP_K)
```

替换为直接导入：
```python
from app.agent.rag_agent import RAGAgent
agent = RAGAgent()
rag_result = agent.retrieve(query=query, top_k=self.RAG_TOP_K)
```

### 2E. 删除 agent_runtime/ 整个目录

确认上述三个消费者均已迁移后，删除整个目录（10 个文件）：
- `app/agent_runtime/__init__.py`
- `app/agent_runtime/registry.py`
- `app/agent_runtime/orchestrator.py`
- `app/agent_runtime/factory.py`
- `app/agent_runtime/runtime.py`
- `app/agent_runtime/context.py`
- `app/agent_runtime/events.py`
- `app/agent_runtime/exceptions.py`
- `app/agent_runtime/message_bus.py`
- `app/agent_runtime/README.md`

### 阶段 2 验证

1. Grep 搜索 `from app.agent_runtime` → 应零结果（排除 .md 文件）
2. 执行 `python -c "from app.api.agent_runtime import router; print('OK')"` 确认 API 导入正常
3. 执行 `python -c "from app.api.testcase_generation import router; print('OK')"` 确认测试用例 API 导入正常
4. 执行 `python -c "from app.agent.testcase.testcase_generator_agent import TestCaseGeneratorAgent; print('OK')"` 确认 Agent 导入正常

---

## 阶段 3：Gen1 内部子系统清理

### 3A. 验证并删除 `agent/runtime/` 子系统

`agent/runtime/` 包含 4 个文件：`__init__.py`, `manager.py`, `runtime.py`, `state.py`

验证结果：
- `from app.agent.runtime import` 仅出现在 `agent/__init__.py`（行 57）
- `RuntimeManager`/`AgentRuntime`/`get_runtime_manager` 的重导出无任何外部消费者

**操作**：
1. 从 `agent/__init__.py` 删除 `from app.agent.runtime import (AgentRuntime, RuntimeManager, get_runtime_manager)`
2. 从 `__all__` 移除 `"AgentRuntime"`, `"RuntimeManager"`, `"get_runtime_manager"`
3. 删除整个 `app/agent/runtime/` 目录

### 3B. 验证并删除 `agent/orchestrator/` 子系统

`agent/orchestrator/` 包含 3 个文件：`__init__.py`, `result_collector.py`, `task_orchestrator.py`

验证结果：
- `from app.agent.orchestrator import` 仅出现在 `agent/__init__.py`（行 71）
- `ResultCollector`/`TaskOrchestrator`/`get_task_orchestrator` 的重导出无任何外部消费者
  （注意：Gen2 的 `get_task_orchestrator` 已在阶段 2 删除）

**操作**：
1. 从 `agent/__init__.py` 删除 `from app.agent.orchestrator import (ResultCollector, TaskOrchestrator, get_task_orchestrator)`
2. 从 `__all__` 移除 `"ResultCollector"`, `"TaskOrchestrator"`, `"get_task_orchestrator"`
3. 删除整个 `app/agent/orchestrator/` 目录

### 3C. 保留的子系统

以下子系统仍被外部引用，**保留不动**：
- `agent/factory/` — 被 `services/task_service.py:20` 引用
- `agent/router/` — 被 `services/requirement_center_service.py:39` 引用
- `agent/memory/` — 被 `agent/base_agent.py` 引用（活跃基类）
- `agent/testcase/` — 被 Gen2 注册表和 Gen3 注册表引用

### 阶段 3 验证

1. Grep 搜索 `from app.agent.runtime import` → 应零结果
2. Grep 搜索 `from app.agent.orchestrator import` → 应零结果
3. 执行 `python -c "from app.agent import *; print('OK')"` 确认包导入正常

---

## 阶段 4：Stale __pycache__ 清理

### 4A. 清理策略

删除以下目录中的孤立 .pyc 文件（对应已删除的 .py 文件）：

| __pycache__ 位置 | 需清理的 .pyc |
|-----------------|-------------|
| `agent/__pycache__/` | graph_search_agent, mock_agent, router_agent, task_orchestrator 的 .pyc |
| `agent/case/__pycache__/` | context_enricher_agent, context_splitter, execution_runner_agent, framework_adapter_agent, script_generator_agent, image_parser, storage_agent, video_parser, schema_parser, swagger_parser 的 .pyc |
| `agent/runtime/__pycache__/` | 整个目录删除 |
| `agent/orchestrator/__pycache__/` | 整个目录删除 |
| `agent_runtime/__pycache__/` | 整个目录删除 |
| `api/__pycache__/` | rag, session, test_asset, test_assets, three_layer 的 .pyc |

### 阶段 4 验证

执行 `python -c "import app.main"` 确认无导入错误

---

## 阶段 5：全面验证

### 5A. 静态验证

搜索以下所有模式，均应返回零结果：
- `from app.agent_runtime` — Gen2 已删除
- `from app.agent.runtime import` — Gen1 runtime 子系统已删除
- `from app.agent.orchestrator` — Gen1 orchestrator 子系统已删除
- `LegacyTaskOrchestrator` — 已删除的重导出
- `graph_search_agent|mock_agent|router_agent`（在 import 语句中）
- `from app.agent.case.(context_enricher|context_splitter|execution_runner|framework_adapter|script_generator_agent|image_parser|storage_agent|video_parser|schema_parser|swagger_parser)`

### 5B. 导入验证

```bash
python -c "from app.main import app; print(f'{len(app.routes)} routes')"
python -c "from app.api import api_router; print(f'{len(api_router.routes)} routes')"
python -c "from app.runtime import get_task_runtime; print('Gen3 runtime OK')"
```

### 5C. 功能验证

1. `GET /api/v1/agents` — 返回 Gen3 注册的 Agent 列表
2. `POST /api/v1/task/run` — 提交任务，pipeline 执行正常
3. `POST /api/v1/testcase/generate` — 测试用例生成 pipeline 正常
4. `GET /api/v1/task/{sid}/logs` — 查询执行日志
5. `GET /api/v1/task/{sid}/status` — 查询任务状态

---

## 清理统计

| 清理项 | 数量 |
|--------|------|
| Gen1 死代码 .py 删除 | 14 |
| Gen1 __init__.py 修改 | 2（`agent/__init__.py`, `agent/case/__init__.py`） |
| Gen2 agent_runtime/ 全部删除 | 10 |
| Gen1 内部子系统删除 | 7（runtime/ 4 + orchestrator/ 3） |
| Gen3 agent_registry.py 修改 | 1（删 8 条 + 加 5 条） |
| Gen3 definitions.py 修改 | 1（同步删 8 条 + 加 5 条） |
| API 文件修改 | 2（`api/agent_runtime.py`, `api/testcase_generation.py`） |
| Agent 文件修改 | 1（`testcase_generator_agent.py`） |
| __pycache__ 清理 | 全部涉及目录 |
| **总计删除 .py 文件** | **31** |

## 风险提示

1. **不可删除的文件**：`scheduler_agent.py`, `task_executor.py`, `script_executor.py`, `script_validator.py`, `script_parser.py`, `case/api_extraction_agent.py`, `case/case_generator_v2.py`, `case/retriever_agent.py` 共 8 个文件仍被活跃引用
2. **Gen3 注册表补充**：必须在移除 Gen2 之前完成 testcase Agent 在 Gen3 注册表中的注册
3. **pipeline 返回结构**：Gen3 返回 `{status, steps, context, final_data}`，与 Gen2 的 `{session_id, task_id, results, duration}` 不同，`_save_results` 函数需适配
4. **REFACTOR_PLAN.md 延期**：本方案不包含完整 Gen1→Gen3 迁移（broadcast mode），仅处理死代码、Gen2 移除和 Gen1 内部死子系统
