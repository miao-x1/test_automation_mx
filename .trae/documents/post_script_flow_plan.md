# 脚本生成之后的流程 — 实施计划

## 概述

将统一管道从脚本生成后的2步（execution_agent + feedback_agent）扩展为完整的6步后置流程，补齐 Storage/Report/Defect/Export 能力，并修复参数映射 Bug。

## 现状分析

### 当前管道（web_test 9步）

```
1.requirement_agent → 2.rag_agent → 3.relation_agent → 4.graph_agent → 5.flow_parser
→ 6.case_agent → 7.script_generator → 8.execution_agent → 9.feedback_agent
```

脚本生成后仅有执行+反馈两步。Gen3图流有完整13节点但未接入统一管道。

### 已确认的 Bug

**Bug 1 — execution_agent 参数不匹配**:
- 步骤 `input_keys: ["test_script"]` → `payload["test_script"] = context["test_script"]`
- 但 `ExecutionAgent.execute_script()` 签名是 `(script_content, task_id, execution_id, on_log)`
- 参数名 `test_script` ≠ `script_content`，且 `task_id`/`execution_id` 缺失

**Bug 2 — feedback_agent 参数不匹配**:
- 步骤 `input_keys: ["execution_result"]` → `payload["execution_result"] = ...`
- 但 `FeedbackAgent.analyze_failure()` 签名是 `(requirement, script_content, exec_result, ...)`
- 参数名 `execution_result` ≠ `exec_result`，且 `requirement`/`script_content` 缺失

**Bug 3 — context 值类型不确定**:
- `context["test_script"]` 可能是 dict（含 script_content + degradation_info）而非纯字符串

## 改动方案

### 设计原则

1. **声明式参数映射** — 步骤定义中新增 `param_mapping`/`extract_fields`/`defaults` 字段，不改 Agent 方法签名
2. **管道元数据注入** — context 中维护 `__pipeline_meta__`，携带 task_id/session_id/requirement 等
3. **渐进式步骤插入** — 新步骤设为 `required: False`，失败不阻断管道
4. **复用已有 Gen3 实现** — ReportAgent/DefectAgent/ExportAgent 已有完整逻辑

### 扩展后的管道（web_test 13步）

```
 7. script_generator   → test_script
 8. storage_agent (新)  → storage_result       [required: False]
 9. execution_agent    → execution_result
10. report_agent (新)   → report_result         [required: False]
11. defect_agent (新)   → defect_result         [required: False]
12. feedback_agent     → analysis_result
13. export_agent (新)   → export_result         [required: False]
```

### 数据流

```
context["test_script"] = {script_content: str, degradation_info?: dict}
         │
    ┌────┴────────┐
    ▼             ▼
storage_agent   execution_agent
(store: 入库    (execute_script:
 +Milvus+Neo4j)  执行+HTML报告)
    │                │
    ▼                ▼
storage_result  execution_result = {
                   status, success_count,
                   failed_count, log_content,
                   screenshot_path, report_path}
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         report_agent        defect_agent
         (生成HTML+          (提取缺陷+
          JSON报告)           严重度分级)
              │                   │
              └────────┬──────────┘
                       ▼
                 feedback_agent
                 (规则分析+
                  反馈上下文)
                       │
                       ▼
                  export_agent
                  (汇总导出)
```

## 实施步骤

### 步骤1: 修复参数映射 Bug

**文件**: `app/runtime/task_runtime.py`

在 `execute_pipeline` 和 `execute_pipeline_sse` 的上下文注入逻辑中，支持 `param_mapping`/`extract_fields`/`defaults`:

```python
# 当前代码（约第417行）
for key in input_keys:
    if key in context:
        payload[key] = context[key]

# 改为
param_mapping = step.get("param_mapping", {})
extract_fields = step.get("extract_fields", {})
defaults = step.get("defaults", {})
pipeline_meta = context.get("__pipeline_meta__", {})

for key in input_keys:
    if key in context:
        param_name = param_mapping.get(key, key)
        value = context[key]
        extract_field = extract_fields.get(key)
        if extract_field and isinstance(value, dict):
            value = value.get(extract_field, value)
        payload[param_name] = value

for param_name, default_value in defaults.items():
    if param_name not in payload:
        if isinstance(default_value, str) and default_value.startswith("__meta__."):
            meta_key = default_value[len("__meta__."):]
            payload[param_name] = pipeline_meta.get(meta_key, 0)
        else:
            payload[param_name] = default_value
```

同时处理 `__pipeline_meta__` 注入到 context:
```python
if "__pipeline_meta__" in payload:
    context["__pipeline_meta__"] = payload.pop("__pipeline_meta__")
```

**文件**: `app/api/agent_runtime.py`

修改 `build_pipeline_steps` 中 execution_agent 和 feedback_agent 步骤:

```python
# execution_agent（修改后）
{
    "agent_type": "execution_agent",
    "action": "execute_script",
    "input_keys": ["test_script"],
    "param_mapping": {"test_script": "script_content"},
    "extract_fields": {"test_script": "script_content"},
    "defaults": {"task_id": "__meta__.task_id", "execution_id": "__meta__.execution_id"},
    "output_key": "execution_result",
},

# feedback_agent（修改后）
{
    "agent_type": "feedback_agent",
    "action": "analyze_failure",
    "input_keys": ["execution_result"],
    "param_mapping": {"execution_result": "exec_result"},
    "defaults": {
        "requirement": "__meta__.requirement",
        "script_content": "__meta__.script_content",
    },
    "output_key": "analysis_result",
},
```

在 `run_task`/`run_task_stream` 中，执行管道前注入 `__pipeline_meta__`:

```python
steps[0]["payload"]["__pipeline_meta__"] = {
    "task_id": task_id_int,
    "session_id": session_id,
    "requirement": req.requirement,
    "execution_id": execution_id_int,
    "script_content": "",  # 在script_generator完成后回填
}
```

### 步骤2: 新建 StorageAgent

**新建文件**: `app/agent/storage/storage_agent.py`

```python
class StorageAgent(NewBaseAgent):
    agent_name = "storage_agent"
    display_name = "存储Agent"
    capabilities = [AgentCapability.KNOWLEDGE_UPDATE]

    def store(self, test_script, requirement="", task_id=0, test_cases=None):
        """脚本入库 + Milvus向量化 + Neo4j知识更新"""
        # 1. 提取script_content
        # 2. 保存到Script表
        # 3. EmbeddingAgent + MilvusService.insert_script_vector
        # 4. KnowledgeUpdateAgent.update_after_execution
        # 全部try/except，失败返回degraded状态
```

**注册**: 在 `definitions.py` 中添加 `storage_agent` AgentSpec

### 步骤3: 添加 Report 管道步骤

复用已有的 `app/agents/flows/report_agent.py`（已注册为 `report_agent`）。

在 `build_pipeline_steps` 中 execution_agent 之后添加:
```python
{
    "agent_type": "report_agent",
    "action": "generate",
    "input_keys": ["execution_result"],
    "defaults": {"task_id": "__meta__.task_id"},
    "required": False,
    "output_key": "report_result",
},
```

**注意**: ReportAgent 是 RoutedAgent 子类，需验证管道 Adapter 能否正确处理其返回格式。如不能，新建 LegacyAgent 适配类。

### 步骤4: 添加 Defect 管道步骤

在 `app/agents/flows/defect_agent.py` 中新增管道适配方法:

```python
async def analyze_from_execution(self, execution_result, task_id=""):
    """从执行结果分析缺陷（管道适配方法）"""
    logs = execution_result.get("log_content", "")
    failed_results = self._extract_failed_from_logs(logs, execution_result)
    return await self._do_analyze({"task_id": task_id, "failed_results": failed_results, "logs": logs})
```

在 `build_pipeline_steps` 中 report_agent 之后添加:
```python
{
    "agent_type": "defect_agent",
    "action": "analyze_from_execution",
    "input_keys": ["execution_result"],
    "defaults": {"task_id": "__meta__.task_id"},
    "required": False,
    "output_key": "defect_result",
},
```

### 步骤5: 添加 Export 管道步骤

复用已有的 `app/agents/flows/export_agent.py`（注册名为 `flow_export_agent`）。

在 `build_pipeline_steps` 中 feedback_agent 之后添加:
```python
{
    "agent_type": "flow_export_agent",
    "action": "execute",
    "input_keys": ["report_result", "defect_result", "analysis_result"],
    "defaults": {
        "task_id": "__meta__.task_id",
        "session_key": "__meta__.session_id",
        "scripts": [],
        "script_language": "python",
        "framework": "playwright",
    },
    "required": False,
    "output_key": "export_result",
},
```

### 步骤6: 管道执行器增强 — required 标记

**文件**: `app/runtime/task_runtime.py`

在 `execute_pipeline` 和 `execute_pipeline_sse` 中支持 `required: False`:

```python
is_required = step.get("required", True)

if result.get("status") == "failed":
    if is_required:
        # 终止管道
        return {"status": "failed", "failed_step": i, ...}
    else:
        # 跳过，继续下一步
        logger.warning(f"Step {i} ({agent_type}) failed but not required, skipping")
        context[output_key] = {"status": "skipped", "error": result.get("error")}
        continue
```

### 步骤7: SSE 事件增强

**文件**: `app/runtime/task_runtime.py`

在 `execute_pipeline_sse` 中为新增步骤发送扩展事件:

```python
if agent_type == "storage_agent":
    yield {"event": "storage_completed", "data": {...}}
elif agent_type == "report_agent":
    yield {"event": "report_completed", "data": {"report_path": ...}}
elif agent_type == "defect_agent":
    yield {"event": "defect_completed", "data": {"total_defects": ...}}
elif agent_type == "export_agent":
    yield {"event": "export_completed", "data": {"total_scripts": ...}}
```

### 步骤8: 前端适配

**文件**: `frontend/src/pages/agent-runtime/AgentRuntimePage.tsx`

- 新增 `reportInfo`/`defectInfo` 状态
- SSE 事件处理新增 `storage_completed`/`report_completed`/`defect_completed`/`export_completed`
- 新增测试报告卡片（HTML/JSON 报告链接）
- 新增缺陷分析表格（缺陷ID/测试名/错误类型/严重程度/错误信息）

## 实施顺序

```
阶段1: Bug修复
  ├── 1a. task_runtime.py: 添加 param_mapping/extract_fields/defaults 支持
  ├── 1b. agent_runtime.py: 修改 execution_agent/feedback_agent 步骤定义
  └── 1c. agent_runtime.py: run_task/run_task_stream 注入 __pipeline_meta__

阶段2: Storage步骤
  ├── 2a. 新建 storage_agent.py
  ├── 2b. definitions.py 注册 storage_agent
  └── 2c. build_pipeline_steps 添加 storage 步骤

阶段3: Report/Defect/Export步骤
  ├── 3a. build_pipeline_steps 添加 report 步骤
  ├── 3b. DefectAgent 新增 analyze_from_execution 适配方法
  ├── 3c. build_pipeline_steps 添加 defect 步骤
  └── 3d. build_pipeline_steps 添加 export 步骤

阶段4: 管道执行器增强
  ├── 4a. task_runtime.py: 支持 required: False
  └── 4b. task_runtime.py: 扩展 SSE 事件

阶段5: 前端适配
  ├── 5a. AgentRuntimePage.tsx: 新增事件处理
  └── 5b. AgentRuntimePage.tsx: 新增报告/缺陷展示组件
```

## 向后兼容

- `param_mapping`/`extract_fields`/`defaults` 均为可选字段，不添加时行为与当前一致
- `required` 默认 True，不添加时失败仍终止管道
- 新步骤全部设为 `required: False`，失败不阻断
- `api_test`/`android_test`/`performance_test` 工作流不修改
- Gen1 委托模式和 GraphFlow 模式不受影响
- Agent 方法签名不变

## 风险与对策

| 风险 | 对策 |
|------|------|
| RoutedAgent 返回格式与管道 Adapter 不兼容 | 验证 execute_sse 对 RoutedAgent 的处理；如不兼容，新建 LegacyAgent 适配类 |
| context["test_script"] 类型不确定 | 用 extract_fields 从 dict 提取 script_content |
| Milvus/Neo4j 不可用 | required: False + try/except 降级 |
| task_id/execution_id 为 0 | ExecutionAgent 增加对 task_id=0 的容错 |
| ExportAgent 注册名不一致 | 确认 definitions.py 中是 `flow_export_agent`，管道中使用正确名称 |

## 验证

1. 单元验证: `execute_script(script_content="...", task_id=1, execution_id=1)` 调用成功
2. 管道验证: 简单需求跑完整 13 步，确认 context 正确传递
3. 降级验证: 断开 Milvus/Neo4j，确认 Storage 步骤降级不影响后续
4. SSE 验证: 前端确认新事件类型能接收和渲染
5. 回归验证: api_test/android_test/performance_test 行为不变
