# 工作流事件（替代SSE流式输出）

## 核心变更
禁止LLM token级输出。改为阶段刷新。

## WorkflowEvent 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| session_id | Integer FK | 会话ID |
| agent | String(50) | Agent名称 |
| event_type | String(20) | START/PROGRESS/SUCCESS/ERROR/SKIP |
| message | Text | 事件消息 |
| cost | Float | 费用 |
| duration | Float | 耗时(秒) |

## 事件类型
| 类型 | 说明 |
|------|------|
| START | Agent开始执行 |
| PROGRESS | 阶段进度（如"已生成5条用例"） |
| SUCCESS | Agent成功完成 |
| ERROR | Agent执行失败 |
| SKIP | Agent跳过 |

## 前端刷新
- 轮询间隔: 2秒
- 终态(completed/failed)自动停止轮询
- 显示: 状态、阶段、日志，不显示模型输出
