# 会话中心

## 菜单位置
需求 → 会话管理

## 页面布局
左：会话列表 | 右：详情

## 详情Tab
| Tab | 内容 | 数据源 |
|-----|------|--------|
| 需求 | requirement_summary | Session |
| API提取 | ApiMeta | GET /workflow/result?agent=APIExtraction |
| RAG上下文 | 检索结果 | GET /workflow/result?agent=RAG |
| 用例 | 生成的用例 | GET /workflow/result?agent=CaseGenerate |
| 日志 | WorkflowEvent时间线 | useWorkflowMonitor |
| 执行 | 状态+操作 | useWorkflowMonitor |

## 接口
| 端点 | 方法 | 说明 |
|------|------|------|
| /session/list | GET | 会话列表 |
| /session/{id} | GET | 会话详情 |
| /session/{id}/timeline | GET | 事件时间线 |
| /session/{id}/resume | POST | 恢复执行 |
| /session/{id}/rerun | POST | 重新执行 |

## 功能
- 继续执行：从失败步骤恢复
- 重新执行：从头重跑
- 查看错误：错误详情+堆栈
- 恢复页面：切换页面不丢状态
