# 脚本后流程完善计划

## 概述

扩展管道从脚本生成后到最终导出的完整流程（13步管道），修复已发现的兼容性问题，并完成前端适配。

## 当前状态分析

### 已完成（后端）
| 项 | 状态 | 说明 |
|---|---|---|
| param_mapping/extract_fields/defaults 机制 | ✅ | task_runtime.py 两个函数均已实现 |
| 13步管道定义 | ✅ | build_pipeline_steps() 已定义全部步骤 |
| __pipeline_meta__ 注入 | ✅ | run_task + run_task_stream 均已注入 |
| StorageAgent | ✅ | 创建并注册，store() + execute() 完整 |
| DefectAgent.analyze_from_execution | ✅ | 适配方法已创建 |
| required: False 支持 (SSE版) | ✅ | execute_pipeline_sse 已实现跳过逻辑 |

### 待修复问题

#### 问题1: RoutedAgent 子类的 action 路由缺失（严重）
- **ReportAgent**: 管道 action 为 `"generate"`，但 `BaseRoutedAgent._action_handlers` 仅注册了 `"execute"` 和 `"default"`
- **DefectAgent**: 管道 action 为 `"analyze_from_execution"`，同样未注册
- **后果**: `handle_task_message` 抛出 `ValueError("Unknown action: ...")`，步骤失败
- **ExportAgent**: action 为 `"execute"`，已在默认注册中，理论上可用，但需验证

#### 问题2: ReportAgent._do_generate 输入格式不匹配
- 管道传入的 `execution_result` 是执行结果 dict（含 log_content, failed_count 等）
- 但 `_do_generate` 期望的 payload 含 `total`, `passed`, `failed`, `skipped`, `duration`, `results`, `logs` 等字段
- 需要适配方法将 execution_result 转换为 _do_generate 所需格式

#### 问题3: _invoke_handler 调用签名不匹配
- `BaseRoutedAgent._invoke_handler` 调用 `handler(payload, ctx)` — 两个位置参数
- 但 `DefectAgent.analyze_from_execution` 签名是 `(execution_result, task_id)` — 关键字参数
- 需要包装方法统一签名为 `(payload: Dict, ctx: MessageContext)`

#### 问题4: execute_pipeline (非SSE版) 缺少 required: False 支持
- 步骤失败时直接返回 `{"status": "failed"}`，终止整个管道
- 非必需步骤（storage/report/defect/export）失败也会终止管道

#### 问题5: 前端 SSE 事件格式不匹配
- `execute_pipeline_sse` 发出的事件使用 `{"event": "step_start", "data": {...}}` 格式
- 前端 `AgentRuntimePage.tsx` 仅处理 `event_type` 字段（旧格式），不识别 `event` 字段
- 导致 `pipeline_start`, `step_start`, `step_completed`, `step_failed`, `pipeline_completed` 事件全部被忽略

#### 问题6: 前端缺少后脚本步骤的展示组件
- 无测试报告卡片
- 无缺陷分析表格
- 无存储/导出状态展示

## 实施方案

### 步骤1: 修复 ReportAgent 管道兼容性
**文件**: `c:\ui-automation\backend\app\agents\flows\report_agent.py`

在 `__init__` 中注册 `"generate"` action handler，并创建管道适配方法：

```python
def __init__(self) -> None:
    super().__init__(...)
    self._report_dir = os.path.join(os.getcwd(), "reports")
    # 注册管道 action
    self.register_action("generate", self._pipeline_generate)

async def _pipeline_generate(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
    """管道适配：从 execution_result 生成报告"""
    execution_result = payload.get("execution_result", payload)
    task_id = str(payload.get("task_id", ""))

    # 从 execution_result 提取报告所需字段
    total = execution_result.get("total", 0) if isinstance(execution_result, dict) else 0
    passed = execution_result.get("passed", 0) if isinstance(execution_result, dict) else 0
    failed = execution_result.get("failed_count", execution_result.get("failed", 0)) if isinstance(execution_result, dict) else 0
    skipped = execution_result.get("skipped", 0) if isinstance(execution_result, dict) else 0
    logs = execution_result.get("log_content", "") if isinstance(execution_result, dict) else ""

    report_payload = {
        "task_id": task_id,
        "total": total,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "duration": execution_result.get("duration", 0) if isinstance(execution_result, dict) else 0,
        "results": execution_result.get("results", []) if isinstance(execution_result, dict) else [],
        "logs": logs,
    }
    return await self._do_generate(report_payload)
```

### 步骤2: 修复 DefectAgent 管道兼容性
**文件**: `c:\ui-automation\backend\app\agents\flows\defect_agent.py`

在 `__init__` 中注册 `"analyze_from_execution"` action handler：

```python
def __init__(self) -> None:
    super().__init__(...)
    # 注册管道 action
    self.register_action("analyze_from_execution", self._pipeline_analyze_from_execution)

async def _pipeline_analyze_from_execution(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
    """管道适配：签名统一为 (payload, ctx)"""
    execution_result = payload.get("execution_result", {})
    task_id = str(payload.get("task_id", ""))
    return await self.analyze_from_execution(execution_result=execution_result, task_id=task_id)
```

### 步骤3: 验证 ExportAgent 管道兼容性
**文件**: `c:\ui-automation\backend\app\agents\flows\export_agent.py`

ExportAgent 的 action 是 `"execute"`，已在默认 `_action_handlers` 中注册。但其 `execute()` 方法通过 `handle_export()` 间接调用，`handle_export` 被装饰为 `@message_handler`。

需要确认直接调用 `handle_export(msg, ctx)` 是否正常工作。如果 `@message_handler` 装饰器阻止了直接调用，则需要创建管道适配方法：

```python
async def _pipeline_export(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
    """管道适配：不依赖 @message_handler 装饰"""
    # 直接执行导出逻辑，不通过 handle_export
    scripts = payload.get("scripts", [])
    framework = payload.get("framework", "playwright")
    script_language = payload.get("script_language", "python")
    # ... 执行保存逻辑 ...
    return {"status": "success", "total_scripts": len(scripts)}
```

并在 `__init__` 中: `self.register_action("execute", self._pipeline_export)`

### 步骤4: 修复 execute_pipeline (非SSE版) required: False 支持
**文件**: `c:\ui-automation\backend\app\runtime\task_runtime.py`

在 `execute_pipeline()` 的错误处理部分添加 `required: False` 跳过逻辑，与 `execute_pipeline_sse()` 保持一致：

```python
# 当前代码（第371行）:
if result.get("status") == "failed":
    return {"status": "failed", ...}

# 改为:
if result.get("status") == "failed":
    is_required = step.get("required", True)
    if is_required:
        return {"status": "failed", "failed_step": i, ...}
    else:
        logger.warning(f"Step {i} ({agent_type}) failed but not required, skipping")
        if output_key:
            context[output_key] = {"status": "skipped", "error": str(result.get("errors", ""))}
        step_results.append({...})
        continue
```

### 步骤5: 前端 SSE 事件处理适配
**文件**: `c:\ui-automation\frontend\src\pages\agent-runtime\AgentRuntimePage.tsx`

在 SSE onEvent 回调中新增对管道级事件的处理。当前前端仅处理 `event_type` 字段，需要同时处理 `event` 字段：

```typescript
// pipeline_start — 管道开始
if (event.event === 'pipeline_start') {
  const data = event.data;
  setSessionId(data.session_id || '');
  setTotalSteps(data.total_steps || 0);
  return;
}

// step_start — 步骤开始（替代 agent_started）
if (event.event === 'step_start') {
  const data = event.data;
  setSteps(prev => {
    const stepName = `${data.step + 1}. ${data.agent_type}`;
    const exists = prev.find(s => s.name === stepName);
    if (exists) {
      return prev.map(s => s.name === stepName ? {...s, status: 'running'} : s);
    }
    return [...prev, {
      name: stepName,
      agent_name: data.agent_type,
      status: 'running',
      message: `执行: ${data.action}`,
      progress: 0,
      duration: 0,
    }];
  });
  return;
}

// step_completed — 步骤完成（替代 agent_completed）
if (event.event === 'step_completed') {
  const data = event.data;
  setSteps(prev => prev.map((s, idx) =>
    idx === data.step ? {
      ...s, status: 'completed',
      duration: data.duration,
      output_data: data.data,
    } : s
  ));
  setCompletedSteps(prev => prev + 1);

  // 提取特定步骤结果
  if (data.data) {
    if (data.step === 7) setStorageResult(data.data);       // storage
    if (data.step === 9) setReportResult(data.data);         // report
    if (data.step === 10) setDefectResult(data.data);       // defect
    if (data.step === 12) setExportResult(data.data);       // export
  }
  return;
}

// step_failed — 步骤失败
if (event.event === 'step_failed') {
  const data = event.data;
  setSteps(prev => prev.map((s, idx) =>
    idx === data.step ? {...s, status: 'failed', error: data.error} : s
  ));
  return;
}

// pipeline_completed — 管道完成
if (event.event === 'pipeline_completed') {
  const data = event.data;
  setTaskStatus('completed');
  if (data.session_id) {
    setSessionId(data.session_id);
    loadLogs(data.session_id);
  }
  return;
}

// done — 结束（兼容 event 和 event_type 两种格式）
if (event.event === 'done' || event.event_type === 'done') {
  setRunning(false);
  sseRef.current = false;
  return;
}
```

新增状态变量：
```typescript
const [storageResult, setStorageResult] = useState<any>(null);
const [reportResult, setReportResult] = useState<any>(null);
const [defectResult, setDefectResult] = useState<any>(null);
const [exportResult, setExportResult] = useState<any>(null);
```

### 步骤6: 前端展示组件
**文件**: `c:\ui-automation\frontend\src\pages\agent-runtime\AgentRuntimePage.tsx`

在执行结果区域（Timeline 下方）新增：

1. **测试报告卡片** — 当 `reportResult` 存在时显示：
   - 通过/失败/跳过统计
   - 通过率进度条
   - 报告文件链接

2. **缺陷分析表格** — 当 `defectResult` 存在且 `defects.length > 0` 时显示：
   - 缺陷ID | 测试名称 | 错误类型 | 严重程度 | 错误信息

3. **存储/导出状态** — 在步骤表格中自动展示（通过 output_data）

### 步骤7: 前端 runTaskSSE 完成判断修复
**文件**: `c:\ui-automation\frontend\src\services\agentRuntime.ts`

当前 `runTaskSSE` 仅在 `data.event_type === 'done'` 时触发 `onComplete`。管道发出的 done 事件使用 `event` 字段而非 `event_type`：

```typescript
// 当前代码（第180行）:
if (data.event_type === 'done') {
  onComplete?.();
  return;
}

// 改为:
if (data.event_type === 'done' || data.event === 'done') {
  onComplete?.();
  return;
}
```

## 实施顺序

1. **步骤1-3**: 修复后端 Agent 管道兼容性（ReportAgent + DefectAgent + ExportAgent 验证）
2. **步骤4**: 修复 execute_pipeline required: False 支持
3. **步骤5-7**: 前端适配（SSE事件 + 展示组件 + runTaskSSE修复）
4. **验证**: 启动后端服务，提交测试任务，验证完整管道流程

## 验证清单

- [ ] 后端启动无导入错误
- [ ] 前端编译无 TypeScript 错误
- [ ] 提交 web_test 任务，13步管道完整执行
- [ ] storage_agent 步骤成功（脚本入库 + 向量化）
- [ ] execution_agent 步骤成功（脚本执行）
- [ ] report_agent 步骤成功（报告生成）
- [ ] defect_agent 步骤成功或被跳过（required: False）
- [ ] feedback_agent 步骤成功（失败分析）
- [ ] flow_export_agent 步骤成功或被跳过（required: False）
- [ ] 前端正确显示所有步骤状态
- [ ] 前端显示测试报告卡片
- [ ] 前端显示缺陷分析表格（如有缺陷）
- [ ] 非必需步骤失败时管道继续执行
