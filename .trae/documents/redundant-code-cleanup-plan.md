# 冗余代码清理执行计划

## Summary

清理 `backend/app/` 下约 60+ 对新旧版本重叠文件：删除 24 个冗余文件，新增 5 个提取文件，重命名合并 3 对 API 文件，更新约 20 个引用文件。覆盖 services/、models/、api/、retrieval/rag/、prompts/context/ 五大层面。与已有 REFACTOR_PLAN.md（Agent 架构统一）协调执行。

## Current State Analysis

### 审查发现的关键事实（与原始判断的修正）

| 原始判断 | 实际状态 | 影响 |
|---------|---------|------|
| `task_service.py` 是 `unified_task_service.py` 的子集 | **非子集**：TaskService 有 8 方法（含 get/list/update/delete/rerun），UnifiedTaskService 仅 5 方法（含 create+run）。互补关系 | 需合并而非删除 |
| `services/workflow/` 与 `requirement_flow_service.py` 重叠 | **workflow/ 是死代码**：4 个 Flow 类仅在自身 `__init__.py` 引用 | 直接删除 |
| `data_fusion_service.py` 有重叠 | **死代码**：无任何 import | 直接删除 |
| `services/requirement_service.py`（顶层）有引用 | **死代码**：api/knowledge.py 实际导入的是子目录版本 | 直接删除 |
| `case/compiler.py` 可直接删除 | **有 13 处活跃引用**（api/session.py、api/upload_task.py 等） | 需先迁移引用 |
| `task.py` vs `requirement_task.py` 需合并 | **不应合并**：一对多关系，非重复 | 保留两者 |
| `graphflow.py` vs `workflow.py` 需统一 | **不同关注点**：DAG 编排 vs 事件追踪 | 保留两者 |

### 重叠文件统计

| 层面 | 重叠组数 | 删除文件数 | 新增文件数 | 修改文件数 |
|------|---------|-----------|-----------|-----------|
| services/ | 8 | 12 | 4 | 8 |
| models/ | 4 | 5 | 0 | 3 |
| api/ | 7 | 5 | 1 | 3 |
| retrieval/ vs rag/ | 2 | 6 | 1 | 2 |
| prompts/ + context/ | 2 | 3 | 0 | 4 |
| **合计** | **23** | **31** | **6** | **~20** |

## Proposed Changes

### Phase 1: 删除确认死代码（低风险）

#### 1.1 删除 `services/requirement_service.py`（顶层）

- **文件**: `backend/app/services/requirement_service.py`
- **原因**: 死代码，无任何文件 import（api/knowledge.py 导入的是 `services/knowledge/requirement_service.py` 子目录版本）
- **操作**: 直接删除
- **同步**: 检查 `services/__init__.py` 是否有导出

#### 1.2 删除 `services/data_fusion_service.py`

- **文件**: `backend/app/services/data_fusion_service.py`
- **原因**: 死代码，仅在日志中出现，功能已被 `retrieval/manager.py` + `context/fusion.py` 替代
- **操作**: 直接删除

#### 1.3 删除 `services/workflow/` 整个子目录

- **目录**: `backend/app/services/workflow/`（5 个文件：`__init__.py`、`requirement_flow.py`、`generation_flow.py`、`publish_flow.py`、`execution_flow.py`）
- **原因**: 4 个 Flow 类仅在自身 `__init__.py` 引用，`api/workflow.py` 实际通过 `services/generation/*_agent.py` 实现
- **操作**: 整个目录删除
- **注意**: `WorkflowState` 常量若被其他文件引用需先迁移

#### 1.4 删除 `api/three_layer.py`

- **文件**: `backend/app/api/three_layer.py`
- **前置条件**: 必须先完成 Phase 3.4（迁移 compiler.py 引用）
- **操作**: 删除文件 + 移除 `api/__init__.py` 中路由注册（第 25 行 import + 第 66 行 include_router）
- **风险**: 旧前端可能仍调用 `/three-layer/*`，需确认已迁移至 `/workflow/*`

---

### Phase 2: models/ 层统一

#### 2.1 统一 test_asset 三模型

- **目标**: 保留 `models/test_asset.py` 作为唯一资产模型，删除 `legacy_web_asset.py` 和 `test_asset_v2.py`
- **当前引用**: legacy 4 处（task_service.py、unified_task_service.py、requirement_flow_service.py、api/test_asset.py）；v2 2 处（api/assets_v2.py、services/assets/migration_service.py）

**步骤**:
1. **扩展 `models/test_asset.py`**: 补充 v2 独有字段（`draft_content`/`published_content`/`AssetSource` 枚举）和 legacy 独有字段（`script_content`/`script_language`/`reuse_count`/`kb_status`）；统一 `AssetType` 增加 `CASE`，`AssetStatus` 增加 `CREATED`/`ANALYZED`/`GENERATED`/`ARCHIVED`
2. **更新 4 个 legacy 引用**: `from app.models.legacy_web_asset import LegacyWebAsset as TestAsset` → `from app.models.test_asset import TestAsset, AssetStatus`
3. **更新 2 个 v2 引用**: `from app.models.test_asset_v2 import TestAssetV2` → `from app.models.test_asset import TestAsset`
4. **更新 `models/__init__.py`**: 移除旧导出
5. **删除**: `models/legacy_web_asset.py`、`models/test_asset_v2.py`
6. **DB 迁移**: Alembic 迁移将 `web_script_asset` 和 `test_asset_v2` 表数据导入 `test_asset` 表

#### 2.2 评估 case_* vs test_case_* 模型

- **结论**: **不统一**，两组模型服务不同业务线（case_* → L1/L2/L3 流水线；test_case_* → testcase_generation API），字段差异大，强行合并触发 11+ 文件改动无业务收益
- **操作**: 在 `models/__init__.py` 注释中明确职责边界

#### 2.3 统一 4 个事件/日志模型到 agent_event.py

- **目标**: 保留 `models/agent_event.py`，删除 `agent_log.py`、`agent_execution_log.py`、`workflow_event.py`
- **前置条件**: 建议在 REFACTOR_PLAN Phase 5（删除 agent_runtime/）后执行，因 AgentExecutionLog 被 `agent_runtime/orchestrator.py` 引用

**步骤**:
1. **扩展 `models/agent_event.py`**: 新增 `log_level`（吸收 AgentLog）、`input_data`/`output_data`（吸收 AgentExecutionLog）、`cost`/`duration`/`session_id`（吸收 WorkflowEvent）
2. **Alembic 迁移**: 数据迁移将 agent_log/agent_execution_log/workflow_event 历史数据导入 agent_event
3. **更新引用**: `tools/database_tool.py`（AgentLog→AgentEvent）、`agents/flows/mysql_storage_agent.py`、`api/agent_runtime.py`、`retrieval/mysql_retriever.py`、`api/workflow.py`（WorkflowEvent→AgentEvent）
4. **删除**: `models/agent_log.py`、`models/agent_execution_log.py`、`models/workflow_event.py`
5. **更新** `models/__init__.py`

#### 2.4 评估 task.py vs requirement_task.py

- **结论**: **不合并**，Task 是通用任务表，RequirementTask 是需求专用记录，通过 `task_id` 建立一对多关系
- **操作**: 在 `models/__init__.py` 注释中明确职责边界

---

### Phase 3: services/ 层重构

#### 3.1 合并 task_service.py 到 unified_task_service.py

- **操作**: 将 TaskService 的独有方法（get_task/get_task_list/update_task_status/delete_task/rerun_task/get_script_content）迁移到 UnifiedTaskService
- **更新引用**: `api/task.py` 中 16 处 `TaskService.*` → `UnifiedTaskService.*`；`services/__init__.py` 保留别名 `UnifiedTaskService as TaskService`
- **删除**: `services/task_service.py`

#### 3.2 拆分 execution_service.py 到 execution/ 子目录

- **操作**: 将 DB 记录管理方法迁移到新建 `services/execution/record_service.py`（ExecutionRecordService），删除旧版 `run_execution` 方法（已被 dispatcher 替代）
- **更新引用**: `api/execution.py`（ExecutionService → ExecutionRecordService + ExecutionDispatcher）、`services/requirement_flow_service.py`
- **删除**: `services/execution_service.py`
- **新增**: `services/execution/record_service.py`

#### 3.3 迁移 rag_service.py 到 rag/service/pipeline.py

- **操作**: 将 RAGService 的索引方法（index_all/index_incremental/index_cases/index_scripts/index_task）迁移到 RAGPipeline
- **更新引用**: `api/rag.py`（RAGService → get_rag_service()）
- **删除**: `services/rag_service.py`
- **保留**: `services/generation/rag_agent.py`（薄 Agent，服务 workflow，职责不同）

#### 3.4 拆分 case/compiler.py 并迁移引用

- **原因**: 已标注"已废弃"但有 13 处活跃引用
- **操作**: 提取 3 个独立文件：
  - `services/case/progress_queue.py` — `_progress_queues` 工具
  - `services/case/execution_compiler.py` — `compile_for_execution` 函数
  - `services/case/business_rules.py` — 默认业务规则
- **更新引用**: `api/session.py`（4 处）、`api/upload_task.py`（3 处）、`api/api_test/execution_controller.py`、`api/api_test/suite_controller.py`、`services/generation/rag_agent.py`
- **删除**: `services/case/compiler.py`

#### 3.5 统一 session_manager.py（services → runtime）

- **操作**: 将 `services/session_manager.py` 的 DB 持久化方法迁移到 `runtime/session_manager.py`
- **更新引用**: `api/session_v2.py`
- **删除**: `services/session_manager.py`

#### 3.6 requirement_flow_service.py 处理

- **说明**: 由 REFACTOR_PLAN Phase 3 负责重构为 BroadcastDispatcher，本计划仅完成协同引用更新（Phase 2.1 legacy_web_asset 引用 + Phase 3.2 execution_service 引用）

---

### Phase 4: api/ 层合并

#### 4.1 合并 session.py + session_v2.py

- **操作**: 将 session.py 独有端点（stream/contents/chunks/testpoints/archive/resume）迁移到 session_v2.py，v2 prefix 改为 `/session`，删除旧 session.py，重命名 v2 为正式版
- **更新**: `api/__init__.py` 路由注册
- **风险**: 前端 `/session/v2/*` 调用需改为 `/session/*`

#### 4.2 合并 rag.py + rag_v2.py

- **操作**: 将 rag.py 索引管理端点迁移到 rag_v2.py，v2 prefix 改为 `/rag`，删除旧 rag.py，重命名 v2 为正式版
- **更新**: `api/__init__.py` 路由注册

#### 4.3 统一 test_asset.py + test_assets.py + assets_v2.py

- **操作**: 以 assets_v2.py 为基础新建 `api/assets.py`（prefix `/assets`），合并旧版端点（providers/drafts/type-stats/route/batch-delete），删除 3 个旧文件
- **更新**: `api/__init__.py` 路由注册
- **删除**: `api/test_asset.py`、`api/test_assets.py`、`api/assets_v2.py`

#### 4.4-4.6 评估保留项

- `graphflow.py` vs `workflow.py`: **保留两者**（DAG 编排 vs 事件追踪，不同关注点）
- `case.py` vs `testcase_generation.py`: **短期保留**，中期统一到 testcase_generation.py
- `requirement.py` vs `requirement_center.py`: **保留两者**（任务执行 vs 会话管理，不同关注点）

---

### Phase 5: retrieval/ 与 rag/ 统一

#### 5.1 统一 retrieval/manager.py 到 rag/service/pipeline.py

- **操作**: 将 RetrievalManager 的 `retrieve_by_plan(plan)` 逻辑作为 RAGPipeline 新方法
- **更新引用**: `api/context_api.py`（get_retrieval_manager → get_rag_service）、`context/__init__.py`
- **保留**: `context/` 模块（router.py + fusion.py + models.py）

#### 5.2 统一 retrieval/ 三个检索器到 rag/retriever/

- **操作**: 将 mysql_retriever.py 的通用查询能力迁移到 `rag/retriever/mysql_query_tool.py`；milvus_retriever.py 能力已被 vector_retriever.py 覆盖；neo4j_retriever.py 迁移到 `rag/graph_store/`
- **删除**: `retrieval/` 整个目录（6 个文件）

---

### Phase 6: prompts/ 和 context/ 清理

#### 6.1 删除 prompts/case_prompt.py 和 prompts/requirement_prompt.py

- **前置条件**: REFACTOR_PLAN Phase 3 完成（requirement_flow_service.py 重构后不再使用这些 Prompt）
- **操作**: 删除 2 个文件，更新 `prompts/__init__.py` 移除导出

#### 6.2 统一 context/router.py 与 agent/router_agent.py

- **操作**: 将 RouterAgent 的关键词路由规则迁移到 `context/router.py` 新增 `route_by_query()` 方法
- **更新引用**: `runtime/agent_registry.py` 和 `agents/factory/definitions.py` 移除 router_agent 定义
- **删除**: `agent/router_agent.py`
- **协调**: 与 REFACTOR_PLAN Phase 5（删除 agent/ 目录）协同执行

---

### Phase 7: 全量验证

1. **残留引用搜索**: Grep 确认所有旧路径无残留 import
2. **路由注册验证**: 检查 `api/__init__.py` 无悬挂引用
3. **启动测试**: 无 ImportError，所有 API 端点可访问
4. **DB 迁移验证**: `alembic upgrade head` 成功，历史数据已迁移

## Assumptions & Decisions

1. **死代码直接删除**: `requirement_service.py`、`data_fusion_service.py`、`services/workflow/` 确认无引用，直接删除
2. **task_service + unified_task_service 合并而非删除**: 两者互补，需将 TaskService 独有方法迁移到 UnifiedTaskService
3. **case_* vs test_case_* 不统一**: 两组模型服务不同业务线，字段差异大，强行合并无业务收益
4. **task vs requirement_task 不合并**: 一对多关系，非重复
5. **graphflow vs workflow 保留两者**: 不同关注点（DAG 编排 vs 事件追踪）
6. **事件模型统一需 DB 迁移**: 需要 Alembic 迁移脚本将历史数据导入统一表
7. **与 REFACTOR_PLAN 协调**: Phase 2.3 和 Phase 6 需在 REFACTOR_PLAN 对应 Phase 后执行

## 执行顺序与依赖关系

```
第一批（无冲突，可立即执行）:
  Phase 1（死代码删除）→ Phase 2.1（test_asset 统一）→ Phase 3（services 重构）→ Phase 4（api 合并）→ Phase 5（retrieval 统一）

第二批（需协调 REFACTOR_PLAN）:
  REFACTOR_PLAN Phase 1-6 完成后 → Phase 2.3（事件模型统一）→ Phase 6（prompts 和 context 清理）
```

## 文件操作汇总

### 删除的文件（31 个）

| Phase | 文件 |
|-------|------|
| 1.1 | `services/requirement_service.py` |
| 1.2 | `services/data_fusion_service.py` |
| 1.3 | `services/workflow/`（5 个文件） |
| 1.4 | `api/three_layer.py` |
| 2.1 | `models/legacy_web_asset.py`、`models/test_asset_v2.py` |
| 2.3 | `models/agent_log.py`、`models/agent_execution_log.py`、`models/workflow_event.py` |
| 3.1 | `services/task_service.py` |
| 3.2 | `services/execution_service.py` |
| 3.3 | `services/rag_service.py` |
| 3.4 | `services/case/compiler.py` |
| 3.5 | `services/session_manager.py` |
| 4.3 | `api/test_asset.py`、`api/test_assets.py`、`api/assets_v2.py` |
| 5.1+5.2 | `retrieval/`（6 个文件） |
| 6.1 | `prompts/case_prompt.py`、`prompts/requirement_prompt.py` |
| 6.2 | `agent/router_agent.py` |

### 新增的文件（6 个）

| Phase | 文件 |
|-------|------|
| 3.2 | `services/execution/record_service.py` |
| 3.4 | `services/case/progress_queue.py` |
| 3.4 | `services/case/execution_compiler.py` |
| 3.4 | `services/case/business_rules.py` |
| 5.2 | `rag/retriever/mysql_query_tool.py`（可选） |
| 4.3 | `api/assets.py`（合并后正式版） |

### 重命名的文件（3 个）

| Phase | 原路径 → 新路径 |
|-------|-----------------|
| 4.1 | `api/session_v2.py` → `api/session.py` |
| 4.2 | `api/rag_v2.py` → `api/rag.py` |
| 4.3 | `api/assets_v2.py` → `api/assets.py` |

## Verification Steps

1. **Phase 1 验证**: Grep 搜索 `from app.services.requirement_service import`、`from app.services.data_fusion_service import`、`from app.services.workflow`、`from app.api.three_layer import` 无结果
2. **Phase 2 验证**: `alembic upgrade head` 成功；Grep 搜索 `from app.models.legacy_web_asset import`、`from app.models.test_asset_v2 import`、`from app.models.agent_log import`、`from app.models.agent_execution_log import`、`from app.models.workflow_event import` 无结果
3. **Phase 3 验证**: Grep 搜索 `from app.services.task_service import`、`from app.services.execution_service import`、`from app.services.rag_service import`、`from app.services.case.compiler import`、`from app.services.session_manager import` 无结果
4. **Phase 4 验证**: API 端点 `/session/*`、`/rag/*`、`/assets/*` 可访问，无 `/session/v2`、`/rag/v2`、`/assets/v2` 路由
5. **Phase 5 验证**: Grep 搜索 `from app.retrieval` 无结果；`api/context_api.py` 正常工作
6. **Phase 6 验证**: Grep 搜索 `from app.prompts.case_prompt import`、`from app.prompts.requirement_prompt import`、`from app.agent.router_agent import` 无结果
7. **启动测试**: 后端服务无 ImportError，所有 API 端点可访问，SSE 端点正常推送
