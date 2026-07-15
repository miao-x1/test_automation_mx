# 架构重构执行计划：统一 Agent 版本 + 事件驱动广播模式

## 目标

1. **统一 Agent 架构**：以第三代 `runtime/` + `agents/`（AutoGen Core）为唯一标准，删除第一代和第二代代码
2. **改造执行模式**：从 Pipeline 线性串行改为事件驱动广播（Agent 订阅事件，排班发布任务事件后自动响应）
3. **排班主导**：SchedulerAgent 仍作为触发入口，但改为发布事件而非调用 Pipeline

---

## 当前问题概览

### 三代架构并存

| 代际 | 目录 | 基类 | 工厂 | 消息总线 | 编排器 |
|------|------|------|------|----------|--------|
| 第一代 | `agent/` (部分) | `base.py` (LegacyBaseAgent) | `factory.py` | `message_bus.py` (同步) | `task_orchestrator.py` |
| 第二代 | `agent_runtime/` | `base_agent.py` (BaseAgent) | `agent_runtime/factory.py` | `agent_runtime/message_bus.py` (异步) | `agent_runtime/orchestrator.py` |
| 第三代 | `runtime/` + `agents/` | `runtime/base_agent.py` (BaseRoutedAgent) | `agents/factory/` | `runtime/message_bus.py` (AutoGen) | `runtime/task_runtime.py` |

### 线性 Pipeline 现状

```
RequirementFlowService.generate() 线性调用：
  需求解析 → 脚本复用 → RAG检索 → 关系分析 → 图推理 → 用例生成 → 脚本生成 → 脚本执行 → 知识更新
```
每步串行等待上一步完成，无并行能力。

### 依赖关系图谱

**引用第一代 `agent/base.py` 的文件（21个）**：
- `agent/case/` 目录下全部 21 个 Agent 文件（api_extraction_agent, case_compiler_agent, case_generator, document_parser, image_parser, mindmap_agent, review_agent, script_generator_agent, storage_agent, swagger_parser 等）

**引用第一代 `agent/factory.py` 的文件（2个）**：
- `agent/__init__.py`、`services/task_service.py`

**引用第一代 `agent/message_bus.py` 的文件（7个）**：
- `agent/base.py`、`agent/base_agent.py`、`agent/rag_agent.py`、`agent/case_agent.py`、`agent/requirement_agent.py`、`agent/task_orchestrator.py`、`agent/__init__.py`

**引用第二代 `agent_runtime/` 的文件（3个外部）**：
- `api/testcase_generation.py`、`api/agent_runtime.py`、`agent/testcase/testcase_generator_agent.py`

**引用第三代 `runtime/` + `agents/` 的文件**：
- `api/graphflow.py`、`agents/flows/` 目录下全部 Agent

---

## 重构后的目标架构

### 事件驱动广播流程

```
SchedulerAgent (排班触发)
    │
    ▼ publishes "task.start" event
    │
EventBus (事件总线)
    │
    ├── RequirementAgent 订阅 "task.start"
    │     └── 处理完成 → publishes "requirement.parsed"
    │
    ├── ScriptReuseAgent 订阅 "requirement.parsed"  ┐
    │     └── 处理完成 → publishes "reuse.checked"   │ 并行
    ├── RAGAgent 订阅 "requirement.parsed"           │
    │     └── 处理完成 → publishes "rag.retrieved"  ┘
    │
    ├── RelationAgent 订阅 "rag.retrieved"
    │     └── 处理完成 → publishes "relation.analyzed"
    │
    ├── GraphAgent 订阅 "relation.analyzed"
    │     └── 处理完成 → publishes "graph.inferred"
    │
    ├── CaseAgent 订阅 "graph.inferred" + "rag.retrieved" + "reuse.checked"
    │     └── 处理完成 → publishes "case.generated"
    │
    ├── ScriptAgent 订阅 "case.generated"
    │     └── 处理完成 → publishes "script.generated"
    │
    ├── ExecutionAgent 订阅 "script.generated"
    │     └── 处理完成 → publishes "execution.completed"
    │
    ├── KnowledgeUpdateAgent 订阅 "execution.completed"
    │     └── 处理完成 → publishes "knowledge.updated"
    │
    └── CollectorAgent 收集所有结果 → 标记任务完成
```

**关键变化**：
- ScriptReuseAgent 和 RAGAgent 可**并行执行**（都订阅 `requirement.parsed`）
- CaseAgent 等待多个前置事件（扇入聚合）
- 每个 Agent 独立处理，通过事件解耦
- 排班只负责发布初始事件，不再编排具体流程

### 统一后的目录结构

```
backend/app/
├── runtime/                    # 唯一运行时（保留，增强）
│   ├── base_agent.py           # BaseRoutedAgent（唯一基类）
│   ├── runtime.py              # CoreRuntime
│   ├── collector.py            # CollectorAgent
│   ├── adapter.py              # LegacyAgentAdapter（过渡期保留）
│   ├── agent_registry.py       # AgentRegistry + AGENT_DEFINITIONS
│   ├── event_bus.py            # EventBus（增强：支持 Agent 级订阅）
│   ├── message_bus.py          # MessageBus（唯一消息总线）
│   ├── messages.py             # 消息类型定义
│   ├── task_runtime.py         # TaskRuntime
│   ├── graph_flow_manager.py   # GraphFlowManager（保留）
│   ├── broadcast_dispatcher.py # 【新增】广播调度器
│   └── event_types.py          # 【新增】事件类型与订阅规则定义
├── agents/                     # 唯一 Agent 实现
│   ├── factory/                # AgentFactory
│   └── flows/                  # 所有业务 Agent（扩充）
│       ├── requirement_agent.py      # 已有
│       ├── case_agent.py             # 已有
│       ├── review_agent.py           # 已有
│       ├── script_agent.py           # 已有
│       ├── export_agent.py           # 已有
│       ├── rag_query_agent.py        # 已有
│       ├── execution_flow_agent.py   # 已有
│       ├── report_agent.py          # 已有
│       ├── defect_agent.py          # 已有
│       ├── human_feedback_agent.py   # 已有
│       ├── graph_storage_agent.py    # 已有
│       ├── mysql_storage_agent.py    # 已有
│       ├── vector_storage_agent.py  # 已有
│       ├── page_knowledge_agent.py   # 已有
│       ├── image_agent.py           # 已有
│       ├── api_knowledge_agent.py   # 已有
│       ├── script_reuse_agent.py    # 【新增】从 agent/ 迁移
│       ├── relation_agent.py        # 【新增】从 agent/ 迁移
│       ├── graph_infer_agent.py     # 【新增】从 agent/ 迁移
│       ├── script_generator_agent.py # 【新增】从 agent/ 迁移
│       ├── execution_agent.py       # 【新增】从 agent/ 迁移
│       └── knowledge_update_agent.py # 【新增】从 agent/ 迁移
├── services/                   # 服务层（精简）
│   ├── requirement_flow_service.py  # 改造：从线性 Pipeline → 事件发布
│   └── task_service.py              # 改造：从 AgentFactory → EventBus 订阅
├── api/                        # API 层（更新导入）
├── agent/                      # 【删除】整个目录
└── agent_runtime/              # 【删除】整个目录
```

---

## 分阶段执行计划

### Phase 1: 建设事件驱动广播基础设施

**目标**：在不影响现有代码运行的前提下，新增广播调度基础设施。

#### 1.1 新增 `runtime/event_types.py` — 事件类型与订阅规则

定义事件类型枚举和订阅规则表：

```python
class TaskEventType:
    TASK_START = "task.start"
    REQUIREMENT_PARSED = "requirement.parsed"
    REUSE_CHECKED = "reuse.checked"
    RAG_RETRIEVED = "rag.retrieved"
    RELATION_ANALYZED = "relation.analyzed"
    GRAPH_INFERRED = "graph.inferred"
    CASE_GENERATED = "case.generated"
    SCRIPT_GENERATED = "script.generated"
    EXECUTION_COMPLETED = "execution.completed"
    KNOWLEDGE_UPDATED = "knowledge.updated"
    TASK_COMPLETED = "task.completed"

# 订阅规则：事件 → 订阅该事件的 Agent 列表
EVENT_SUBSCRIPTIONS = {
    "task.start": ["requirement_agent"],
    "requirement.parsed": ["script_reuse_agent", "rag_query_agent"],  # 并行
    "rag.retrieved": ["relation_agent"],
    "relation.analyzed": ["graph_infer_agent"],
    "graph.inferred": ["case_agent"],  # CaseAgent 需要等待多事件
    "case.generated": ["script_generator_agent"],
    "script.generated": ["execution_agent"],
    "execution.completed": ["knowledge_update_agent"],
    "knowledge.updated": [],  # 最终事件，由 Collector 处理
}
```

#### 1.2 新增 `runtime/broadcast_dispatcher.py` — 广播调度器

核心组件，替代线性 Pipeline 编排：

```python
class BroadcastDispatcher:
    """事件驱动广播调度器，替代线性 Pipeline"""

    async def dispatch_task(self, task_id, requirement, task_config):
        """排班触发入口：发布 task.start 事件"""
        # 1. 创建 CoreRuntime session
        # 2. 发布 TaskStartEvent 到事件总线
        # 3. 等待 CollectorAgent 收集最终结果

    async def on_event(self, event_type, event_data):
        """事件回调：根据事件类型触发下游 Agent"""
        # 1. 查 EVENT_SUBSCRIPTIONS 获取订阅 Agent 列表
        # 2. 对每个 Agent 发送 TaskMessage（通过 runtime.send_task）
        # 3. Agent 处理完成后自动发布下一个事件

    async def _wait_for_aggregation(self, task_id, required_events, timeout):
        """扇入聚合：等待多个并行 Agent 全部完成"""
        # CaseAgent 需要等待 graph.inferred + rag.retrieved + reuse.checked
```

#### 1.3 增强 `runtime/event_bus.py` — 支持 Agent 级事件订阅

现有 EventBus 仅按 `task_id` 订阅（给前端 SSE 用）。新增按 `event_type` 订阅的能力：

```python
class EventBus:
    # 现有：task_id → subscribers (前端 SSE)
    # 新增：event_type → agent_subscribers (Agent 间通信)

    async def subscribe_event(self, event_type, callback):
        """Agent 订阅特定事件类型"""

    async def publish_event(self, event_type, event_data):
        """发布事件，通知所有订阅该事件类型的 Agent"""
```

**涉及文件**：
- 新增：`runtime/event_types.py`
- 新增：`runtime/broadcast_dispatcher.py`
- 修改：`runtime/event_bus.py`（增强，不破坏现有接口）

**风险**：低。纯新增文件，不影响现有代码。

---

### Phase 2: 统一 Agent 基类到第三代

**目标**：将所有 Agent 统一到 `BaseRoutedAgent` 基类。

#### 2.1 迁移 `agent/case/` 目录（21个文件）

这些 Agent 当前继承 `agent/base.py`（LegacyBaseAgent），需迁移为 `BaseRoutedAgent` 子类。

**策略**：这些 Agent 属于旧的 L1/L2/L3 用例编译流水线，在新的广播架构中，部分功能已被 `agents/flows/` 中的 Agent 替代。处理方式：

| `agent/case/` 中的 Agent | 处理方式 | 原因 |
|--------------------------|----------|------|
| case_generator.py | 删除 | `agents/flows/case_agent.py` 已替代 |
| case_generator_v2.py | 删除 | 同上 |
| review_agent.py | 删除 | `agents/flows/review_agent.py` 已替代 |
| script_generator_agent.py | 逻辑迁移到 `agents/flows/script_generator_agent.py` | 无对应 Gen3 Agent |
| document_parser.py | 逻辑迁移到 `agents/flows/document_parser_agent.py` | 多模态输入解析需要 |
| image_parser.py | 逻辑迁移到 `agents/flows/image_parser_agent.py` | 同上（image_agent 已有但功能不同） |
| swagger_parser.py | 逻辑迁移到 `agents/flows/swagger_parser_agent.py` | API 测试需要 |
| schema_parser.py | 合并到 swagger_parser | API schema 解析 |
| api_extraction_agent.py | 逻辑迁移到 `agents/flows/api_extraction_agent.py` | API 测试需要 |
| requirement_understanding_agent.py | 删除 | `agents/flows/requirement_agent.py` 已替代 |
| rag_context_agent.py | 删除 | `agents/flows/rag_query_agent.py` 已替代 |
| retriever_agent.py | 删除 | 同上 |
| context_enricher_agent.py | 删除 | 功能合并到 requirement_agent |
| case_compiler_agent.py | 删除 | 旧流水线编译器，被广播模式替代 |
| test_normalization_agent.py | 逻辑迁移到 `agents/flows/test_normalization_agent.py` | 标准化功能仍需要 |
| execution_runner_agent.py | 删除 | `agents/flows/execution_flow_agent.py` 已替代 |
| framework_adapter_agent.py | 逻辑迁移到 `agents/flows/framework_adapter_agent.py` | 框架适配功能仍需要 |
| storage_agent.py | 删除 | `agents/flows/mysql_storage_agent.py` 等已替代 |
| video_parser.py | 逻辑迁移到 `agents/flows/video_parser_agent.py` | 视频解析功能 |
| mindmap_agent.py | 逻辑迁移到 `agents/flows/mindmap_agent.py` | 思维导图功能 |
| agent_selector.py | 删除 | 旧架构特有，新架构通过事件路由 |

**迁移步骤**（每个需要迁移的 Agent）：
1. 在 `agents/flows/` 下创建新文件
2. 继承 `BaseRoutedAgent`，添加 `@default_subscription`
3. 实现 `execute()` 方法，将原 Agent 的核心逻辑迁移过来
4. 用 `call_llm()` / `call_llm_json()` 替代旧版 LLM 调用
5. 用 `emit_start()` / `emit_end()` 替代旧版进度推送
6. 用 `publish_message()` 发布下游事件
7. 在 `AGENT_DEFINITIONS` 中注册新 Agent

#### 2.2 迁移 `agent/` 根目录 Agent（~30个文件）

这些 Agent 当前继承 `agent/base_agent.py`（第二代 BaseAgent），需迁移为 `BaseRoutedAgent`。

| `agent/` 中的 Agent | 处理方式 | 对应的 Gen3 Agent |
|---------------------|----------|-------------------|
| requirement_agent.py | 删除 | `agents/flows/requirement_agent.py` ✅ |
| case_agent.py | 删除 | `agents/flows/case_agent.py` ✅ |
| rag_agent.py | 删除 | `agents/flows/rag_query_agent.py` ✅ |
| execution_agent.py | 删除 | `agents/flows/execution_flow_agent.py` ✅ |
| feedback_agent.py | 删除 | `agents/flows/human_feedback_agent.py` ✅ |
| graph_agent.py | 迁移 | `agents/flows/graph_infer_agent.py` 【新建】 |
| relation_agent.py | 迁移 | `agents/flows/relation_agent.py` 【新建】 |
| script_reuse_agent.py | 迁移 | `agents/flows/script_reuse_agent.py` 【新建】 |
| script_generator.py | 迁移 | `agents/flows/script_generator_agent.py` 【新建】 |
| knowledge_update_agent.py | 迁移 | `agents/flows/knowledge_update_agent.py` 【新建】 |
| input_router.py | 迁移 | `agents/flows/input_router_agent.py` 【新建】 |
| fusion_agent.py | 迁移 | `agents/flows/fusion_agent.py` 【新建】 |
| router_agent.py | 删除 | 旧路由功能被事件订阅替代 |
| type_classifier.py | 迁移 | `agents/flows/type_classifier_agent.py` 【新建】 |
| element_agent.py | 迁移 | `agents/flows/element_agent.py` 【新建】 |
| element_merge_agent.py | 迁移 | `agents/flows/element_merge_agent.py` 【新建】 |
| embedding_agent.py | 迁移 | `agents/flows/embedding_agent.py` 【新建】 |
| retrieval_agent.py | 删除 | `agents/flows/rag_query_agent.py` 已替代 |
| graph_search_agent.py | 迁移 | `agents/flows/graph_search_agent.py` 【新建】 |
| page_crawler_agent.py | 迁移 | `agents/flows/page_crawler_agent.py` 【新建】 |
| playwright_agent.py | 迁移 | `agents/flows/playwright_agent.py` 【新建】 |
| page_state_manager.py | 迁移 | `agents/flows/page_state_manager.py` 【新建】 |
| script_parser.py | 迁移 | `agents/flows/script_parser_agent.py` 【新建】 |
| script_validator.py | 迁移 | `agents/flows/script_validator_agent.py` 【新建】 |
| script_executor.py | 迁移 | `agents/flows/script_executor_agent.py` 【新建】 |
| flow_parser.py | 迁移 | `agents/flows/flow_parser_agent.py` 【新建】 |
| flow_script_generator.py | 迁移 | `agents/flows/flow_script_generator.py` 【新建】 |
| strategy_agent.py | 迁移 | `agents/flows/strategy_agent.py` 【新建】 |
| mock_agent.py | 删除 | 测试用 Mock，不需要 |
| scheduler_agent.py | 改造 | 留在原位但改造为事件驱动（见 Phase 6） |
| task_executor.py | 改造 | 改为调用 BroadcastDispatcher（见 Phase 6） |
| executor_factory.py | 迁移 | `agents/flows/executor_factory.py` 【新建】 |
| config.py | 删除 | 配置统一到 `core/config.py` |
| prompt_builder.py | 迁移 | `agents/flows/prompt_builder.py` 【新建】 |
| type_classifier.py | 迁移 | 已列出 |

#### 2.3 更新 `AGENT_DEFINITIONS`

更新 `runtime/agent_registry.py` 中的 `AGENT_DEFINITIONS`：
- 删除所有指向 `app.agent.*` 的定义
- 新增指向 `app.agents.flows.*` 的定义
- 确保 50+ Agent 全部指向 Gen3 路径

**涉及文件**：
- 新增：`agents/flows/` 下约 20 个新 Agent 文件
- 修改：`runtime/agent_registry.py`
- 不修改旧文件（Phase 5 统一删除）

**风险**：中。新建文件不影响现有代码，但需确保业务逻辑正确迁移。

---

### Phase 3: 将线性 Pipeline 改造为事件驱动广播

**目标**：用 `BroadcastDispatcher` 替代 `RequirementFlowService` 的线性 Pipeline。

#### 3.1 改造 `services/requirement_flow_service.py`

**当前**：`generate()` 方法是 SSE 异步生成器，线性调用 9 个 Agent，逐阶段 `yield`。

**改造后**：

```python
class RequirementFlowService:
    async def generate(self, requirement, ...):
        """改造为事件驱动：发布 task.start 事件，等待完成"""
        dispatcher = get_broadcast_dispatcher()

        # 1. 创建 runtime session
        runtime = await get_core_runtime()
        session_key = f"task_{task_id}"
        await runtime.initialize()
        await runtime.start()

        # 2. 发布 task.start 事件，触发广播链
        await dispatcher.dispatch_task(
            task_id=task_id,
            requirement=requirement,
            task_config=task_config
        )

        # 3. 等待最终结果（CollectorAgent 聚合）
        result = await runtime.get_result(task_id, session_key, timeout=300)

        return result
```

**关键变化**：
- 不再逐阶段调用 Agent
- 不再 `yield` SSE 事件（改为通过 EventBus 推送）
- Agent 间通过事件自动串联
- 并行执行（ScriptReuse + RAG 同时运行）

#### 3.2 改造 `agent_runtime/orchestrator.py`（过渡期）

第二代 `TaskOrchestrator` 的 `run()` 和 `run_stream()` 方法改为调用 `BroadcastDispatcher`，保持 API 兼容：

```python
class TaskOrchestrator:
    async def run(self, task_type, input_data, ...):
        """过渡期：转发到 BroadcastDispatcher"""
        dispatcher = get_broadcast_dispatcher()
        return await dispatcher.dispatch_task(...)

    async def run_stream(self, ...):
        """过渡期：转发到 BroadcastDispatcher + EventBus 订阅"""
        dispatcher = get_broadcast_dispatcher()
        task_id = await dispatcher.dispatch_task(...)

        # 订阅 EventBus 获取实时事件
        bus = get_event_bus()
        subscriber = await bus.subscribe(task_id)
        async for event in subscriber.stream():
            yield event
```

#### 3.3 更新事件消息类型

在 `agents/messages/__init__.py` 中新增广播事件消息类型：

```python
class TaskStartEvent(FlowMessage):
    """任务启动事件"""
    requirement: str
    task_config: Dict

class RequirementParsedEvent(FlowMessage):
    """需求解析完成事件"""
    features: List[Dict]
    requirement_items: List[Dict]

class ReuseCheckedEvent(FlowMessage):
    """脚本复用检查完成事件"""
    reused_scripts: List[Dict]

class RAGRetrievedEvent(FlowMessage):
    """RAG 检索完成事件"""
    context: Dict
    retrieved_chunks: List[Dict]

# ... 其他事件类型
```

**涉及文件**：
- 修改：`services/requirement_flow_service.py`
- 修改：`agent_runtime/orchestrator.py`（过渡期兼容）
- 修改：`agents/messages/__init__.py`
- 新增：`runtime/broadcast_dispatcher.py`（Phase 1 已建）

**风险**：高。核心业务逻辑改造，需充分测试。

---

### Phase 4: 更新 API 层适配新架构

**目标**：所有 API 端点统一使用第三代架构。

#### 4.1 更新各 API 文件的导入

| API 文件 | 当前导入 | 改为 |
|----------|---------|------|
| `api/testcase_generation.py` | `from app.agent_runtime.orchestrator import get_task_orchestrator` | `from app.runtime.broadcast_dispatcher import get_broadcast_dispatcher` |
| `api/agent_runtime.py` | `from app.agent_runtime import ...` | `from app.runtime import ...` + `from app.agents.factory import ...` |
| `api/schedule.py` | `from app.agent.scheduler_agent import SchedulerAgent` | 保留（Phase 6 改造 SchedulerAgent） |
| `api/task.py` | 间接通过 `services/task_service.py` | `services/task_service.py` 更新后自动生效 |
| `api/multimodal_input.py` | `from app.agent.input_router import InputRouter` | `from app.agents.flows.input_router_agent import InputRouterAgent` |
| `api/script_upload.py` | `from app.agent.script_parser/validator/executor import ...` | `from app.agents.flows.script_parser_agent import ...` 等 |
| `api/graph.py` | `from app.agent.graph_agent import GraphAgent` | `from app.agents.flows.graph_infer_agent import GraphInferAgent` |
| `api/feedback.py` | `from app.agent.feedback_agent import FeedbackAgent` | `from app.agents.flows.human_feedback_agent import HumanFeedbackAgent` |
| `api/graphflow.py` | 已使用 `app.runtime` | 无需修改 |

#### 4.2 SSE 端点改造

所有 SSE 端点从"消费异步生成器"改为"订阅 EventBus"：

```python
# 改造前
async for event in orchestrator.run_stream(...):
    yield f"data: {event}\n\n"

# 改造后
bus = get_event_bus()
subscriber = await bus.subscribe(task_id)
async for event in subscriber.stream():
    yield f"data: {event}\n\n"
```

**涉及文件**：
- 修改：`api/testcase_generation.py`
- 修改：`api/agent_runtime.py`
- 修改：`api/multimodal_input.py`
- 修改：`api/script_upload.py`
- 修改：`api/graph.py`
- 修改：`api/feedback.py`
- 修改：`api/task.py`
- 修改：`services/task_service.py`

**风险**：中。API 层改动较多但模式统一。

---

### Phase 5: 删除旧版代码

**目标**：删除所有第一代和第二代代码，确保无残留引用。

#### 5.1 删除第一代文件

| 文件/目录 | 说明 |
|-----------|------|
| `agent/base.py` | 旧基类 LegacyBaseAgent |
| `agent/base_agent.py` | 第二代基类（已被 BaseRoutedAgent 替代） |
| `agent/factory.py` | 旧工厂（注意：`factory/` 目录包也需处理） |
| `agent/factory/` 目录 | 新版工厂（功能已迁移到 `agents/factory/`） |
| `agent/message_bus.py` | 旧同步消息总线 |
| `agent/message.py` | 旧消息对象 |
| `agent/task_orchestrator.py` | 旧 Pipeline 编排器 |
| `agent/orchestrator/` 目录 | 另一个编排器（功能已迁移到 broadcast_dispatcher） |
| `agent/case/` 目录 | 21个旧 Agent（已迁移或删除） |
| `agent/testcase/` 目录 | 旧测试用例 Agent（已迁移） |
| `agent/memory/` 目录 | 旧 Memory 模块（Gen3 不使用） |
| `agent/runtime/` 目录 | 旧 runtime（不是 `app/runtime/`） |
| `agent/config.py` | 旧配置 |
| `agent/exceptions.py` | 旧异常（统一到 `runtime/exceptions.py`） |
| `agent/types.py` | 旧类型定义 |
| `agent/prompt_builder.py` | 旧 Prompt 构建器 |
| `agent/__init__.py` | 清理所有旧导出 |

**保留的 `agent/` 目录文件**（Phase 6 改造后保留）：
- `agent/scheduler_agent.py` — 改造为事件驱动
- `agent/task_executor.py` — 改造为调用 BroadcastDispatcher

#### 5.2 删除第二代目录

| 文件/目录 | 说明 |
|-----------|------|
| `agent_runtime/` 整个目录 | 第二代架构（功能已迁移到 `runtime/`） |

#### 5.3 验证无残留引用

删除后用 Grep 搜索确认：
- 无 `from app.agent.base import` 残留
- 无 `from app.agent.factory import` 残留
- 无 `from app.agent.message_bus import` 残留
- 无 `from app.agent.message import` 残留
- 无 `from app.agent_runtime` 残留
- 无 `from app.agent.task_orchestrator import` 残留

**涉及文件**：
- 删除：上述所有文件和目录
- 修改：`agent/__init__.py`（清理导出）

**风险**：高。删除前必须确保所有引用已迁移。建议在 Phase 2-4 完成并测试通过后执行。

---

### Phase 6: 更新启动流程和调度集成

**目标**：SchedulerAgent 改为事件驱动，main.py 初始化新架构。

#### 6.1 改造 `agent/scheduler_agent.py`

**当前**：APScheduler 定时触发 → `TaskExecutor.execute()` → `RequirementFlowService.generate()`（线性 Pipeline）

**改造后**：APScheduler 定时触发 → `BroadcastDispatcher.dispatch_task()`（发布事件）

```python
class SchedulerAgent:
    async def _execute_schedule_task(self, task_id):
        # 1. 创建 ScheduleRunLog
        # 2. 获取 BroadcastDispatcher
        dispatcher = get_broadcast_dispatcher()
        # 3. 发布 task.start 事件（替代调用 Pipeline）
        result = await dispatcher.dispatch_task(
            task_id=task_id,
            requirement=task.task_config.get("requirement"),
            task_config=task.task_config
        )
        # 4. 更新 ScheduleRunLog 和 ScheduleTask
        # 5. 发送通知（通过 EventBus 发布完成事件）
```

#### 6.2 改造 `agent/task_executor.py`

```python
class TaskExecutor:
    async def execute(self, task, run_log, db):
        """改为调用 BroadcastDispatcher"""
        dispatcher = get_broadcast_dispatcher()
        result = await dispatcher.dispatch_task(
            task_id=str(task.id),
            requirement=task.task_config.get("requirement"),
            task_config=task.task_config
        )
        # 更新 run_log
```

#### 6.3 更新 `main.py` 启动流程

```python
# lifespan 启动顺序
1. 创建上传目录
2. 清理 Milvus 锁文件
3. init_db()
4. init_providers()
5. 【新增】初始化 CoreRuntime（initialize + start + register_all agents）
6. 【新增】初始化 BroadcastDispatcher
7. SchedulerAgent().start() — 改造后版本
8. TaskQueue().start()
9. ExecutionQueue.start()

# 关闭顺序
10. TaskQueue().stop()
11. ExecutionQueue.stop()
12. SchedulerAgent().stop()
13. 【新增】CoreRuntime.stop_when_idle()
14. Milvus client.close()
15. close_db()
```

**涉及文件**：
- 修改：`agent/scheduler_agent.py`
- 修改：`agent/task_executor.py`
- 修改：`main.py`

**风险**：高。启动流程变更影响全局，需确保初始化顺序正确。

---

## 执行顺序与依赖关系

```
Phase 1 (广播基础设施)
    │
    ▼
Phase 2 (统一 Agent 基类) ─── 可与 Phase 1 部分并行
    │
    ▼
Phase 3 (改造 Pipeline → 广播) ─── 依赖 Phase 1 + 2
    │
    ▼
Phase 4 (更新 API 层) ─── 依赖 Phase 3
    │
    ▼
Phase 6 (启动流程 + 调度) ─── 依赖 Phase 3 + 4
    │
    ▼
Phase 5 (删除旧代码) ─── 最后执行，依赖所有前置 Phase 完成
```

## 预估工作量

| Phase | 新增文件 | 修改文件 | 删除文件 | 预估复杂度 |
|-------|---------|---------|---------|-----------|
| Phase 1 | 2 | 1 | 0 | 中 |
| Phase 2 | ~20 | 1 | 0 | 高 |
| Phase 3 | 0 | 3 | 0 | 高 |
| Phase 4 | 0 | ~8 | 0 | 中 |
| Phase 5 | 0 | 1 | ~50+ | 低（删除操作） |
| Phase 6 | 0 | 3 | 0 | 高 |
| **总计** | **~22** | **~17** | **~50+** | |

## 验证策略

每个 Phase 完成后执行验证：

1. **Phase 1 验证**：单元测试 BroadcastDispatcher 的事件发布和订阅
2. **Phase 2 验证**：每个迁移的 Agent 能通过 `runtime.send_task()` 正常执行
3. **Phase 3 验证**：端到端测试 — 发布 task.start 事件，验证广播链完整执行
4. **Phase 4 验证**：API 端点返回正确响应，SSE 事件正常推送
5. **Phase 5 验证**：`grep -r "from app.agent.base" backend/` 无结果，`grep -r "from app.agent_runtime" backend/` 无结果
6. **Phase 6 验证**：排班定时触发 → 事件广播 → 结果收集 → 通知推送 完整流程

## 风险与缓解措施

| 风险 | 缓解措施 |
|------|---------|
| Agent 迁移过程中业务逻辑丢失 | 逐个 Agent 迁移，每个迁移后单独测试 |
| 事件驱动导致执行顺序错误 | 在 BroadcastDispatcher 中实现扇入聚合（等待多个前置事件） |
| 并行执行导致资源竞争 | 限制并行度，通过 asyncio.Semaphore 控制 |
| 删除旧代码后发现遗漏引用 | Phase 5 前用 Grep 全面搜索所有旧导入路径 |
| 启动流程变更导致服务无法启动 | Phase 6 最后执行，保留旧启动逻辑作为回退 |

## 注意事项

1. **过渡期兼容**：Phase 2-4 期间，新旧代码并存。`LegacyAgentAdapter` 可在过渡期包装旧 Agent，确保系统不中断
2. **数据库迁移**：本次重构不涉及数据库 Schema 变更，`agent_event`、`agent_result` 等表继续使用
3. **前端适配**：前端 SSE 订阅方式不变（仍通过 `task_id` 订阅 EventBus），但事件格式可能微调
4. **配置变更**：旧 `agent/config.py` 中的配置需迁移到 `core/config.py`
5. **排班系统**：`ScheduleTask` 和 `ScheduleRunLog` 表结构不变，仅改变触发后的执行方式
