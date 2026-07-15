# SESSION_ARCH.md — Session中心

## SessionEvent 模型

```python
class SessionEvent:
    id: int
    session_id: int           # 关联会话
    event_type: str           # 事件类型
    payload: str              # 事件数据(JSON)
    step_index: int           # 步骤序号
    timestamp: datetime       # 时间戳
```

## 事件类型

| 事件类型 | 说明 | payload示例 |
|----------|------|-------------|
| upload | 上传 | {"source_type": "pdf", "file": "xxx.pdf"} |
| chunk | 分块 | {"chunk_count": 5} |
| rag | RAG检索 | {"total": 3, "has_context": true} |
| generate | 生成用例 | {"asset_id": 1, "title": "xxx"} |
| publish | 发布 | {"asset_ids": [1,2,3]} |
| execute | 执行 | {"execution_id": 42, "status": "success"} |
| error | 错误 | {"message": "RAG检索失败"} |

## 恢复机制

```
1. 加载Session
2. 查询所有SessionEvent（按step_index排序）
3. 重放事件，恢复到最新状态
4. 如果最新事件是generate，可继续发布
5. 如果最新事件是publish，可继续执行
```

## SessionCenter 页面

```
┌─────────────────────────────────────────┐
│ 会话中心                                  │
├──────────┬──────────────────────────────┤
│ 会话列表  │ 事件时间线                     │
│ #1 需求A  │ ┌─ upload  10:00            │
│ #2 需求B  │ ├─ chunk   10:01            │
│ #3 需求C  │ ├─ rag     10:02            │
│           │ ├─ generate 10:05           │
│           │ ├─ publish  10:10           │
│           │ └─ execute  10:15           │
└──────────┴──────────────────────────────┘
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| /session/list | GET | 会话列表 |
| /session/{id} | GET | 会话详情 |
| /session/{id}/events | GET | 事件列表 |
| /session/{id}/resume | POST | 恢复会话 |

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 事件数据过大 | 低 | payload限制大小 |
| 恢复时状态不一致 | 中 | 事件重放+校验 |
