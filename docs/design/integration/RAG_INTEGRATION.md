# Phase 4 — 接入 R2R / AnythingChat

## 目标

UI Automation 调用已有 AnythingChat，不运行三个项目。

## 步骤1：AnythingChatClient

### 文件
`backend/app/services/knowledge/client.py`

### 类
`AnythingChatClient`

### 配置
| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| R2R_BASE_URL | http://localhost:7272 | AnythingChat 服务地址 |
| R2R_API_KEY | None | API Key（可选） |

### 接口
| 方法 | 说明 |
|------|------|
| upload(content, doc_type, metadata) | 上传文本到知识库 |
| upload_file(file_path, metadata) | 上传文件到知识库 |
| search(query, top_k, filters, project_id) | 语义搜索 |
| retrieve(query, top_k, filters, project_id) | 增强检索（RAG） |
| health() | 健康检查 |

### 限制
- top_k ≤ 3
- 上下文 ≤ 1500 token
- 请求头自动注入 API Key

## 步骤2：统一接口

### 端点
| 端点 | 方法 | 说明 |
|------|------|------|
| /knowledge/upload | POST | 上传文件到知识库 |
| /knowledge/search | POST | 语义搜索 |
| /knowledge/retrieve | POST | 增强检索（RAG） |

### 认证
所有接口需 `require_auth`。

### 降级
- upload 失败 → 降级到本地 RequirementService
- search 失败 → 返回空结果 `{results: [], total: 0, fallback: true}`
- retrieve 失败 → 返回默认业务规则 `{fallback: true}`

### 修改文件
- `backend/app/api/knowledge.py` — 添加认证，upload 优先走 AnythingChatClient

## 步骤3：生成流程

### 流程
```
需求 → 上传知识 → RAG检索 → 生成 → 保存
```

### 详细步骤
1. **需求**：从 Session 加载 requirement_summary
2. **上传知识**：调用 `rag_client.upload()` 将需求摘要上传到知识库
3. **RAG检索**：调用 `rag_client.retrieve()` 检索相关业务规则
4. **生成**：使用 RAG 上下文增强，流式生成 TestAsset
5. **保存**：创建 TestAsset（draft），validate_executable()

### 降级
- RAG 检索失败 → 使用默认业务规则继续生成
- 默认规则：校验必填参数、校验类型格式、处理异常边界

### 修改文件
- `backend/app/services/workflow/generation_flow.py` — RAG 步骤改用 AnythingChatClient

## 步骤4：Redis 缓存

### 策略
| 操作 | 缓存 | TTL |
|------|------|-----|
| search | Redis 优先，降级内存 | 300s |
| retrieve | Redis 优先，降级内存 | 300s |
| upload | 清除所有检索缓存 | — |

### 缓存 Key
`rag:{md5(method:json_params)}`

### 实现
- `_get_cache()`: Redis → 内存缓存
- `_set_cache()`: Redis → 内存缓存
- `_invalidate_cache()`: 上传后清除所有检索缓存

## 步骤5：失败降级

### 降级链
```
AnythingChat → 默认业务规则 → 继续生成（无 RAG）
```

### 降级场景
| 场景 | 行为 |
|------|------|
| AnythingChat 不可用 | 返回默认业务规则 |
| HTTP 请求超时 | 返回默认业务规则 |
| API Key 无效 | 返回默认业务规则 |
| Redis 不可用 | 降级到内存缓存 |
| 默认业务规则也不可用 | 硬编码规则继续生成 |

### 标记
降级结果包含 `"fallback": true` 标记，前端可据此显示提示。

## 验证

- [x] Python 语法检查通过（client.py / knowledge.py / generation_flow.py）
- [x] AnythingChatClient 封装 upload/search/retrieve/health
- [x] 统一接口 /knowledge/upload|search|retrieve 添加认证
- [x] 生成流程：需求→上传知识→RAG检索→生成→保存
- [x] Redis 缓存 TTL=300s，上传后清除
- [x] 失败自动降级，无 RAG 继续生成
