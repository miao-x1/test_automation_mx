# UI-Automation 架构冻结文档

> 版本: 1.0.0  
> 日期: 2026-07-13  
> 状态: 架构冻结

---

## 一、系统整体架构

### 1.1 架构总览

```
┌──────────────────────────────────────────────────────────────────────┐
│                          用户 / 外部 AI 客户端                         │
│                   (浏览器 / Claude / Cursor via MCP)                  │
└───────────────────┬──────────────────────────────────┬───────────────┘
                    │                                  │
                    ▼                                  ▼
┌────────────────────────────────┐     ┌───────────────────────────────┐
│       Frontend (React 18)       │     │      MCP Server               │
│  Port 3000 · Vite + AntD 5     │     │  9个工具 (页面分析/用例生成     │
│  Zustand · SSE流式 · 50+路由    │     │  /脚本生成/测试执行)            │
│  31个Service模块                │     │  SSE/Streamable HTTP          │
└───────────────┬────────────────┘     └───────────────┬───────────────┘
                │ /api 代理 → :8000                     │
                ▼                                       ▼
┌──────────────────────────────────────────────────────────────────────┐
│                     Backend (FastAPI + Uvicorn)                       │
│                     Port 8000                                         │
│                                                                      │
│  ┌────────────────────────────────────────────────────────────┐      │
│  │  API 层 — 37 个路由模块                                     │      │
│  │  /tasks /executions /requirement /api-test /web            │      │
│  │  /api/v1/task/run/stream (SSE管道) /knowledge-center       │      │
│  │  /sessions /schedule /feedback /kb /graph /tri-store ...    │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  Service 层 — 业务服务                                      │      │
│  │  task_service / requirement_flow_service / reuse_service    │      │
│  │  execution/(redis_queue, http_runner, assertion_engine)     │      │
│  │  case/(pipeline, compiler_utils) assets/(asset_service)    │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  Task Orchestrator — 任务编排 (app/runtime/)                │      │
│  │  TaskRuntime → RuntimeManager → CoreRuntime                 │      │
│  │  三种执行模式: execute() / execute_sse() /                   │      │
│  │               execute_pipeline_sse() (13步管道)             │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  Agent Runtime — AutoGen Core 封装                          │      │
│  │  SingleThreadedAgentRuntime (消息驱动)                       │      │
│  │  AgentRegistry (45+ Agent 自动注册)                          │      │
│  │  LegacyAgentAdapter (旧版Agent适配)                         │      │
│  │  CollectorAgent (结果收集)                                   │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  Agent Factory — 工厂层 (app/agents/factory/)               │      │
│  │  DEFAULT_AGENT_SPECS → AgentSpec → AgentFactory            │      │
│  │  AgentLifecycleManager (状态机: registered→running→stopped) │      │
│  │  ModelRegistry (模型配置管理)                               │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  Agents — 45+ Agent 实例                                    │      │
│  │  Gen1: BaseAgent/NewBaseAgent (直接调用, app/agent/)        │      │
│  │  Gen2: BaseRoutedAgent (消息驱动, app/agents/flows/)         │      │
│  │  Gen3: GraphFlowManager (DAG驱动)                          │      │
│  └────────────────────────┬───────────────────────────────────┘      │
│                           │                                          │
│  ┌────────────────────────▼───────────────────────────────────┐      │
│  │  数据层 — 三库协同                                          │      │
│  │  MySQL (48个模型) + Milvus (3个集合) + Neo4j (图谱)         │      │
│  │  Redis (可选执行队列)                                       │      │
│  └────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 技术栈

| 层级 | 技术选型 | 版本 |
|---|---|---|
| 前端框架 | React + TypeScript | 18.2 / 5.3 |
| 前端构建 | Vite | 5.0 |
| UI 组件库 | Ant Design | 5.12 |
| 状态管理 | Zustand | 5.0 |
| 路由 | React Router | 6.21 |
| 后端框架 | FastAPI + Uvicorn | 0.109 / 0.27 |
| ORM | SQLAlchemy | 2.0.25 |
| 数据迁移 | Alembic | 1.13.1 |
| Agent 框架 | autogen-core | (未在requirements.txt声明) |
| 数据库 | MySQL 8.0 | pymysql 1.1.0 |
| 向量库 | Milvus (Lite/Standalone) | pymilvus |
| 图数据库 | Neo4j | neo4j 6.2.0 |
| 测试执行 | Playwright | 1.41.0 |
| LLM | 通义千问 / DeepSeek / Claude | qwen-plus / qwen-vl-max / qwen-coder-plus / deepseek-chat / claude-3.5-sonnet |

### 1.3 API 路由总览

| 路由前缀 | 文件 | 核心端点 |
|---|---|---|
| `/` | `health.py` | 健康检查 |
| `/auth` | `auth.py` | 登录/注册/Token刷新 |
| `/dashboard` | `dashboard.py` | 仪表盘统计 |
| `/tasks` | `task.py` | 创建/上传/列表/删除/重跑/分析(SSE) |
| `/executions` | `execution.py` | 运行/取消/重试/流式/报告/日志 |
| `/api/v1` | `agent_runtime.py` | `task/run`, `task/run/stream`(SSE管道), agents, workflows, classify |
| `/api/v1` | `testcase_generation.py` | testcase/generate, mindmap, CRUD |
| `/api/v1` | `context_api.py` | context/route, retrieve, preview, stats |
| `/api/v1/requirement-input` | `requirement_input.py` | parse, upload, generate(SSE) |
| `/requirement` | `requirement.py` | 需求驱动测试生成 |
| `/assets` | `assets_v2.py` | 测试资产CRUD + 发布 + 执行 |
| `/api-test` | `api_test/` (子包) | suite/execution/import/report |
| `/sessions` | `session_v2.py` | create/list/restore/run/artifacts |
| `/schedule` | `schedule.py` | CRUD + pause/resume/trigger + history |
| `/kb` | `kb.py` | 元素/用例/脚本知识库管理 |
| `/graph` | `graph.py` | build/sync/data/query/path/infer |
| `/rag` | `rag_v2.py` | upload/ingest/query/search/documents |
| `/knowledge-center` | `knowledge_center.py` | stats/collections/search(全文/语义/混合) |
| `/tri-store` | `tri_store.py` | 三库统一写入/查询/关系/摄取 |
| `/feedback` | `feedback.py` | submit/regenerate/stats |
| `/multimodal-input` | `multimodal_input.py` | upload_script/images, parse, fuse |
| `/graphflow` | `graphflow.py` | run/stream/graph/nodes/edges |

### 1.4 前端页面结构

| 模块 | 路由 | 页面文件 | 功能 |
|---|---|---|---|
| 仪表盘 | `/dashboard` | `Dashboard.tsx` | 项目总览统计 |
| 管理 | `/admin/*` | `admin/` (8个页面) | 用户/权限/项目/环境/数据源管理 |
| 需求中心 | `/requirement-center` | `requirement-center/` (5个文件) | 需求输入→AI分析→评审→最终化 |
| 需求管理 | `/requirement/*` | `requirement/` (7个页面) | 需求列表/创建/分析/分解/详情 |
| 上传中心 | `/upload-tasks` | `upload/UploadTaskCenter.tsx` | 多模态文件上传任务 |
| 测试设计 | `/test-design/*` | `test-design/` (8个文件) | AI生成/草稿/审查/发布/历史 |
| 接口测试 | `/api-test/*` | `api-test/` (10个页面) | 用例/套件/执行/报告/解析 |
| Web自动化 | `/web/*` | `web/` (9个页面) | 页面管理/设计/执行/报告/定时 |
| 执行中心 | `/execution/*` | `execution/ExecutionCenterPage.tsx` | 统一执行入口 |
| 知识中心 | `/knowledge` | `knowledge/KnowledgeCenter.tsx` | 知识库统计/集合/文档/搜索 |
| AI执行 | `/agent-runtime` | `agent-runtime/AgentRuntimePage.tsx` | SSE流式管道执行 |
| Agent监控 | `/agent-monitor` | `agent-monitor/AgentMonitorPage.tsx` | Agent注册表/执行日志 |
| 用例中心 | `/test-case/*` | `test-case/` (6个页面) | 用例生成/列表/导图/导出 |
| 会话管理 | `/sessions*` | `session/` (2个页面) | Session V1/V2 |
| 定时任务 | `/schedule*` | `SchedulePage.tsx` | 定时任务CRUD + 历史 |

### 1.5 前端 Service 层

| 类别 | Service文件 | 对接API |
|---|---|---|
| 认证 | `auth.ts` | `/auth/*` (httpOnly Cookie + Token刷新) |
| 任务 | `task.ts` | `/tasks/*`, `/executions/*` |
| 需求 | `requirement.ts`, `requirementCenter.ts`, `requirementInput.ts` | `/requirement/*`, SSE流 |
| API测试 | `apiCase.ts`, `apiExec.ts`, `apiReport.ts`, `apiSuite.ts` | `/api-test/*` |
| 知识库 | `kb.ts`, `knowledgeCenter.ts`, `rag.ts`, `graph.ts` | `/kb/*`, `/knowledge-center/*`, `/rag/*`, `/graph/*` |
| Agent | `agentRuntime.ts`, `agentMonitor.ts` | `/api/v1/*` (SSE流) |
| 执行 | `executionAnalysis.ts`, `feedback.ts` | `/executions/*`, `/feedback/*` |
| 资产 | `asset.ts`, `case.ts` | `/assets/*`, `/case/*` |
| 其他 | `schedule.ts`, `session.ts`, `multimodalInput.ts`, `scriptUpload.ts`, `pageRelation.ts`, `contextService.ts`, `threeLayer.ts`, `testcaseGeneration.ts` | 各自路由 |
| 纯前端 | `taskTypeDetector.ts` | 本地关键词推断测试类型 |

---

## 二、核心业务流程

### 2.1 完整管道流程 (web_test, 13步)

用户从 AI执行页面（`/agent-runtime`）提交需求后，系统执行以下 13 步管道：

```
用户输入需求 (文本/图片/PDF/Swagger/视频/SQL)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 入口层                                                        │
│                                                               │
│  ① TestTypeClassifierAgent — 测试类型智能识别                   │
│     输入: 需求文本                                              │
│     输出: test_type(web/api/android/performance)               │
│           platform / framework                                 │
│     方式: 规则引擎 + LLM 混合分类                                │
│     路由: test_type → workflow_name 映射                        │
│                                                               │
│  ② ReuseService.quick_check() — 快速预检复用                    │
│     输入: 需求文本                                              │
│     阈值: 0.95 (高于此值直接复用, 跳过全部后续步骤)                │
│     方式: Milvus 向量相似度检索                                  │
└───────────────────────┬─────────────────────────────────────┘
                        │ (未命中复用)
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 需求理解层                                                     │
│                                                               │
│  步骤1: requirement_agent — 需求解析                            │
│    action: analyze                                            │
│    输入: 原始需求文本                                           │
│    输出: {intent, steps[], test_scope, pages[]}               │
│    LLM: qwen-plus                                             │
│    output_key: requirement_analysis                           │
│                                                               │
│  ★ ReuseService.check_reuse() — 精确复用检查                   │
│    输入: requirement_analysis (intent + steps)                 │
│    阈值: 0.90                                                  │
│    命中则跳过步骤3-7, 直接进入步骤8                              │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 上下文增强层                                                   │
│                                                               │
│  步骤2: rag_agent — RAG向量检索                                │
│    从Milvus检索历史元素/用例/脚本                                │
│    output_key: rag_context                                    │
│                                                               │
│  步骤3: relation_agent — 页面关系发现                           │
│    分析页面间导航/数据流转关系                                    │
│    output_key: relation_context                               │
│                                                               │
│  步骤4: graph_agent — 图谱推理                                  │
│    从Neo4j推理页面关系和业务流程                                  │
│    output_key: graph_context                                  │
│                                                               │
│  步骤5: flow_parser — 流程解析                                  │
│    解析业务流程, 提取页面跳转路径                                 │
│    output_key: flow_context                                   │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 用例生成层                                                     │
│                                                               │
│  步骤6: case_agent — 用例生成                                  │
│    action: generate                                           │
│    输入: requirement_analysis + rag_context + relation_context │
│          + graph_context                                      │
│    输出: CaseResult (统一用例模型)                               │
│    LLM: deepseek-chat                                         │
│    output_key: test_cases                                     │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 脚本生成层 (4级降级链)                                         │
│                                                               │
│  步骤7: script_generator — 脚本生成                             │
│    action: generate                                          │
│    输入: test_cases + rag_context + graph_context + flow_context│
│    LLM: qwen-coder-plus                                      │
│                                                               │
│    降级策略:                                                   │
│      Level 0: StrategyAgent 策略选择 → 生成                    │
│      Level 1: FlowScriptGenerator 跨页面脚本生成                │
│      Level 2: RAG + LLM 检索增强生成                           │
│      Level 3: Template 模板填充                                │
│    output_key: test_script (dict, 含 script_content)          │
└───────────────────────┬─────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────┐
│ 后脚本流程                                                     │
│                                                               │
│  步骤8: storage_agent — 脚本存储                               │
│    required: False                                            │
│    ① 保存脚本到MySQL Script表                                   │
│    ② EmbeddingAgent → Milvus向量化入库                         │
│    ③ KnowledgeUpdateAgent → Neo4j知识更新                      │
│    output_key: storage_result                                 │
│                                                               │
│  步骤9: execution_agent — 脚本执行                             │
│    action: execute_script                                     │
│    param_mapping: test_script → script_content                │
│    通过subprocess运行pytest                                    │
│    解析 ##TEST_PASS## / ##TEST_FAIL## 标记                     │
│    失败时截图                                                  │
│    output: {total, passed, failed_count, log_content, ...}    │
│    output_key: execution_result                                │
│                                                               │
│  步骤10: report_agent — 测试报告生成                           │
│    required: False                                             │
│    生成 HTML + JSON 报告                                       │
│    保存到 reports/ 目录                                        │
│    output_key: report_result                                  │
│                                                               │
│  步骤11: defect_agent — 缺陷分析                                │
│    required: False                                             │
│    从execution_result提取失败用例                               │
│    正则匹配 ##TEST_FAIL## 和 FAILED 行                         │
│    提取: defect_id, error_type, severity, traceback            │
│    output_key: defect_result                                  │
│                                                               │
│  步骤12: feedback_agent — 失败分析/反馈                        │
│    param_mapping: execution_result → exec_result              │
│    LLM分析失败原因, 给出改进建议和质量评分                       │
│    LLM: claude-3.5-sonnet                                     │
│    output_key: analysis_result                                 │
│                                                               │
│  步骤13: flow_export_agent — 结果导出                          │
│    required: False                                             │
│    汇总脚本+报告+缺陷+分析                                      │
│    保存到MySQL flow_result表                                   │
│    output_key: export_result                                  │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据流转关系

管道通过 `context` 字典在步骤间传递数据，每个步骤的 `output_key` 存入 context，后续步骤通过 `input_keys` 取值：

```
requirement_analysis ──→ rag_agent (input)
                    ├──→ relation_agent (input)
                    ├──→ graph_agent (input)
                    ├──→ flow_parser (input)
                    └──→ case_agent (input)

rag_context ──→ case_agent (input)
             └──→ script_generator (input)

relation_context ──→ case_agent (input)

graph_context ──→ case_agent (input)
              └──→ script_generator (input)

flow_context ──→ script_generator (input)

test_cases ──→ script_generator (input)

test_script ──→ storage_agent (input)
             └──→ execution_agent (input, via param_mapping+extract_fields)

execution_result ──→ report_agent (input)
                  ├──→ defect_agent (input)
                  └──→ feedback_agent (input, via param_mapping)

report_result ──→ flow_export_agent (input)
defect_result ──→ flow_export_agent (input)
analysis_result ──→ flow_export_agent (input)
```

`__pipeline_meta__` 注入机制：管道第一步携带 `{task_id, session_id, requirement, execution_id, script_content}`，通过 `defaults: {"task_id": "__meta__.task_id"}` 语法在各步骤中按需提取。

### 2.3 多入口路径

除管道外，系统还存在两条替代路径，均最终委托到管道执行：

| 入口 | 触发方式 | 流程 |
|---|---|---|
| Agent Runtime 页面 | 用户提交需求 | `build_pipeline_steps()` → `execute_pipeline_sse()` |
| 需求功能服务 (Gen1) | `RequirementFlowService.generate()` | `classify_sync()` → `quick_check()` → `check_reuse()` → `execute_pipeline_sse()` |
| GraphFlow | `/graphflow/run` | `GraphFlowManager` DAG拓扑 → `FlowNodeAdapter` 包装 Agent |

### 2.4 SSE 事件流

前端通过 `fetch` + `ReadableStream` 接收 SSE 事件，格式为 `data: {json}\n\n`：

| 事件 | 触发时机 | 数据 |
|---|---|---|
| `pipeline_start` | 管道开始 | session_id, total_steps |
| `step_start` | 步骤开始 | step(索引), agent_type, action |
| `step_progress` | 步骤中间进度 | step, progress, message |
| `step_completed` | 步骤完成 | step, duration, data(输出) |
| `step_failed` | 步骤失败 | step, error |
| `pipeline_completed` | 管道完成 | session_id, context(全部输出) |
| `reuse_hit` | 复用命中 | similarity, script_name, check_type |
| `reuse_missed` | 复用未命中 | similarity, check_type |
| `done` | 结束 | status |

---

## 三、Agent 架构

### 3.1 Agent 注册

注册流程从 `definitions.py` 的 `DEFAULT_AGENT_SPECS` 列表开始，自动生成注册表，无需手动编写：

```
DEFAULT_AGENT_SPECS (definitions.py, 45+ 条 AgentSpec)
        │
        ▼ _build_definitions_from_specs()
        │  (过滤 enabled=False, 转换为 AgentDefinition)
        ▼
AGENT_DEFINITIONS (agent_registry.py, 自动生成)
        │
        ▼ AgentRegistry.__init__()
        │  (加载全部定义到 _definitions 字典)
        ▼
RuntimeManager._register_all_agents()
        │  (遍历全部定义, 调用 CoreRuntime.register_agent_type)
        ▼
CoreRuntime.register_agent_type(agent_type, agent_class, factory)
        │
        ├── 如果 agent_class 继承 RoutedAgent:
        │     直接注册到 SingleThreadedAgentRuntime
        │     (BaseRoutedAgent 子类: Gen2 Flow Agent)
        │
        └── 如果 agent_class 不继承 RoutedAgent:
              用 LegacyAgentAdapter 包装后注册
              (NewBaseAgent / BaseAgent 子类: Gen1 Agent)
```

`AgentSpec` 包含完整配置：`name`, `display_name`, `description`, `module_path`, `class_name`, `model`(ModelConfig), `system_prompt`, `tools`, `capabilities`, `enabled`。新增 Agent 只需在此列表添加一条记录，Factory 和 Registry 自动处理。

### 3.2 Agent 创建

Agent 实例创建采用懒加载策略，首次使用时才真正 import 和实例化：

```
任务到达 → AgentRegistry._load_agent_class(agent_type)
             │
             ├── 已缓存 (_loaded_classes) → 直接返回
             │
             └── 未缓存 → importlib.import_module(module_path)
                          → getattr(module, class_name)
                          → 缓存到 _loaded_classes
                          → 返回 class
           │
           ▼ _create_factory(agent_type)
             │
             ├── 创建 factory 函数:
             │     factory = lambda: agent_class(**init_kwargs)
             │
             ▼
           CoreRuntime.register_agent_type(type, class, factory)
             │
             ├── RoutedAgent 子类:
             │     runtime.register_factory(type, factory)
             │
             └── 非 RoutedAgent:
                   LegacyAgentAdapter(agent_class) 包装
                   → adapter 内部 _get_agent() 懒加载实例化
```

`AgentFactory`（`app/agents/factory/factory.py`）提供统一的 Agent 创建入口，管理模型配置和初始化参数。`LegacyAgentAdapter` 在 `__init__` 中保存 agent_class 和 init_kwargs，在 `_get_agent()` 中延迟创建实例。

### 3.3 Agent 生命周期

`AgentLifecycleManager`（`app/agents/factory/lifecycle.py`）管理 Agent 状态转换：

```
                  register()
                      │
                      ▼
               ┌─────────────┐
               │ registered  │  Agent 定义已加载, 类未实例化
               └──────┬──────┘
                      │ initialize(runtime)
                      ▼
               ┌─────────────┐
               │ initialized │  Agent 实例已创建, 准备执行
               └──────┬──────┘
                      │ execute(action, payload)
                      ▼
               ┌─────────────┐
               │   running   │  正在执行任务
               └──┬──────┬───┘
                  │      │ 异常
                  │      ▼
                  │ ┌─────────┐
                  │ │  error  │  执行出错, 记录错误信息
                  │ └─────────┘
                  │ shutdown()
                  ▼
               ┌─────────────┐
               │   stopped    │  已停止, 资源已释放
               └─────────────┘
```

状态查询通过 `get_state(agent_name)` 返回当前状态。`get_all_states()` 返回全部 Agent 的状态快照，用于 `/api/v1/agents/registry` 监控接口。

### 3.4 Agent 通信机制

所有 Agent 间通信通过消息完成，禁止直接实例化其他 Agent。消息类型定义在 `app/runtime/messages.py`：

```
┌──────────────┐                         ┌──────────────┐
│   FastAPI    │                         │  Collector   │
│  TaskRuntime │                         │    Agent     │
└──────┬───────┘                         └──────▲───────┘
       │                                      │
       │ send_task()                          │ ResultMessage
       │ TaskMessage                          │ (最终结果)
       ▼                                      │
┌──────────────┐    AgentRequest     ┌───────┴───────┐
│   Agent A    │ ──────────────────→ │    Agent B    │
│ (BaseRouted) │ ←────────────────── │ (BaseRouted)  │
│              │    AgentResponse    │               │
└──────┬───────┘                     └───────────────┘
       │
       │ publish_message()
       │ ProgressMessage (进度推送 → SSE → 前端)
       │ AgentEventMessage (详细事件 → Collector)
       │ ErrorMessage (错误通知 → SSE → 前端)
       ▼
┌──────────────┐
│  Event Bus   │ → SSE → 前端实时展示
└──────────────┘
```

| 消息类型 | 方向 | 用途 |
|---|---|---|
| `TaskMessage` | FastAPI → Agent | 启动任务，携带 task_id, action, payload |
| `AgentRequest` | Agent → Agent | 请求另一个 Agent 的服务 |
| `AgentResponse` | Agent → Agent | 响应请求，携带 status, data, duration |
| `ProgressMessage` | Agent → 前端 | 进度推送，通过 SSE 到前端 |
| `ResultMessage` | Agent → Collector | 最终结果投递，Collector 汇总写入数据库 |
| `ErrorMessage` | Agent → 前端 | 错误通知 |
| `AgentEventMessage` | Agent → Collector | 详细事件（Prompt/Model/Token/重试等） |
| `TaskStatusMessage` | Collector → 前端 | 任务状态变更通知 |

### 3.5 Agent 分层清单

#### Gen1: 核心业务 Agent（`app/agent/`, 基类 NewBaseAgent）

| Agent | 文件 | LLM | 用途 |
|---|---|---|---|
| RequirementAgent | `requirement/requirement_agent.py` | qwen-plus | 解析需求，提取意图/步骤 |
| ElementAgent | `vision/element_agent.py` | qwen-vl-max | 视觉模型分析页面截图 |
| ScriptGenerator | `script/script_generator.py` | qwen-coder-plus | 生成 Playwright 脚本 |
| ExecutionAgent | `execution/execution_agent.py` | qwen-plus | 执行脚本，收集结果 |
| CaseAgent | `case/case_agent.py` | deepseek-chat | 生成结构化测试用例 |
| RAGAgent | `rag/rag_agent.py` | text-embedding-v3 | 向量检索历史数据 |
| GraphAgent | `graph/graph_agent.py` | - | Neo4j 图谱推理 |
| StorageAgent | `storage/storage_agent.py` | - | 脚本入库 + 向量化 + 知识更新 |
| FeedbackAgent | `feedback/feedback_agent.py` | claude-3.5-sonnet | 失败分析，质量评估 |
| StrategyAgent | `script/strategy_agent.py` | deepseek-chat | 脚本生成策略选择 |
| ScriptReuseAgent | `script/script_reuse_agent.py` | qwen-plus | 脚本复用判断 |
| TestTypeClassifierAgent | `requirement/test_type_classifier_agent.py` | qwen-plus | 测试类型智能识别 |

#### Gen1: 需求解析 Agent（`app/agent/requirement/parsers/`, 基类 BaseRoutedAgent）

| Agent | LLM | 用途 |
|---|---|---|
| InputRouterAgent | qwen-plus | 按输入类型路由到对应解析Agent |
| PDFParserAgent | qwen-plus | PDF 文档解析 |
| ImageAnalyzerAgent | qwen-vl-max | UI 截图分析 |
| VideoAnalyzerAgent | qwen-vl-max | 视频关键帧分析 |
| SwaggerParserAgent | qwen-plus | Swagger/OpenAPI 解析 |
| DatabaseSchemaAgent | qwen-plus | SQL DDL 表结构解析 |

#### Gen2: Flow Agent（`app/agents/flows/`, 基类 BaseRoutedAgent）

| Agent | 用途 |
|---|---|
| RequirementAgent | 消息驱动需求解析 |
| ImageAgent | 页面元素分析 |
| CaseAgent | 用例生成 |
| ReviewAgent | 用例审查 |
| ScriptAgent | 脚本生成 |
| ExportAgent | 结果导出 |
| ReportAgent | 测试报告生成 |
| DefectAgent | 缺陷分析 |
| RAGQueryAgent | 统一上下文查询 |
| ExecutionFlowAgent | 消息驱动脚本执行 |
| MysqlStorageAgent | 统一 MySQL 写入 |
| VectorStorageAgent | 统一 Milvus 操作 |
| GraphStorageAgent | 统一 Neo4j 操作 |
| PageKnowledgeAgent | 截图→OCR→元素→三库存储 |
| APIKnowledgeAgent | Swagger/Postman 解析→三库存储 |

#### Gen1: 用例与测试用例 Agent

| Agent | 基类 | 用途 |
|---|---|---|
| CaseGeneratorAgent | BaseAgent | V2 用例生成（RAG增强） |
| ReviewAgent | BaseAgent | 用例审查 |
| MindMapAgent | BaseAgent | 用例脑图 |
| RequirementAnalysisAgent | NewBaseAgent | 测试需求解析 |
| TestPointAnalysisAgent | NewBaseAgent | 测试点分析 |
| TestCaseGeneratorAgent | NewBaseAgent | 用例生成 |
| TestCaseReviewAgent | NewBaseAgent | 用例审核 |

---

## 四、数据库设计

### 4.1 MySQL — 业务数据库

存储全部业务关系数据，48 个 SQLAlchemy 模型，通过 pymysql 连接（连接池 pool_size=10, max_overflow=20）。

| 领域 | 核心模型 | 说明 |
|---|---|---|
| 用户 | `User`, `UserRole`, `Workspace` | 用户认证与多工作空间 |
| 任务 | `Task`, `TaskStatus`, `InputMode`, `TaskType` | 测试任务管理 |
| 测试资产 | `TestAsset`, `ApiCase`, `ApiCaseFolder`, `TestSuite` | 三套资产体系并存 |
| 用例 | `CaseContent`, `CaseTask`, `CaseMindmap`, `CaseResult` | 测试用例管理 |
| 执行 | `ExecutionRecord`, `ExecutionStatus` | 执行记录与状态 |
| 需求 | `RequirementTask`, `RequirementInput`, `RequirementSession` | 需求管理与会话 |
| 知识库 | `KnowledgeSource`, `KnowledgeChunk`, `RetrievalLog` | 文档知识管理 |
| 页面 | `PageElement`, `PageKnowledge`, `PageRelation`, `UIElement` | 页面元素与关系 |
| 图谱 | `FlowResult`, `MindMap` | 流程结果与脑图 |
| 会话 | `Session`, `SessionEvent`, `SessionArtifact` | Agent 会话管理 |
| Agent | `AgentResult`, `AgentEvent`, `AgentExecutionLog`, `AgentRegistry` | Agent 执行记录 |
| 脚本 | `Script` | 生成的自动化脚本 |
| 定时 | `ScheduleTask`, `ScheduleRunLog` | 定时任务调度 |
| 反馈 | `Feedback` | 用户反馈 |
| 测试用例 | `TestRequirement`, `TestPoint`, `TestCase`, `TestCaseReview` | 用例生成流程 |

数据库迁移通过 Alembic 管理，共 22 个迁移版本，从 `001_init_tables` 到 `017_add_task_classification_fields`，外加 `r2r_add_knowledge_tables`、`tc001_add_testcase_tables` 等专项迁移。

### 4.2 Milvus — 向量语义库

存储文本向量，用于语义检索和脚本复用判断。支持 Milvus Lite（嵌入式，开发环境）和 Milvus Standalone（生产环境，需 Docker 部署）两种模式。客户端采用单例模式 + 线程锁 + 延迟初始化。

| 集合名 | 存储内容 | 向量维度 | 用途 |
|---|---|---|---|
| `ui_element_vector` | UI 元素描述向量 | 1024 | 元素检索，匹配页面元素 |
| `test_case_vector` | 测试用例描述向量 | 1024 | 用例检索，历史用例复用 |
| `scriptVector` | 脚本内容向量 | 1024 | 脚本复用，相似度判断（阈值 0.90/0.95） |

向量嵌入使用通义千问 `text-embedding-v3` 模型（DashScope provider），维度 1024。

数据写入时机：
- 脚本存储步骤（`StorageAgent.store()`）：脚本生成后立即入库
- RAG 索引接口（`/rag/index`）：手动批量索引
- 知识更新步骤（`KnowledgeUpdateAgent`）：执行后自动更新

数据查询时机：
- 脚本复用检查（`ReuseService.quick_check` / `check_reuse`）
- RAG 检索步骤（`RAGAgent.retrieve()`）
- 知识中心搜索（`/knowledge-center/search/semantic`）

### 4.3 Neo4j — 关系图谱

存储页面关系和业务流程图谱，用于推理页面间导航路径和数据流转。客户端采用 bolt 协议连接，连接失败时启动冷却机制（降级为跳过图谱步骤，不阻断主流程）。

| 节点类型 | 属性 | 说明 |
|---|---|---|
| `Page` | url, title, screenshot | 页面节点 |
| `Element` | locator, type, text | UI 元素节点 |
| `TestCase` | title, steps | 测试用例节点 |
| `Script` | name, content | 脚本节点 |

| 关系类型 | 方向 | 说明 |
|---|---|---|
| `HAS_ELEMENT` | Page → Element | 页面包含元素 |
| `NAVIGATE_TO` | Page → Page | 页面导航关系 |
| `TRIGGER` | Element → Page | 元素触发页面跳转 |
| `USES` | TestCase → Element | 用例使用元素 |
| `GENERATES` | TestCase → Script | 用例生成脚本 |

数据写入时机：
- 图谱构建接口（`/graph/build`）
- 知识更新步骤（`KnowledgeUpdateAgent`）
- 页面关系发现（`RelationAgent.discover()`）

数据查询时机：
- 图谱推理步骤（`GraphAgent.reason()`）
- 页面路径查询（`/graph/path`）
- 业务流程分析（`/graph/business-flows`）

### 4.4 Redis — 执行队列（可选）

通过 `REDIS_ENABLED` 控制启用，当前配置为 `False`（未启用）。用于接口测试异步执行队列，`TaskQueue` 管理 3 个 worker。

---

## 五、当前存在的问题

### 5.1 严重问题

| 编号 | 问题 | 影响 | 根因 |
|---|---|---|---|
| S-01 | 三套 Agent 体系并存 | 代码重复，维护成本高，新人理解困难 | Gen1(BaseAgent) → Gen2(BaseRoutedAgent) → Gen3(GraphFlowManager) 渐进演进，未完成统一迁移 |
| S-02 | 三套测试资产体系重叠 | 同一用例可能存在于 CaseContent / ApiCase / TestAssetV2 三处，数据不一致 | 不同业务模块独立设计资产模型，未统一 |
| S-03 | 凭据泄露风险 | `.env` 包含真实数据库密码和 API Key，`alembic.ini` 硬编码连接串含密码 | 安全意识不足，配置管理不规范 |
| S-04 | requirements.txt 依赖不完整 | `pymilvus`、`redis`、`autogen-core` 等核心库未声明，新环境部署失败 | 手动安装后未更新依赖清单 |
| S-05 | 无容器化部署 | 无法快速部署，环境一致性问题 | 无 Dockerfile / docker-compose |
| S-06 | 前端 SSE 事件格式不统一 | 管道级事件（`event`字段）和旧版事件（`event_type`字段）共存，前端需同时兼容 | 管道系统新增时未统一事件格式 |

### 5.2 中等问题

| 编号 | 问题 | 影响 |
|---|---|---|
| M-01 | 测试非标准化 | 测试文件为独立脚本（`asyncio.run(main())`），未使用 pytest 框架，无覆盖率报告 |
| M-02 | 无 CI/CD 配置 | 无 GitHub Actions / GitLab CI，代码变更无自动化验证 |
| M-03 | 多 API 前缀混合 | `/api/*`、`/api/v1/*`、`/api/v1/requirement-input/*` 三种前缀共存，前端代理需统一处理 |
| M-04 | 旧路由大量重定向 | 20+ 个旧路由通过 `<Navigate>` 重定向到新路由，增加路由表复杂度 |
| M-05 | LLM 模型分散管理 | 5 个不同模型分散在各 AgentSpec 中，无统一模型配置中心 |
| M-06 | Gen1 与 Gen2 同名 Agent 并存 | `RequirementAgent`、`CaseAgent`、`ReviewAgent` 等在 `app/agent/` 和 `app/agents/flows/` 各有一份 |
| M-07 | `app/agent_runtime/` 残留 | 仅 `__pycache__`，无 `.py` 源文件，但目录仍存在 |
| M-08 | 数据库连接串两处配置 | `alembic.ini` 和 `.env` 各维护一份，可能不一致 |

### 5.3 优化问题

| 编号 | 问题 | 建议 |
|---|---|---|
| O-01 | Agent 注册表缺少运行时禁用 | `enabled=False` 在 Spec 层面过滤，运行时无法动态禁用 |
| O-02 | `execute_pipeline()`（非SSE版）与 SSE 版功能不完全对齐 | 非 SSE 版虽然已添加 `required: False` 支持，但缺少管道级事件发送 |
| O-03 | 前端状态管理仅一个 Store | `uploadStore.ts` 仅管理上传任务，其他状态散落在各页面 `useState` 中 |
| O-04 | 错误处理不够统一 | 各 Agent 的 error 返回格式不一致，有的返回 `{"status": "error"}`，有的抛异常 |
| O-05 | 文档分散 | 设计文档在 `docs/design/` 下 9 个子目录，与 `backend/docs/` 存在重叠 |
| O-06 | 日志未结构化 | 使用 loguru 但未配置 JSON 格式化，不利于日志聚合分析 |
| O-07 | 缺少 API 限流 | 无 rate limiting，LLM 调用可能被滥用 |

---

## 六、后续优化路线

### 第一阶段: 安全与部署（优先）

1. 清理凭据：`alembic.ini` 改为从环境变量读取连接串，`.env` 添加到 `.gitignore`（已添加），删除硬编码密码
2. 补全 `requirements.txt`：添加 `pymilvus`、`redis`、`autogen-core` 等缺失依赖
3. 容器化：编写 `Dockerfile`（后端）和 `docker-compose.yml`（MySQL + Milvus + Neo4j + 后端 + 前端）
4. 添加 CI 配置：GitHub Actions 自动运行测试和构建

### 第二阶段: 架构统一

5. 统一 Agent 体系：将 Gen1 Agent 逐步迁移为 BaseRoutedAgent 子类，删除 LegacyAgentAdapter，最终消除 `app/agent/` 与 `app/agents/` 的二分
6. 统一测试资产模型：将 `CaseContent` / `ApiCase` / `TestAssetV2` 合并为单一 `TestAsset` 模型，迁移历史数据
7. 统一 API 前缀：全部归入 `/api/v1/`，删除旧前缀
8. 统一 SSE 事件格式：全部使用 `{"event": "...", "data": {...}}` 格式，删除 `event_type` 兼容代码
9. 清理残留：删除 `app/agent_runtime/` 目录、清理旧路由重定向

### 第三阶段: 质量提升

10. 引入 pytest 框架：将测试文件迁移为 pytest 用例，添加 `conftest.py` 和 `pytest.ini`，配置覆盖率报告
11. 统一错误处理：定义标准错误响应模型，所有 Agent 遵循同一错误格式
12. 结构化日志：配置 loguru JSON 格式化，添加 request_id 追踪
13. API 限流：为 LLM 相关接口添加 rate limiting
14. 前端状态管理优化：将 Agent Runtime 页面的状态提取为独立 Store

### 第四阶段: 性能与可观测性

15. Agent 执行并行化：步骤 10/11/12（报告/缺陷/反馈）无数据依赖，可改为并行执行
16. LLM 调用缓存：对相同输入缓存 LLM 结果，降低成本
17. 添加 OpenTelemetry 追踪：分布式追踪 Agent 执行链路
18. 添加 Prometheus 指标：监控 Agent 执行时间、成功率、LLM 调用次数
