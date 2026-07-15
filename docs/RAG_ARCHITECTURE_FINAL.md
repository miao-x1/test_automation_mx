# RAG 架构收敛最终文档

> 版本: 2.0
> 日期: 2026-07-13
> 状态: 已实施
> 修订: v2.0 R2R 完全收敛 — 仅负责入库前预处理（解析+切片），不参与运行时查询；Embedding 统一为单一实现

---

## 一、RAG 整体架构图

```
                          ┌─────────────┐
                          │    Agent     │
                          │ (业务逻辑)   │
                          └──────┬───────┘
                                 │
                          ┌──────▼───────┐
                          │    Context    │
                          │   Router     │
                          │ (统一路由)    │
                          └──────┬───────┘
                                 │
              ┌──────────────────┼──────────────────┐
              │                  │                  │
       ┌──────▼──────┐   ┌──────▼──────┐   ┌──────▼──────┐
       │    MySQL     │   │   Milvus    │   │   Neo4j     │
       │  业务数据     │   │  语义检索   │   │  关系推理   │
       └─────────────┘   └──────┬──────┘   └─────────────┘
                                │
                         ┌──────▼──────┐
                         │  Embedding  │
                         │  Factory    │
                         │ (统一实现)   │
                         └─────────────┘

  ─────────────────────────────────────────────────────

  入库流程（自下而上）:

                    Knowledge Pipeline
                          ↑
                   ┌──────┴──────┐
                   │     R2R     │
                   │ (解析+切片) │
                   └─────────────┘
                          ↑
                    Knowledge API
                          ↑
                      用户上传
```

---

## 二、R2R 职责

### 定位
R2R 是外部 RAG 框架（SciPhi-AI/R2R），作为文档预处理引擎。

### 职责边界
R2R **只负责知识进入系统前的预处理**：

| 职责 | 说明 |
|------|------|
| 文档解析 | PDF/Word/Markdown/JSON/图片 → 纯文本 |
| 文档切片 | 按策略分块（Chunk） |
| 向量生成 | R2R 内部 Embedding（项目不使用） |
| 知识存储 | R2R 内部存储（项目不使用） |

### R2R 流程
```
Document → Parser → Chunk → [项目接管] → Embedding → Milvus
```

### R2R 不参与
- ❌ 测试任务执行
- ❌ Agent 实时查询
- ❌ 页面元素检索
- ❌ 脚本生成

### 入库流程
```
用户上传文档
    ↓
Knowledge API (/knowledge/upload)
    ↓
KnowledgePipeline.ingest()
    ↓
Step 1: R2R 预处理
    ├── R2R upload_file() → R2R 内部解析+切片
    └── R2R get_chunks()  → 获取切片结果
    ↓
Step 2: RAGPipeline 三库写入
    ├── Embedding (统一 EmbeddingFactory)
    ├── MySQL knowledge_source + knowledge_chunk
    ├── Milvus rag_knowledge_vector
    └── Neo4j 图谱节点
    ↓
返回入库结果
```

### 降级策略
R2R 不可用时，自动降级为本地解析：
```
R2R 不可用 → RAGPipeline.ingest_document() (本地 DocumentLoader + Chunker + 三库写入)
```

---

## 三、Milvus 职责

### 定位
Milvus 是 AI 运行时语义检索数据库。

### Collection 设计

| Collection | 用途 | 向量维度 | 索引类型 | 距离度量 |
|-----------|------|---------|---------|---------|
| `ui_element_vector` | UI 页面元素向量 | 1024 | IVF_FLAT | COSINE |
| `test_case_vector` | 测试用例向量 | 1024 | IVF_FLAT | COSINE |
| `script_vector` | 脚本向量 | 1024 | IVF_FLAT | COSINE |
| `rag_knowledge_vector` | RAG 知识文档 Chunk 向量 | 1024 | IVF_FLAT | COSINE |
| `requirement_vector` | 需求向量 | 1024 | IVF_FLAT | COSINE |
| `page_vector` | 页面向量 | 1024 | IVF_FLAT | COSINE |

### Agent 运行时检索流程
```
Agent 需求
    ↓
ContextRouter.retrieve_sync(query, context_type)
    ↓
EmbeddingFactory → DashScopeEmbedding.embed_sync(query)
    ↓
Milvus TopK 搜索
    ↓
返回上下文
```

### 禁止
- ❌ Agent 直接调用 MilvusClient
- ❌ 在 Agent 中重复实现 Embedding
- ❌ 使用不一致的 API Key 或向量维度

---

## 四、Embedding 统一架构

### 问题（已修复）
改造前存在 **4 个重复的 DashScope Embedding 实现**：

| # | 位置 | API Key | API 端点 |
|---|------|---------|---------|
| 1 | `DashScopeEmbedding` | `DASHSCOPE_API_KEY`（不存在） | DashScope 原生 API |
| 2 | `EmbeddingAgent._embed_dashscope()` | `QWEN_API_KEY` | OpenAI 兼容 API |
| 3 | `ContextRouter._embed_dashscope_sync()` | `QWEN_API_KEY` | OpenAI 兼容 API |
| 4 | `RetrievalAgent._embed_query_dashscope()` | `QWEN_API_KEY` | OpenAI 兼容 API |

### 统一后
```
EmbeddingFactory (单例)
    ↓
DashScopeEmbedding (唯一实现)
    ├── API Key: settings.QWEN_API_KEY
    ├── API URL: https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings
    ├── Model:   settings.EMBEDDING_MODEL (默认 text-embedding-v3)
    ├── Dim:     settings.EMBEDDING_DIM (默认 1024)
    ├── async:  embed() / embed_batch()
    └── sync:   embed_sync() / embed_batch_sync()
```

### 使用方式
```python
# 异步上下文
from app.rag.embedding.factory import get_embedding_factory
embedding = get_embedding_factory().get_embedding()
vector = await embedding.embed(text)

# 同步上下文（ContextRouter.retrieve_sync 内部）
vector = embedding.embed_sync(text)
```

---

## 五、Context Router 设计

### 职责
统一决定 Agent 应该查询哪个数据源。**禁止 Agent 自己判断**。

### 路由表

| ContextType | 数据源 | 场景 |
|-------------|--------|------|
| `PAGE_ELEMENT` | MySQL + Milvus + Neo4j | 页面元素检索 |
| `DOCUMENT` | Milvus + MySQL | 知识文档检索 |
| `TEST_CASE` | Milvus | 测试用例检索 |
| `BUSINESS_FLOW` | Neo4j + MySQL | 业务流程检索 |
| `SCRIPT` | Milvus + MySQL | 脚本检索 |
| `EXECUTION_HISTORY` | MySQL | 执行历史检索 |

### 接口
```python
class ContextRouter:
    def retrieve_sync(
        self,
        query: str,
        context_type: ContextType,
        top_k: int = 10,
        filters: Optional[Dict] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """同步检索（Agent 统一入口）"""

    async def retrieve(
        self,
        query: str,
        context_type: ContextType,
        top_k: int = 10,
        filters: Optional[Dict] = None,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """异步检索"""
```

### R2R 在 ContextRouter 中的状态
- `_query_r2r()` 方法保留但返回空列表 + 警告日志
- R2R 不在路由表中
- ContextRouter 自身使用 EmbeddingFactory 统一获取 Embedding（不再自带重复实现）

---

## 六、Agent 调用流程

### 改造前（问题）
```
Agent → Milvus (直接查询，绕过 ContextRouter)
Agent → R2R (直接查询，绕过 ContextRouter)
Agent → 自带 Embedding 实现 (重复代码)
```

### 改造后（统一）
```
Agent → ContextRouter → Milvus / MySQL / Neo4j
ContextRouter → EmbeddingFactory → DashScopeEmbedding (统一)
```

### Agent 依赖矩阵（改造后）

| Agent | 查询路径 | 写入路径 | 改造状态 |
|-------|---------|---------|---------|
| RAGAgent | ContextRouter ✓ | — | 已完成 |
| ScriptReuseAgent | ContextRouter ✓ | — | 已完成 |
| RAGContextAgent | ContextRouter ✓ | — | 已完成 |
| RetrievalAgent | ContextRouter ✓ | — | 已完成（重写） |
| RetrieverAgent | ContextRouter ✓ | — | 已完成（重写） |
| EmbeddingAgent | — | EmbeddingFactory ✓ | 已完成 |
| GraphAgent | — | Neo4j 直接写入 | 写入操作，可接受 |
| RelationAgent | Neo4j 直接查询 | — | 待改造（低优先级） |
| KnowledgeUpdateAgent | — | Milvus + Neo4j + MySQL | 写入操作，可接受 |

---

## 七、数据流总览

### 入库数据流
```
用户上传文档
    ↓
Knowledge API
    ↓
KnowledgePipeline
    ├── R2R: 解析 + 切片
    └── RAGPipeline: Embedding + MySQL + Milvus + Neo4j
    ↓
三库数据一致

Agent 查询
    ↓
ContextRouter
    ├── EmbeddingFactory → DashScopeEmbedding
    ├── Milvus: 语义检索
    ├── MySQL: 结构化查询
    └── Neo4j: 关系推理
    ↓
合并结果返回 Agent
```

### 检索数据流
```
Agent.request(query)
    ↓
ContextRouter.retrieve_sync(query, context_type)
    ↓
路由表选择数据源
    ↓
┌─ Milvus: embed_sync(query) → search(top_k) → 向量结果
├─ MySQL:  结构化查询 (source_id, chunk_type, ...)
└─ Neo4j:  关系图查询 (page→element, api→dependency)
    ↓
合并 + 去重 + 排序
    ↓
返回 {results, total, source_breakdown}
```

---

## 八、修改文件清单

### Phase 1: R2R 收敛
| 文件 | 改动 |
|------|------|
| `api/knowledge.py` | 移除 /search /retrieve 的 R2R 降级路径 |
| `services/knowledge/requirement_service.py` | 统一走 KnowledgePipeline，不再直接调 R2R |

### Phase 2: Embedding 统一
| 文件 | 改动 |
|------|------|
| `rag/embedding/dashscope_embedding.py` | 统一实现，使用 QWEN_API_KEY + OpenAI 兼容 API |
| `rag/embedding/base.py` | 添加 embed_sync/embed_batch_sync 方法 |
| `services/context_router/router.py` | 移除重复的 _embed_dashscope_sync/_embed_local_sync |
| `agent/rag/embedding_agent.py` | 移除重复的 _embed_dashscope/_embed_local，使用 EmbeddingFactory |

### Phase 3: Agent 改造
| 文件 | 改动 |
|------|------|
| `agent/rag/retrieval_agent.py` | 重写为 ContextRouter 路由 |
| `agent/case/retriever_agent.py` | 重写为 ContextRouter 路由，修复集合名和 API 问题 |

### Phase 4: 死代码清理
| 文件 | 改动 |
|------|------|
| `agent/storage/storage_agent.py` | 移除不存在的 MilvusService 导入 |
| `services/requirement_flow_service.py` | 移除不存在的 MilvusService 导入 |

---

## 九、验证结果

所有修改文件通过 Python 语法检查：
```
app/api/knowledge.py: OK
app/services/knowledge/requirement_service.py: OK
app/services/knowledge/case_generate_service.py: OK
app/rag/embedding/dashscope_embedding.py: OK
app/rag/embedding/base.py: OK
app/services/context_router/router.py: OK
app/agent/rag/retrieval_agent.py: OK
app/agent/rag/embedding_agent.py: OK
app/agent/case/retriever_agent.py: OK
app/agent/storage/storage_agent.py: OK
app/services/requirement_flow_service.py: OK
```

---

## 十、未来扩展方案

### 短期（已完成）
1. ✅ R2R 收敛为入库预处理工具
2. ✅ Embedding 统一为单一实现
3. ✅ ContextRouter 成为唯一查询入口
4. ✅ Agent 不再直接操作 Milvus

### 中期（待实施）
1. RAGQueryAgent 接入 ContextRouter（目前独立实现 keyword→vector→graph→rerank 流水线）
2. RelationAgent 接入 ContextRouter（目前直接查询 Neo4j）
3. 新版 Agent (app/agents/) 全部接入 ContextRouter

### 长期
1. Collection 命名统一（当前 6 个 Collection 命名风格不一致）
2. MultiVectorStore 与 milvus_client.py 的 Schema 统一
3. 广播模式（MessageBus）真正生效，Pipeline 改为事件驱动
4. DBMemory 修复缓存空时不查 DB 的问题
