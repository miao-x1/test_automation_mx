# 最终用户流程

## 架构
```
Session → Workflow → Agent Event → DB → 前端轮询刷新
```

## 用户流程
```
上传需求 → 创建会话 → 后台运行 → 查看阶段 → 查看日志 → 查看API提取 → 查看用例 → 发布 → 执行 → 报告
```

## 禁止
- 实时刷模型回答
- token级SSE输出
- 仅内存存储

## 允许
- 查看进度（阶段刷新）
- 查看日志（事件时间线）
- 恢复执行（断点续传）
- 重新执行（从头重跑）

## 新增模型
| 模型 | 说明 |
|------|------|
| api_metadata | API提取结果 |
| workflow_event | 工作流事件 |
| agent_result | Agent输出持久化 |

## 新增Agent
| Agent | 说明 |
|-------|------|
| APIExtractionAgent | API信息提取 |

## 新增页面
| 页面 | 路由 |
|------|------|
| SessionCenter | /sessions |
| ApiAnalyzePage | /api-test/analyze |

## 新增Hook
| Hook | 说明 |
|------|------|
| useWorkflowMonitor | 工作流轮询监控 |

## 新增API
| 端点 | 说明 |
|------|------|
| POST /workflow/start | 启动工作流 |
| GET /workflow/status | 获取状态 |
| GET /workflow/events | 获取事件 |
| GET /workflow/result | 获取结果 |
| GET /workflow/logs | 获取日志 |
| POST /workflow/resume | 恢复执行 |
| POST /workflow/rerun | 重新执行 |

## 验证
- [x] TypeScript 编译通过（0 errors）
- [x] Python 语法检查通过
- [x] 事件驱动替代SSE
- [x] 所有Agent输出持久化
- [x] 会话中心支持恢复/重跑
- [x] 前端轮询刷新
- [x] API提取阶段新增
- [x] 接口解析页面新增
