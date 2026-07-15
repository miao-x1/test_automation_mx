# 冗余代码清理执行计划（更新版）

## Summary

清理 `backend/app/` 下新旧版本重叠文件，消除所有冗余代码。Phase 1（死代码删除）已完成，本计划从 Phase 2.1（test_asset 模型统一收尾）开始，覆盖 services/、api/、retrieval/ 三大层面，共 5 个 Phase、约 20 个步骤、涉及修改约 25 个文件、删除约 15 个文件。

## Current State Analysis

### 已完成
- **Phase 1 死代码删除**: `services/requirement_service.py`、`services/data_fusion_service.py`、`services/workflow/*.py` 已删除（仅剩 `__pycache__` 待清理）
- **Phase 2.1 模型扩展**: `models/test_asset.py` 已扩展完成，包含 V2 字段（`draft_content`/`published_content`/`folder_id`/`test_point_id`）和 Legacy 字段（`input_config`/`exec_config`/`script_content`/`script_language`/`script_path`/`kb_status`/`reuse_count`），枚举已统一，添加了 `name`/`source` 兼容属性

### 待完成
| Phase | 状态 | 涉及文件数 | 删除文件数 | 新增文件数 |
|-------|------|-----------|-----------|-----------|
| 2.1 test_asset 统一收尾 | 进行中 | 9 | 2 | 0 |
| 3 services/ 层重构 | 未开始 | ~12 | 5 | 5 |
| 4 api/ 层合并 | 未开始 | ~6 | 5 | 0 |
| 5 retrieval/ 统一 | 未开始 | ~3 | 6(目录) | 0(迁移) |

### 关键发现
1. `task_service.py`（8方法）与 `unified_task_service.py`（3方法+3辅助）是**互补关系**，需合并而非删除任一
2. `case/compiler.py` 有 **14 处活跃引用**，拆分需同步更新所有引用
3. `source` 是 Python property 别名（指向 `source_type` 列），**SQLAlchemy 查询过滤器中不能使用**，必须用 `source_type`
4. Legacy 的 `source="generated"` 对应统一模型的 `SourceType.AI = "ai"`，需做值映射
5. `retrieval/` 与 `rag/` 职责不同（三库协同检索 vs 文档级 RAG 管道），应迁移合并而非删除

---

## Proposed Changes

### Phase 2.1: test_asset 三模型统一（收尾）

#### 2.1.1 更新 `to_execution_json` 和 `publish` 方法

**文件**: `backend/app/models/test_asset.py`

`to_execution_json` 方法（第 216 行）增加 V2 fallback — 当 `content_json` 为空时从 `published_content` 或 `draft_content` 读取:

```python
def to_execution_json(self) -> dict:
    """生成Execution Ready格式（从content_json，V2兼容fallback）"""
    content = self.content_json
    if not content:
        content = self.published_content or self.draft_content
    if not content:
        return {}
    try:
        data = json.loads(content)  # 原来是 json.loads(self.content_json)
```

`publish` 方法（第 276 行）补充 draft→published 复制逻辑:

```python
def publish(self):
    """发布：标记为已发布，并将draft_content复制到published_content"""
    if self.draft_content and not self.published_content:
        self.published_content = self.draft_content
    self.published = True
    self.status = AssetStatus.PUBLISHED
```

#### 2.1.2 修改 `task.py` relationship 引用

**文件**: `backend/app/models/task.py`（第 139-144 行）

```python
# 当前
test_assets = relationship("LegacyWebAsset", back_populates="task", ...)
# 修改为
test_assets = relationship("TestAsset", back_populates="task", ...)
```

#### 2.1.3 更新 6 个 legacy_web_asset 引用文件

| 文件 | 行号 | 当前 import | 修改为 |
|------|------|-------------|--------|
| `models/__init__.py` | 8 | `from app.models.legacy_web_asset import LegacyWebAsset` | 删除此行 |
| `api/test_asset.py` | 13 | `from app.models.legacy_web_asset import LegacyWebAsset as TestAsset, LegacyAssetType as AssetType, LegacyAssetStatus as AssetStatus` | `from app.models.test_asset import TestAsset, AssetType, AssetStatus` |
| `services/task_service.py` | 14 | 同上 | 同上 |
| `services/unified_task_service.py` | 25 | 同上 | 同上 |
| `services/requirement_flow_service.py` | 1232 | 同上 | 同上 |
| `migrations/migrate_case_to_asset.py` | 312 | `from app.models.legacy_web_asset import LegacyWebAsset` | 删除此行（改用原生 SQL 查询旧表或跳过） |

**字段适配**（所有创建 TestAsset 的位置）:
- `name=...` → `title=...`（使用实际列名）
- `source="generated"` → `source_type="ai"`（值映射 + 列名）
- `status=AssetStatus.READY` → 不变（统一模型有 READY 状态）

涉及文件: `api/test_asset.py`、`services/task_service.py:300-310`、`services/unified_task_service.py:302-329`、`services/requirement_flow_service.py:1233-1258`

#### 2.1.4 更新 3 个 test_asset_v2 引用文件

| 文件 | 行号 | 当前 import | 修改为 |
|------|------|-------------|--------|
| `models/__init__.py` | 30 | `from app.models.test_asset_v2 import TestAssetV2, AssetType as AssetTypeV2, AssetStatus as AssetStatusV2, AssetSource` | 删除此行，从 `test_asset` 导入 `AssetSource` |
| `api/assets_v2.py` | 17 | `from app.models.test_asset_v2 import TestAssetV2, AssetType, AssetStatus, AssetSource` | `from app.models.test_asset import TestAsset as TestAssetV2, AssetType, AssetStatus, AssetSource` |
| `services/assets/migration_service.py` | 20 | 同上 | 同上 |

**关键适配 — SQLAlchemy 查询过滤器**:
- `api/assets_v2.py:62` — `query.filter(TestAssetV2.source == source)` → `query.filter(TestAssetV2.source_type == source)`（property 不能用于查询过滤器）
- `services/assets/migration_service.py` — ORM 构造中 `source=AssetSource.AI` → `source_type=AssetSource.AI`（构造函数必须用列名）

**`models/__init__.py` 清理**:
- 删除第 8 行 `from app.models.legacy_web_asset import LegacyWebAsset`
- 删除第 30 行 `from app.models.test_asset_v2 import ...`
- 在第 7 行补充 `AssetSource, SourceType` 导出
- 从 `__all__` 中删除 `"LegacyWebAsset"`、`"TestAssetV2"`、`"AssetTypeV2"`、`"AssetStatusV2"`

#### 2.1.5 删除旧模型文件

- 删除 `backend/app/models/legacy_web_asset.py`
- 删除 `backend/app/models/test_asset_v2.py`
- 清理 `backend/app/services/workflow/__pycache__/` 目录

**验证**: 
```bash
cd backend
python -c "from app.models import TestAsset, AssetType, AssetStatus, SourceType, AssetSource; print('models OK')"
python -c "from app.services.task_service import TaskService; print('task_service OK')"
python -c "from app.services.unified_task_service import UnifiedTaskService; print('unified OK')"
python -c "from app.api.assets_v2 import router; print('assets_v2 OK')"
```

---

### Phase 3: services/ 层重构

#### 3.1 合并 task_service.py + unified_task_service.py

**策略**: 将 `unified_task_service.py` 的所有方法迁入 `task_service.py` 的 `TaskService` 类，统一 `create_task` 签名（采用 UnifiedTaskService 更全的版本），保留 `run_analysis` 和 `run_unified_analysis` 两个流程方法。

**合并后 TaskService 方法清单**:
- `create_task`（统一签名，支持 image/url 两种模式）
- `get_task`、`get_task_list`、`update_task_status`、`delete_task`、`rerun_task`、`get_script_content`（来自 TaskService）
- `run_analysis`（旧版 Vision-only 流程，来自 TaskService）
- `run_unified_analysis`、`_run_vision`、`_run_crawl`、`_remap_progress`（来自 UnifiedTaskService）

**引用更新**:
| 文件 | 当前 import | 修改为 |
|------|------------|--------|
| `api/task.py:22` | `from app.services.task_service import TaskService` | 不变 |
| `api/upload_task.py` | `from app.services.unified_task_service import UnifiedTaskService` | `from app.services.task_service import TaskService as UnifiedTaskService` |
| `services/__init__.py:4` | `from app.services.task_service import TaskService` | 不变 |

全局搜索 `UnifiedTaskService` 引用并更新。删除 `services/unified_task_service.py`。

#### 3.2 拆分 execution_service.py

**策略**: 将 `ExecutionService`（7方法）拆分为两个文件:

| 新文件 | 迁入方法 |
|--------|---------|
| `services/execution/legacy_runner.py` | `create_execution`、`run_execution`（Playwright 脚本执行） |
| `services/execution/query_service.py` | `get_execution`、`get_executions_by_task`、`get_execution_log`、`get_execution_report`、`get_execution_screenshot` |

在 `services/execution/__init__.py` 中创建兼容导出:
```python
from app.services.execution.legacy_runner import LegacyExecutionRunner as ExecutionService
from app.services.execution.query_service import ExecutionQueryService
```

**引用更新**:
| 文件 | 当前 import | 修改为 |
|------|------------|--------|
| `api/execution.py:29` | `from app.services.execution_service import ExecutionService` | `from app.services.execution import ExecutionService, ExecutionQueryService` |
| `services/requirement_flow_service.py:1401` | `from app.services.execution_service import ExecutionService` | `from app.services.execution import ExecutionService` |

删除 `services/execution_service.py`。

#### 3.3 迁移 rag_service.py

**策略**: 将 `RAGService` 的 Milvus 索引逻辑迁移到 `rag/service/legacy_rag.py`，保留旧索引能力:

**引用更新**:
| 文件 | 当前 import | 修改为 |
|------|------------|--------|
| `api/rag.py:10` | `from app.services.rag_service import RAGService` | `from app.rag.service.legacy_rag import LegacyRAGService as RAGService` |

删除 `services/rag_service.py`。

#### 3.4 拆分 case/compiler.py

**策略**: 将 `CaseCompilerService`（16方法）拆分为 3 个文件:

| 新文件 | 迁入内容 |
|--------|---------|
| `services/case/case_set_store.py` | `_read_case_set`、`_merge_case_set`、`_migrate_old_format`、`_load_cases_from_db`、`_save_single_case` |
| `services/case/pipeline.py` | `run_pipeline`、`_run_pipeline_async`、`run_l3_compilation`、`compile_for_execution` |
| `services/case/compiler_utils.py` | `_progress_queues`、`PIPELINE_STATES`、`RAG_TOP_K_LIMIT`、`_push_progress`、`_check_rag_available`、`_get_default_business_rules`、`_limit_rag_result` |

**14 处引用更新**:
| 文件 | 行号 | 修改为 |
|------|------|--------|
| `api/session.py` | 258, 346 | `from app.services.case.compiler_utils import _progress_queues` |
| `api/session.py` | 608 | `from app.services.case.pipeline import CasePipeline` |
| `api/session.py` | 615 | 同上 |
| `api/session.py` | 633 | 同上 |
| `api/upload_task.py` | 199, 257 | `from app.services.case.compiler_utils import _progress_queues` |
| `api/upload_task.py` | 204 | `from app.services.case.pipeline import CasePipeline` |
| `api/api_test/execution_controller.py` | 127 | `from app.services.case.pipeline import CasePipeline` |
| `api/api_test/suite_controller.py` | 133 | 同上 |
| `services/generation/rag_agent.py` | 49 | `from app.services.case.compiler_utils import get_default_business_rules` |

删除 `services/case/compiler.py`。

#### 3.5 统一 session_manager.py

**策略**: 将 `services/session_manager.py` 的 DB 持久化方法迁入 `runtime/session_manager.py`，使后者成为统一入口。

**引用更新**:
| 文件 | 当前 import | 修改为 |
|------|------------|--------|
| `api/session_v2.py:27` | `from app.services.session_manager import get_session_manager` | `from app.runtime.session_manager import get_session_manager` |

删除 `services/session_manager.py`。

> **风险**: 需确保 `runtime/session_manager.py` 的 `get_session_manager()` 返回实例具有 `session_v2.py` 所需的所有方法。若不兼容，先在 `runtime/session_manager.py` 中添加缺失方法的委托。

---

### Phase 4: api/ 层合并

#### 4.1 合并 session 路由

将 `api/session.py` 的独有端点迁移到 `api/session_v2.py`，修改 v2 prefix 为 `/session`:

**`api/__init__.py` 修改**:
- 删除第 28 行 `from app.api.session import router as session_router`
- 删除第 70 行 `api_router.include_router(session_router, prefix="/session", ...)`
- 修改第 75 行 → `api_router.include_router(session_v2_router, prefix="/session", tags=["会话管理"])`

删除 `api/session.py`。

#### 4.2 合并 rag 路由

将 `api/rag.py` 的独有索引端点迁移到 `api/rag_v2.py`:

**`api/__init__.py` 修改**:
- 删除第 10 行 `from app.api.rag import router as rag_router`
- 删除第 54 行 `api_router.include_router(rag_router, prefix="/rag", ...)`
- 修改第 76 行 `prefix="/rag/v2"` → `prefix="/rag"`

删除 `api/rag.py`。

#### 4.3 合并 test_asset 路由

以 `api/assets_v2.py` 为基准合并，将 `api/test_asset.py` 的 Provider Schema 端点迁入:

**`api/__init__.py` 修改**:
- 删除第 17 行 `from app.api.test_asset import router as test_asset_router`
- 删除第 16 行 `from app.api.test_assets import router as test_assets_router`
- 删除第 51 行 `api_router.include_router(test_asset_router, prefix="/assets", ...)`
- 删除第 68 行 `api_router.include_router(test_assets_router)`
- 修改第 71 行 `prefix="/assets/v2"` → `prefix="/assets"`

删除 `api/test_asset.py` 和 `api/test_assets.py`。

#### 4.4 删除 three_layer.py

**前置条件**: Phase 3.4 已完成。

**`api/__init__.py` 修改**:
- 删除第 25 行 `from app.api.three_layer import router as three_layer_router`
- 删除第 66 行 `api_router.include_router(three_layer_router, prefix="/three-layer", ...)`

删除 `api/three_layer.py`。

---

### Phase 5: retrieval/ 统一到 rag/

#### 5.1 迁移 retrieval/ 到 rag/retrieval_engine/

将 `retrieval/` 目录整体迁移为 `rag/retrieval_engine/` 子模块:

| 原路径 | 新路径 |
|--------|--------|
| `retrieval/base.py` | `rag/retrieval_engine/base.py` |
| `retrieval/manager.py` | `rag/retrieval_engine/manager.py` |
| `retrieval/mysql_retriever.py` | `rag/retrieval_engine/mysql_retriever.py` |
| `retrieval/milvus_retriever.py` | `rag/retrieval_engine/milvus_retriever.py` |
| `retrieval/neo4j_retriever.py` | `rag/retrieval_engine/neo4j_retriever.py` |

**引用更新**:
| 文件 | 当前 import | 修改为 |
|------|------------|--------|
| `api/context_api.py:19` | `from app.retrieval.manager import get_retrieval_manager` | `from app.rag.retrieval_engine.manager import get_retrieval_manager` |
| 迁移文件内部 | `from app.retrieval.base import ...` | `from app.rag.retrieval_engine.base import ...` |

删除 `retrieval/` 目录。

---

## Assumptions & Decisions

1. **`source` property 不能用于 SQLAlchemy 查询**: ORM 构造和查询过滤器中必须使用实际列名 `source_type`，仅序列化/反序列化时可使用 `source` 别名
2. **Legacy `source="generated"` 映射为 `source_type="ai"`**: 统一使用 `SourceType.AI`
3. **task_service 与 unified_task_service 合并**: 互补关系，统一为 `TaskService`，保留所有方法
4. **compiler.py 14 处引用**: 拆分后同步更新所有引用，不做兼容 facade（用户要求直接删除）
5. **retrieval/ 迁移而非删除**: 保留三库协同检索能力，归入 rag/ 体系
6. **前端路由协调**: Phase 4 涉及 URL prefix 变更（`/session/v2` → `/session` 等），需与前端同步
7. **Phase 2.3 和 Phase 6 推迟**: 事件模型统一和 prompts/context 清理需协调 REFACTOR_PLAN，不在本计划范围

## Verification Steps

1. **Phase 2.1 验证**: Grep 搜索 `from app.models.legacy_web_asset import` 和 `from app.models.test_asset_v2 import` 无结果；Python import 测试通过
2. **Phase 3 验证**: Grep 搜索 `from app.services.unified_task_service`、`from app.services.execution_service`、`from app.services.rag_service`、`from app.services.case.compiler`、`from app.services.session_manager` 无结果
3. **Phase 4 验证**: 检查 `api/__init__.py` 无 `session_router`、`rag_router`、`test_asset_router`、`three_layer_router` 注册；API 端点 `/session/*`、`/rag/*`、`/assets/*` 可访问
4. **Phase 5 验证**: Grep 搜索 `from app.retrieval` 无结果；`api/context_api.py` 正常工作
5. **启动测试**: 后端服务无 ImportError，所有 API 端点可访问，SSE 端点正常推送

## 执行顺序

```
Phase 2.1 (test_asset 统一收尾)
  2.1.1 → 2.1.2 → 2.1.3 → 2.1.4 → 2.1.5
  ↓
Phase 3 (services 层重构)
  3.1 → 3.2 → 3.3 → 3.4 → 3.5
  ↓
Phase 4 (api 层合并)
  4.1 → 4.2 → 4.3 → 4.4 (依赖 3.4)
  ↓
Phase 5 (retrieval 统一)
  5.1
```
