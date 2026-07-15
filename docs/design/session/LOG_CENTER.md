# 日志中心

## 位置
会话中心 → 日志Tab

## 显示内容
| 字段 | 说明 |
|------|------|
| 时间 | created_at |
| Agent | agent名称 |
| 事件类型 | START/PROGRESS/SUCCESS/ERROR |
| 消息 | 事件消息 |
| 耗时 | duration(秒) |
| 费用 | cost(元) |

## 接口
GET /workflow/logs?session_id={id}

## 功能
- 下载日志为文本
- 复制日志
- 按Agent过滤
- 按事件类型过滤
