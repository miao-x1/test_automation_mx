# 三层数据体系模块

企业级三层数据访问架构，实现AI根据任务自动判断查哪个数据库。

## 架构概览

```
┌──────────────────────────────────────────────┐
│              Agent / API 层                   │
│    (测试用例生成/脚本生成/需求分析)              │
└──────────────────┬───────────────────────────┘
                   │
         ┌─────────▼─────────┐
         │  ContextRouter     │  ← 智能路由：判断查什么库
         │  (app/context/)    │
         └─────────┬─────────┘
                   │ RetrievalPlan
         ┌─────────▼─────────┐
         │  RetrievalManager  │  ← 统一调度：执行三库检索
         │  (app/retrieval/)   │
         └────┬────┬────┬─────┘
              │    │    │
     ┌────────▼─┐ ┌▼──────┐ ┌────────▼─┐
     │ MySQL     │ │Milvus │ │ Neo4j    │
     │ Retriever │ │Retriev│ │ Retriever│
     └───────────┘ └───────┘ └──────────┘
              │    │    │
         ┌────▼────▼────▼─────┐
         │  ContextFusion     │  ← 融合结果
         │  (app/context/)    │
         └─────────┬─────────┘
                   │ FusedContext
         ┌─────────▼─────────┐
         │  Agent使用上下文    │
         └───────────────────┘
```

## 三层数据库职责

| 数据库 | 定位 | 存储内容 | 检索方式 |
|--------|------|----------|----------|
| MySQL | 业务数据库 | 用户/任务/需求/用例/执行/报告/配置 | 结构化查询（SQL） |
| Milvus | 语义知识库 | 需求文档/历史用例/脚本/页面描述 | 向量ANN（余弦相似度） |
| Neo4j | 关系图谱 | 页面→元素→API→用例→脚本 关系链 | Cypher图遍历 |

## 目录结构

```
backend/app/
├── context/                      # 上下文路由层
│   ├── __init__.py
│   ├── models.py                 # 数据模型（TaskContext, RetrievalPlan, FusedContext）
│   ├── router.py                 # ContextRouter - 智能路由器
│   └── fusion.py                 # ContextFusion - 结果融合器
│
├── retrieval/                    # 统一检索层
│   ├── __init__.py
│   ├── base.py                   # BaseRetriever - 检索器基类
│   ├── mysql_retriever.py        # MysqlRetriever - MySQL检索
│   ├── milvus_retriever.py       # MilvusRetriever - Milvus向量检索
│   ├── neo4j_retriever.py        # Neo4jRetriever - Neo4j图检索
│   └── manager.py                # RetrievalManager - 统一管理器
│
├── agent/testcase/
│   └── knowledge_sync_agent.py   # KnowledgeSyncAgent - 数据同步
│
└── api/
    └── context_api.py            # 三层上下文API
```

## API端点

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/context/route | 预览路由计划（不执行检索） |
| POST | /api/v1/context/retrieve | 执行检索并返回融合上下文 |
| GET | /api/v1/context/preview/{task_id} | 查看任务使用的AI上下文 |
| GET | /api/v1/context/stats | 获取三层系统统计 |

## 路由规则

| 任务类型 | MySQL | Milvus | Neo4j |
|----------|-------|--------|-------|
| 脚本生成 | task, test_case, script, ui_element | script_vector, test_case_vector | Page, Element, API, Script |
| 用例生成 | test_requirement, test_case_point, test_case | test_case_vector, rag_knowledge | Page, Element, TestCase |
| 需求分析 | requirement_task, requirement_input | requirement_vector, rag_knowledge | (跳过) |
| Web测试 | task, ui_element, script | script_vector, page_vector | Page, Element, Script |
| 接口测试 | api_case, api_metadata | rag_knowledge | API, TestCase |

## 扩展指南

### 新增检索器

1. 继承 `BaseRetriever`
2. 实现 `search(query)` 方法
3. 在 `RetrievalManager` 中注册

### 新增数据库类型

1. 在 `context/models.py` 中新增 Query 数据类
2. 在 `RetrievalPlan` 中添加新字段
3. 在 `ContextRouter` 中添加路由规则
4. 创建新的 Retriever
5. 在 `RetrievalManager` 中调度

### 接入新Agent

```python
from app.context.router import get_context_router
from app.rag.retrieval_engine.manager import get_retrieval_manager

# 1. 构建任务上下文
context = TaskContext(
    task_id="xxx",
    requirement="生成登录测试脚本",
    task_type="script_generation",
)

# 2. 路由
router = get_context_router()
plan = router.route(context)

# 3. 检索
manager = get_retrieval_manager()
fused = manager.retrieve(plan)

# 4. 使用上下文
print(fused.business_context)   # MySQL数据
print(fused.knowledge_context)  # Milvus参考
print(fused.graph_context)     # Neo4j关系
```
