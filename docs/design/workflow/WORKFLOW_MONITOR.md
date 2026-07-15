# 前端实时刷新（替代SSE）

## 核心变更
禁止页面等待。改为轮询刷新。

## useWorkflowMonitor Hook
- 文件: `frontend/src/hooks/useWorkflowMonitor.ts`
- 轮询间隔: 2秒
- 自动停止: completed/failed

## 流程
```
启动 → 返回session_id → 轮询 → 更新页面
```

## 接口
| 端点 | 方法 | 说明 |
|------|------|------|
| /workflow/start | POST | 启动工作流 |
| /workflow/status | GET | 获取状态 |
| /workflow/events | GET | 获取事件列表 |
| /workflow/result | GET | 获取Agent结果 |
| /workflow/resume | POST | 恢复执行 |
| /workflow/rerun | POST | 重新执行 |

## 返回值
- status: 工作流状态
- events: 事件列表
- results: Agent结果
- resume(): 恢复执行
- rerun(): 重新执行
- fetchLogs(): 获取日志
