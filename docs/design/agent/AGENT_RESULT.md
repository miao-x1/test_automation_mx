# Agent输出持久化

## 核心原则
禁止仅存在内存。所有Agent输出存数据库。

## agent_result 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| session_id | Integer FK | 会话ID |
| agent | String(50) | Agent名称 |
| input | Text | Agent输入(JSON) |
| output | Text | Agent输出(JSON) |
| summary | String(500) | 结果摘要 |
| tokens | Integer | 消耗token数 |
| cost | Float | 费用(元) |
| status | String(20) | pending/running/completed/failed |

## 保存的Agent结果
| Agent | 输入 | 输出 |
|-------|------|------|
| Requirement | 需求文本 | 需求摘要+功能点 |
| APIExtraction | 需求文本 | ApiMeta |
| RAG | 查询文本 | 检索上下文 |
| CaseGenerate | 功能点列表 | asset_ids |
| Review | 用例列表 | 审查结果 |

## 支持
- 重新恢复：从失败的Agent继续
- 查看历史：读取历史Agent结果
- 调试定位：查看输入/输出/错误
