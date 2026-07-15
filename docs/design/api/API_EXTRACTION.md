# API信息提取阶段

## 流程位置
需求理解 → **APIExtraction** → RAG → CaseGenerate → Review → Publish

## APIExtractionAgent
- 文件: `backend/app/agent/case/api_extraction_agent.py`
- 职责: 从需求文本中提取接口元数据
- 输出: ApiMeta `{session_id, apis: [{name, method, path, headers, request_schema, response_schema, depends, priority}]}`

## api_metadata 表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| session_id | Integer FK | 会话ID |
| content | Text | API元数据(JSON) |
| status | String | pending/extracted/confirmed/modified |
| api_count | Integer | 提取的API数量 |

## 降级
- LLM提取失败 → 规则提取（mock）
- 结果标记 `fallback: true`
