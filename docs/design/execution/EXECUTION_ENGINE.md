# EXECUTION_ENGINE.md — 执行引擎

## 目录结构

```
execution/
├── dispatcher.py      # 执行调度器（入口）
├── queue.py           # 执行队列
├── runner.py          # 执行器（HTTP/Web/Android）
├── collector.py       # 结果收集器
└── report.py          # 报告生成器
```

## 执行流程

```
dispatch → worker → runner → report
```

### dispatch（调度）
- 接收执行请求（case_id / suite_id）
- 创建 ExecutionRecord
- 分发到执行队列

### worker（工作线程）
- 从队列获取任务
- 调用 runner 执行
- 更新执行状态

### runner（执行器）
- HttpRunner：API测试执行
- WebRunner：Web UI测试执行
- AndroidRunner：Android测试执行

### report（报告）
- 收集执行结果
- 生成报告
- 更新 TestAsset.execution_state

## 执行记录

```python
class ExecutionRecord:
    id: int
    task_id: int              # 关联Task
    asset_id: int             # 关联TestAsset
    status: str               # pending/running/success/failed
    result: dict              # 执行结果
    started_at: datetime
    finished_at: datetime
    duration_ms: int
    logs: str                 # 实时日志
```

## 支持能力

| 能力 | 说明 |
|------|------|
| 实时日志 | SSE推送执行日志 |
| 暂停 | 暂停执行队列 |
| 恢复 | 恢复执行队列 |
| 重试 | 失败用例重试 |
| 历史 | 执行记录查询 |

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /execution/run/case | POST | 直接执行用例 |
| /execution/run/suite | POST | 执行套件 |
| /execution/{id}/status | GET | 查询执行状态 |
| /execution/{id}/logs | GET | SSE实时日志 |
| /execution/{id}/pause | POST | 暂停执行 |
| /execution/{id}/resume | POST | 恢复执行 |
| /execution/{id}/retry | POST | 重试执行 |
| /execution/recent | GET | 最近执行列表 |

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 执行队列阻塞 | 中 | 异步执行+超时机制 |
| 实时日志丢失 | 低 | SSE重连+后端缓存 |
