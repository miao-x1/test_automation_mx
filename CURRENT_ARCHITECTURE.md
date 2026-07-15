# UI Automation 平台 — 当前架构冻结报告

> 生成时间：2026-06-17
> 状态：**冻结现状，禁止改代码**

---

## 一、当前目录树

### 1.1 后端 (`backend/app/`)

```
app/
├── main.py                              # FastAPI 入口
│
├── api/                                 # API路由层（22个路由模块）
│   ├── __init__.py                      # 路由注册中心
│   ├── health.py                        # 健康检查        /
│   ├── auth.py                          # 认证            /auth
│   ├── dashboard.py                     # 仪表盘          /dashboard
│   ├── task.py                          # 任务管理        /tasks
│   ├── page.py                          # 页面抓取(兼容)  /page
│   ├── execution.py                     # 执行管理        /executions
│   ├── rag.py                           # RAG知识库       /rag
│   ├── requirement.py                   # 需求驱动        /requirement
│   ├── kb.py                            # 知识库管理      /kb
│   ├── graph.py                         # 图数据库        /graph
│   ├── feedback.py                      # 用户反馈        /feedback
│   ├── page_relation.py                 # 页面关联        /page-relation
│   ├── multimodal_input.py              # 多模态输入      /multimodal-input
│   ├── schedule.py                      # 定时任务        /schedule
│   ├── script_upload.py                 # 脚本上传        /script-upload
│   ├── admin.py                         # 管理模块        /admin
│   ├── knowledge.py                     # 知识服务        /knowledge
│   │
│   ├── case.py                          # ⚠️ 旧用例中心   /case
│   ├── test_asset.py                    # ⚠️ 旧资产管理   /assets
│   ├── test_assets.py                   # ⚠️ 旧资产中心   /test-assets
│   ├── three_layer.py                   # ⚠️ 三层测试     /three-layer
│   │
│   ├── api_test/                        # 接口测试模块    /api-test
│   │   ├── __init__.py
│   │   ├── case_controller.py           #   用例管理
│   │   ├── suite_controller.py          #   测试套件
│   │   ├── execution_controller.py      #   执行引擎
│   │   ├── report_controller.py         #   报告
│   │   └── import_controller.py         #   导入(AI/Swagger)
│   │
│   ├── upload_task.py                   # 上传任务系统    /upload/task
│   ├── session.py                       # 会话管理        /session
│   ├── assets_v2.py                     # ★ 统一资产V2    /assets/v2
│   └── workflow.py                      # ★ 工作流引擎    /workflow
│
├── services/                            # 业务服务层
│   ├── assets/                          # ★ 统一资产服务
│   │   ├── asset_service.py             #   资产CRUD/发布/统计
│   │   └── migration_service.py         #   旧数据迁移
│   ├── workflow/                        # ★ 工作流引擎
│   │   └── generation_flow.py           #   生成工作流
│   ├── execution/                       # 执行引擎
│   │   ├── dispatcher.py                #   执行调度器
│   │   ├── http_runner.py               #   HTTP执行器
│   │   ├── case_runner.py               #   用例执行器
│   │   ├── assertion_engine.py          #   断言引擎
│   │   ├── context.py                   #   执行上下文
│   │   ├── execution_queue.py           #   执行队列
│   │   ├── redis_queue.py               #   Redis队列
│   │   ├── report_generator.py          #   报告生成
│   │   └── result_writer.py             #   结果写入
│   ├── case/                            # ⚠️ 旧用例服务
│   │   ├── compiler.py                  #   用例编译器(分层存储L1/L2/L3)
│   │   ├── case_sync_service.py         #   ⚠️ CaseContent→ApiCase同步
│   │   ├── requirement_chunk_service.py #   分块+滚动摘要
│   │   └── test_type_router.py          #   测试类型路由
│   ├── cache/
│   │   └── pipeline_cache.py            #   缓存
│   ├── knowledge/
│   │   ├── case_generate_service.py     #   用例生成服务
│   │   ├── client.py                    #   知识库客户端
│   │   └── requirement_service.py       #   需求服务
│   ├── rag_service.py                   # RAG服务
│   ├── kb_service.py                    # 知识库服务
│   ├── graph_service.py                 # 图服务
│   ├── graph_build_service.py           # 图构建
│   ├── page_crawler_service.py          # 页面爬虫
│   ├── requirement_service.py           # 需求服务
│   ├── requirement_flow_service.py      # 需求流程
│   ├── execution_service.py             # 执行服务
│   ├── task_service.py                  # 任务服务
│   ├── unified_task_service.py          # 统一任务
│   └── data_fusion_service.py           # 数据融合
│
├── agent/                               # Agent推理层
│   ├── case/                            # 用例相关Agent
│   │   ├── requirement_understanding_agent.py  # L1需求理解
│   │   ├── case_compiler_agent.py              # L2用例编译(逐条流式)
│   │   ├── test_normalization_agent.py         # L3标准化
│   │   ├── rag_context_agent.py                # RAG上下文
│   │   ├── review_agent.py                     # 审查
│   │   ├── agent_selector.py                   # Agent选择器
│   │   ├── document_parser.py / swagger_parser.py / schema_parser.py
│   │   ├── image_parser.py / video_parser.py
│   │   ├── mindmap_agent.py / script_generator_agent.py
│   │   ├── execution_runner_agent.py / framework_adapter_agent.py
│   │   ├── context_enricher_agent.py / context_splitter.py
│   │   ├── retriever_agent.py / storage_agent.py
│   │   └── case_generator.py / case_generator_v2.py
│   ├── base.py / factory.py / prompt_builder.py
│   ├── input_router.py / type_classifier.py
│   ├── playwright_agent.py / page_crawler_agent.py
│   ├── execution_agent.py / rag_agent.py
│   ├── graph_agent.py / graph_search_agent.py
│   ├── requirement_agent.py / relation_agent.py
│   ├── strategy_agent.py / scheduler_agent.py
│   ├── task_executor.py / task_orchestrator.py
│   ├── script_executor.py / script_generator.py / script_parser.py
│   ├── script_reuse_agent.py / script_validator.py
│   ├── knowledge_update_agent.py / feedback_agent.py
│   ├── fusion_agent.py / mock_agent.py
│   ├── element_agent.py / element_merge_agent.py
│   ├── embedding_agent.py / page_state_manager.py
│   ├── message_bus.py / flow_parser.py / flow_script_generator.py
│   └── router_agent.py
│
├── models/                              # 数据模型层（30个模型）
│   ├── base.py                          # BaseModel / OwnedModel
│   ├── user.py                          # User / UserRole / Workspace
│   ├── task.py                          # Task / TaskStatus / InputMode / TaskType
│   ├── test_asset.py                    # ⚠️ 旧TestAsset (web/api/performance/android)
│   ├── test_asset_v2.py                 # ★ TestAssetV2 (统一资产)
│   ├── session_event.py                 # ★ SessionEvent (事件溯源)
│   ├── session.py                       # Session / SessionContent
│   ├── test_point.py                    # TestPoint
│   ├── requirement_chunk.py             # RequirementChunk
│   ├── case_content.py                  # ⚠️ CaseContent (AI草稿)
│   ├── case_task.py                     # ⚠️ CaseTask (生成任务)
│   ├── case_mindmap.py                  # CaseMindmap
│   ├── case_export.py                   # CaseExport
│   ├── case_generation.py               # CaseGeneration
│   ├── api_case.py                      # ⚠️ ApiCase (发布层)
│   ├── test_suite.py                    # TestSuite / SuiteExecution
│   ├── execution_record.py              # ExecutionRecord
│   ├── requirement_task.py              # RequirementTask
│   ├── requirement_input.py             # RequirementInput
│   ├── schedule_task.py                 # ScheduleTask / ScheduleRunLog
│   ├── feedback.py                      # Feedback
│   ├── knowledge_source.py              # KnowledgeSource
│   ├── knowledge_chunk.py               # KnowledgeChunk
│   ├── retrieval_log.py                 # RetrievalLog
│   ├── image_file.py                    # ImageFile
│   ├── analysis_result.py               # AnalysisResult
│   ├── script.py                        # Script
│   ├── ui_element.py                    # UIElement
│   ├── page_element.py                  # PageElement
│   └── page_relation.py                 # (import存在但未在__init__导出)
│
├── schemas/                             # 请求/响应Schema
│   ├── response.py                      # 统一Response
│   ├── case_set.py                      # CaseSet
│   ├── requirement_context.py           # RequirementContext
│   ├── retrieved_context.py             # RetrievedContext
│   └── task.py                          # TaskSchema
│
├── prompts/                             # Prompt模板
│   ├── case_prompt.py
│   ├── requirement_prompt.py
│   └── playwright_prompt.py
│
├── core/                                # 核心配置
│   ├── config.py / auth.py / logger.py
│   ├── provider.py / task_queue.py
│   └── providers/ (api/web/android/performance)
│
├── db/                                  # 数据库
│   ├── database.py                      # MySQL + SQLAlchemy
│   ├── milvus_client.py                 # Milvus向量库
│   └── neo4j_client.py                  # Neo4j图库
│
├── mcp/                                 # MCP协议
│   └── server.py
│
└── utils/
```

### 1.2 前端 (`frontend/src/`)

```
src/
├── App.tsx                              # 主入口(菜单+路由)
├── main.tsx                             # React挂载
│
├── pages/
│   ├── Dashboard.tsx                    # 仪表盘
│   ├── admin/                           # 管理(8个页面)
│   ├── requirement/                     # 需求(5个页面)
│   │   ├── RequirementList.tsx
│   │   ├── RequirementCreate.tsx
│   │   ├── RequirementAnalyze.tsx
│   │   ├── RequirementDecompose.tsx     # ⚠️ 旧
│   │   └── RequirementToTask.tsx        # ⚠️ 旧
│   ├── web/                             # Web测试(10个页面)
│   ├── api-test/                        # 接口测试(9个页面)
│   ├── test-assets/                     # ★ 测试资产中心
│   │   └── TestAssetsPage.tsx           #   统一资产(Draft/Published/Generate/History)
│   ├── test-case/                       # ⚠️ 旧用例(5个页面,路由重定向到test-assets)
│   ├── session/                         # 会话中心
│   │   └── SessionCenter.tsx
│   ├── upload/                          # 上传任务中心
│   │   └── UploadTaskCenter.tsx
│   ├── auth/                            # 认证(3个页面)
│   ├── settings/                        # 设置
│   └── [旧页面兼容](7个)
│
├── services/                            # API服务层(22个服务)
│   ├── request.ts                       # HTTP客户端
│   ├── auth.ts / requirement.ts / case.ts
│   ├── apiCase.ts / apiSuite.ts / apiExec.ts / apiReport.ts
│   ├── asset.ts / task.ts / threeLayer.ts
│   ├── rag.ts / kb.ts / graph.ts
│   ├── page.ts / pageRelation.ts / schedule.ts
│   ├── scriptUpload.ts / multimodalInput.ts
│   ├── feedback.ts / executionAnalysis.ts
│   └── taskTypeDetector.ts
│
├── stores/                              # 状态管理
│   └── uploadStore.ts                   # zustand上传Store
│
├── components/                          # 通用组件(8个)
│   ├── UI.tsx / ErrorBoundary.tsx
│   ├── AIStepTimeline.tsx / ExecutionTimeline.tsx
│   ├── RequirementInput.tsx / SmartSuggestion.tsx
│   ├── TaskUnderstanding.tsx / PageRelationPanel.tsx
│
├── hooks/                               # 自定义Hook
│   └── useExecutionPoller.ts
│
├── styles/                              # 样式
│   └── global.css
│
└── types/                               # 类型定义
    └── d3-force.d.ts
```

---

## 二、API映射

### 2.1 当前全部API路由

| 前缀 | 模块 | 状态 | 说明 |
|------|------|------|------|
| `/` | health | 活跃 | 健康检查 |
| `/auth` | auth | 活跃 | 认证登录 |
| `/dashboard` | dashboard | 活跃 | 仪表盘 |
| `/tasks` | task | 活跃 | 任务管理 |
| `/assets` | test_asset | ⚠️旧 | 旧资产管理 |
| `/page` | page | 兼容 | 页面抓取 |
| `/executions` | execution | 活跃 | 执行管理 |
| `/rag` | rag | 活跃 | RAG知识库 |
| `/requirement` | requirement | 活跃 | 需求驱动 |
| `/kb` | kb | 活跃 | 知识库管理 |
| `/graph` | graph | 活跃 | 图数据库 |
| `/feedback` | feedback | 活跃 | 用户反馈 |
| `/page-relation` | page_relation | 活跃 | 页面关联 |
| `/multimodal-input` | multimodal_input | 活跃 | 多模态输入 |
| `/schedule` | schedule | 活跃 | 定时任务 |
| `/script-upload` | script_upload | 活跃 | 脚本上传 |
| `/admin` | admin | 活跃 | 管理模块 |
| `/case` | case | ⚠️旧 | 旧用例中心 |
| `/knowledge` | knowledge | 活跃 | 知识服务 |
| `/three-layer` | three_layer | ⚠️旧 | 三层测试 |
| `/api-test` | api_test | 活跃 | 接口测试(5个子路由) |
| `/test-assets` | test_assets | ⚠️旧 | 旧资产中心 |
| `/upload/task` | upload_task | 活跃 | 上传任务系统 |
| `/session` | session | 活跃 | 会话管理 |
| `/assets/v2` | assets_v2 | ★新 | 统一测试资产 |
| `/workflow` | workflow | ★新 | 工作流引擎 |

### 2.2 重复API端点对照

| 功能 | 旧端点 | 新端点 | 重复 |
|------|--------|--------|------|
| 用例列表 | `GET /case/list` | `GET /assets/v2/list` | ✅ |
| 草稿列表 | `GET /test-assets/drafts` | `GET /assets/v2/list?status=generated` | ✅ |
| 发布用例 | `POST /test-assets/publish` | `POST /assets/v2/publish` | ✅ |
| 已发布列表 | `GET /test-assets/list` | `GET /assets/v2/list?status=published` | ✅ |
| 类型统计 | `GET /test-assets/type-stats` | `GET /assets/v2/stats/summary` | ✅ |
| AI生成 | `POST /three-layer/compile` | `POST /workflow/generate` | ✅ |
| SSE流式 | `POST /three-layer/generate/stream` | `POST /workflow/generate/stream` | ✅ |
| 任务列表 | `GET /three-layer/tasks` | `GET /workflow/{session_id}` | ✅ |
| 任务结果 | `GET /three-layer/tasks/{id}/result` | `GET /workflow/{session_id}` | ✅ |
| 执行 | `POST /api-test/execution/run` | `POST /assets/v2/execute` | ✅ |
| 用例同步 | `POST /api-test/import/sync/to-api-test` | `POST /assets/v2/migrate` | ✅ |
| API用例CRUD | `POST/GET/PUT/DELETE /api-test/cases/*` | `POST/GET/PUT/DELETE /assets/v2/*` | ✅ |

---

## 三、页面路由

### 3.1 当前一级菜单

```
仪表盘
管理
  ├── 用户管理 / 角色权限 / 项目管理 / 环境配置 / 系统配置 / 数据源 / 脚本仓库
需求
  ├── 需求列表 / 需求创建 / 需求分析 / 会话管理
Web
  ├── 页面管理 / 创建测试 / 执行测试 / 测试结果 / 测试报告 / 定时任务(子)
Android (disabled)
接口测试
  ├── 用例管理 / 测试套件 / 执行 / 报告
测试资产
  ├── 资产中心 / AI生成 / 上传中心
─────────────────
个人中心 / 系统设置
```

### 3.2 已删除的一级菜单

```
测试用例 (已删除,路由重定向到test-assets)
  ├── AI生成 → /test-assets/generate
  ├── 用例列表 → /test-assets
  ├── 思维导图 → /test-assets
  └── 导出 → /test-assets
```

### 3.3 旧路由兼容重定向

| 旧路由 | 重定向到 |
|--------|----------|
| `/test-case/*` | `/test-assets` |
| `/manage` | `/web/execute` |
| `/executions` | `/web/results` |
| `/schedule` | `/web/schedule` |
| `/script-upload` | `/web/create` |
| `/test-type/api` | `/api-test/cases` |
| `/test-type/web` | `/web/execute` |

---

## 四、数据模型

### 4.1 三套资产体系（核心重复）

```
┌─────────────────────────────────────────────────────────────────┐
│                    ⚠️ 三套资产体系重复                            │
├─────────────────┬──────────────────┬────────────────────────────┤
│   CaseContent   │     ApiCase      │     TestAssetV2 (★新)      │
│   (AI草稿层)     │   (发布层)        │     (统一资产)              │
├─────────────────┼──────────────────┼────────────────────────────┤
│ case_task_id    │ folder_id        │ session_id                 │
│ title           │ title            │ title                      │
│ case_type       │ case_id          │ asset_type (api/web/       │
│                 │                  │   android/case)            │
│ precondition    │ description      │ description                │
│ steps (Text)    │ steps (MEDIUMTEXT)│ draft_content (Text)      │
│ expected (Text) │ assertions (MT)  │ published_content (Text)   │
│ priority        │ priority         │ priority                   │
│ tags            │ tags             │ tags                       │
│ case_status     │ status           │ status (created→...→exec)  │
│   draft/review/ │   draft/review/  │                            │
│   published     │   published/dep  │                            │
│ source_type     │ source           │ source (ai/manual/         │
│                 │                  │   swagger/import/reused)   │
│ test_type       │ test_type        │ (由asset_type替代)          │
│ api_case_id     │ source_content_id│ legacy_case_content_id     │
│                 │                  │ legacy_api_case_id         │
│ version         │ version          │ version                    │
│ is_deleted      │ is_deleted       │ is_deleted                 │
│                 │ method           │ (在content_json内)          │
│                 │ url              │ (在content_json内)          │
│                 │ extracts         │ (在content_json内)          │
│                 │ variables        │ (在content_json内)          │
│                 │ env_override     │ (在content_json内)          │
│                 │ last_run_status  │ execution_state            │
│                 │ run_count        │ (在execution_state内)       │
│                 │ module_name      │ (无对应)                    │
│                 │ canonical_case_id│ (无对应)                    │
└─────────────────┴──────────────────┴────────────────────────────┘
```

### 4.2 旧TestAsset（Web脚本层，第三套资产）

```
┌─────────────────────────────────────────────────────────────────┐
│   TestAsset (旧) — Web脚本资产                                   │
├─────────────────────────────────────────────────────────────────┤
│ name             │ 资产名称                                      │
│ asset_type       │ web/api/performance/android                   │
│ task_id          │ 关联Task                                      │
│ input_config     │ 输入配置(JSON)                                 │
│ exec_config      │ 执行配置(JSON)                                 │
│ script_content   │ 脚本内容                                      │
│ script_language   │ python/javascript                            │
│ script_path      │ 脚本路径                                      │
│ version          │ 版本号                                        │
│ status           │ draft/ready/running/completed/failed/archived │
│ kb_status        │ 知识库审核状态                                 │
│ source           │ generated/reused/manual                       │
│ reuse_count      │ 复用次数                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 4.3 CaseTask（生成任务，与Session重叠）

```
┌─────────────────────────────────────────────────────────────────┐
│   CaseTask — 用例生成任务                                        │
├─────────────────────────────────────────────────────────────────┤
│ title              │ 任务标题                                    │
│ source_type        │ pdf/doc/image/video/schema/swagger/url/text│
│ source_file        │ 源文件路径                                  │
│ source_url         │ 源URL                                       │
│ raw_input          │ 原始输入                                    │
│ status             │ waiting/parsing/generating/reviewing/       │
│                    │ completed/failed                            │
│ requirement_context│ 解析后的RequirementContext(JSON)             │
│ case_set           │ 生成的CaseSet(JSON,含L1/L2/L3)              │
│ error_message      │ 错误信息                                    │
└─────────────────────────────────────────────────────────────────┘
```

### 4.4 其他关键模型

| 模型 | 表名 | 说明 |
|------|------|------|
| Session | session | 会话(与CaseTask功能重叠) |
| SessionContent | session_content | 会话内容 |
| SessionEvent | session_event | ★ 事件溯源 |
| RequirementChunk | requirement_chunk | 需求分块 |
| TestPoint | test_point | 测试点 |
| ExecutionRecord | execution_record | 执行记录(关联Task) |
| TestSuite | test_suite | 测试套件(关联ApiCase) |
| SuiteExecution | suite_execution | 套件执行记录 |
| ApiCaseFolder | api_case_folder | API用例目录 |

### 4.5 模型间关系

```
Task (1) ──── (N) TestAsset(旧)       Web脚本资产
  │
  └──── (N) ExecutionRecord           执行记录

CaseTask (1) ── (N) CaseContent       AI草稿
                      │
                      └── api_case_id ──→ ApiCase    发布层
                                            │
                              source_content_id ──→ CaseContent

Session (1) ── (N) SessionContent     会话内容
    │
    ├── (N) RequirementChunk          需求分块
    ├── (N) TestPoint                 测试点
    ├── (N) SessionEvent              事件溯源
    └── (N) TestAssetV2               ★ 统一资产

TestSuite (1) ── (N) SuiteExecution   套件执行
    └── case_ids ──→ ApiCase          编排用例

ApiCaseFolder (1) ── (N) ApiCase      目录分类
```

---

## 五、状态流

### 5.1 当前数据流（存在多条路径）

```
路径A（旧：CaseContent → ApiCase 同步）
═══════════════════════════════════════

  需求上传
     │
     ▼
  CaseTask (生成任务)
     │
     ▼
  CaseCompilerService.run_pipeline()
     │  L1: 需求理解 → features
     │  L2: 用例编译 → cases (逐条流式)
     │  L3: 标准化   → execution_ready
     ▼
  CaseContent (草稿, status=draft)
     │
     │  ⚠️ CaseSyncService.sync_single/batch()
     ▼
  ApiCase (发布, status=published)
     │
     ▼
  TestSuite.case_ids → SuiteExecution
     │
     ▼
  ExecutionRecord


路径B（新：Session → Workflow → TestAssetV2）
═══════════════════════════════════════════════

  需求上传
     │
     ▼
  Session (会话)
     │
     ▼
  TestGenerationWorkflow.run()
     │  Phase1: 需求获取
     │  Phase2: 分块处理 (RequirementChunkService)
     │  Phase3: 需求分析 (L1内部)
     │  Phase4: RAG增强
     │  Phase5: 用例生成 (L2内部, 逐条流式)
     │  Phase6: 审查
     ▼
  TestAssetV2 (status=reviewed)
     │
     │  AssetService.publish_assets()
     ▼
  TestAssetV2 (status=published)
     │
     ▼
  ExecutionDispatcher.dispatch()
     │
     ▼
  HttpRunner + AssertionEngine
     │
     ▼
  TestAssetV2.execution_state (更新)


路径C（旧：Web脚本）
═══════════════════

  页面抓取 → Task → TestAsset(旧, script_content)
     │
     ▼
  PlaywrightAgent → ExecutionRecord
```

### 5.2 调用链层级

```
页面(Page)
  │
  ▼
前端Service (services/*.ts)
  │
  ▼
API路由 (api/*.py)
  │
  ▼
业务Service (services/*.py)
  │
  ▼
Agent推理 (agent/*.py)     ← ⚠️ 部分Agent直接操作DB/API/文件
  │
  ▼
数据模型 (models/*.py)
  │
  ▼
数据库 (MySQL/Milvus/Neo4j)
```

---

## 六、重复模块标记

### 6.1 ⚠️ Case 重复

| 维度 | CaseContent | ApiCase | TestAssetV2 |
|------|-------------|---------|-------------|
| 定位 | AI草稿 | 发布执行 | 统一资产 |
| 表 | case_content | api_case | test_asset_v2 |
| API | /case, /test-assets/drafts | /api-test/cases, /test-assets/list | /assets/v2/list |
| Service | CaseCompilerService | CaseSyncService | AssetService |
| 状态 | draft/review/published | draft/review/published/deprecated | created→...→executed |
| 内容 | steps(Text) | steps(MEDIUMTEXT)+assertions | draft_content+published_content |
| 同步 | CaseContent → ApiCase (CaseSyncService) | ← | 无需同步 |

**问题**：CaseContent和ApiCase是同一资产的两个阶段，通过CaseSyncService手动同步，维护困难。

### 6.2 ⚠️ Asset 重复

| 维度 | TestAsset(旧) | TestAssetV2(新) |
|------|---------------|-----------------|
| 定位 | Web脚本资产 | 统一测试资产 |
| 表 | test_asset | test_asset_v2 |
| API | /assets | /assets/v2 |
| Service | task_service | AssetService |
| 类型 | web/api/performance/android | api/web/android/case |
| 内容 | script_content+input_config | draft_content+published_content |

**问题**：两套资产表，前端需要判断调用哪个API。

### 6.3 ⚠️ ThreeLayer 重复

| 维度 | three_layer API | workflow API |
|------|-----------------|--------------|
| 端点 | /three-layer/analyze,compile,generate | /workflow/generate |
| Service | CaseCompilerService | TestGenerationWorkflow |
| 状态 | L1/L2/L3 (暴露给页面) | created→...→executed (内部) |
| 存储 | CaseTask.case_set {L1,L2,L3} | TestAssetV2 + SessionEvent |

**问题**：L1/L2/L3是内部概念不应暴露，两套API做同样的事。

### 6.4 ⚠️ Execution 重复

| 维度 | execution API | api-test/execution | assets_v2/execute |
|------|---------------|--------------------|-------------------|
| 端点 | /executions | /api-test/execution/run | /assets/v2/execute |
| Service | ExecutionService | CaseRunner | ExecutionDispatcher |
| 模型 | ExecutionRecord | SuiteExecution | TestAssetV2.execution_state |

**问题**：三套执行入口，模型不统一。

### 6.5 ⚠️ Session vs CaseTask 重复

| 维度 | CaseTask | Session |
|------|----------|---------|
| 定位 | 用例生成任务 | 会话管理 |
| 状态 | waiting→completed | active→completed |
| 关联 | CaseContent | TestAssetV2, SessionEvent |
| 存储 | requirement_context, case_set | SessionContent, RequirementChunk |

**问题**：CaseTask和Session做同样的事（需求→生成），但数据模型不同。

---

## 七、风险点

| # | 风险 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | 三套资产体系(CaseContent+ApiCase+TestAssetV2) | 数据不一致，同步复杂 | P0 |
| 2 | CaseSyncService手动同步 | 同步失败→数据丢失 | P0 |
| 3 | ThreeLayer和Workflow两套API | 前端不知调哪个 | P1 |
| 4 | Agent直接操作DB/API/文件 | 违反职责分离，难测试 | P1 |
| 5 | ExecutionRecord关联Task而非TestAssetV2 | 执行结果无法关联到统一资产 | P1 |
| 6 | TestSuite.case_ids引用ApiCase | 迁移后引用断裂 | P1 |
| 7 | 前端test-case/目录仍存在 | 代码冗余，维护混乱 | P2 |
| 8 | 旧Service(compiler/sync)仍被调用 | 新旧逻辑并存 | P2 |

---

> **下一步**：基于本报告进行第二步「统一领域模型」，收敛所有测试资产到 TestAsset。
