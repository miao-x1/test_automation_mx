# 项目目录整理执行计划

## Summary

清理 `c:\ui-automation` 根目录下散乱的 39 个 MD 文件和 4 个 TXT 文件：删除 7 个无用文件，将 33 个设计文档归档到 `docs/design/` 分类目录，根目录仅保留 3 个核心文件（README.md、CURRENT_ARCHITECTURE.md、REFACTOR_PLAN.md）。

## Current State Analysis

### 根目录文件现状

根目录堆积了 43 个非代码文件，严重影响可读性：

| 类别 | 数量 | 说明 |
|------|------|------|
| 核心文档 | 3 | README.md、CURRENT_ARCHITECTURE.md、REFACTOR_PLAN.md |
| 设计文档 | 33 | 各阶段重构设计稿，散落在根目录 |
| 过时/无用文件 | 7 | 已被取代的旧文档 + 空/笔记 TXT 文件 |

### 文件价值判断依据

- **ARCHITECTURE.md**：仅展示 4 个文件的极早期架构，被 CURRENT_ARCHITECTURE.md（含 22 个路由模块、完整目录树）完全取代
- **PROJECT_DELIVERY.md**：MVP 阶段交付文档，项目已远超此阶段
- **MIGRATION.md**：被 MIGRATION_PLAN.md（标注"已执行完成"）取代
- **0.4**：空文件，0 行内容
- **0611.txt**：非结构化个人开发笔记
- **midscen.txt**：Midscene 个人学习笔记，与项目无关
- **图解.txt**：简陋 ASCII 架构图，信息已在正式文档中体现

## Proposed Changes

### Step 1: 删除 7 个无用文件

| 文件 | 删除原因 |
|------|---------|
| `ARCHITECTURE.md` | 被 CURRENT_ARCHITECTURE.md 完全取代 |
| `PROJECT_DELIVERY.md` | 极早期 MVP 交付文档，严重过时 |
| `MIGRATION.md` | 被 MIGRATION_PLAN.md 取代 |
| `0.4` | 空文件 |
| `0611.txt` | 非结构化个人笔记 |
| `midscen.txt` | 个人学习笔记，与项目无关 |
| `图解.txt` | 简陋 ASCII 图，信息已在正式文档中 |

### Step 2: 创建归档目录结构

在 `c:\ui-automation\docs\` 下创建分类子目录：

```
docs/
└── design/
    ├── agent/        # Agent 架构、结果、生成模块
    ├── case/         # 用例模型、生成、UI
    ├── execution/    # 执行中心、引擎、模式、重构
    ├── frontend/     # 菜单、状态管理、上传、测试标准
    ├── requirement/  # 需求模块、产品化
    ├── session/      # 会话中心、日志中心
    ├── workflow/     # 工作流、事件、监控、最终架构
    ├── api/          # API 分析、提取、测试
    ├── suite/        # 套件模型、可选降级
    ├── migration/    # 迁移方案
    ├── integration/  # RAG 集成
    └── performance/  # 性能优化
```

### Step 3: 移动 33 个设计文档到对应分类目录

| 源文件 | 目标目录 |
|--------|---------|
| `AGENT_ARCHITECTURE.md` | `docs/design/agent/` |
| `AGENT_RESULT.md` | `docs/design/agent/` |
| `GENERATION_ARCH.md` | `docs/design/agent/` |
| `CASE_GENERATOR.md` | `docs/design/case/` |
| `CASE_MODEL.md` | `docs/design/case/` |
| `CASE_UI.md` | `docs/design/case/` |
| `MODEL_REFACTOR.md` | `docs/design/case/` |
| `EXECUTION_CENTER.md` | `docs/design/execution/` |
| `EXECUTION_ENGINE.md` | `docs/design/execution/` |
| `EXECUTION_MODE.md` | `docs/design/execution/` |
| `EXECUTION_REFACTOR.md` | `docs/design/execution/` |
| `MENU_REFACTOR.md` | `docs/design/frontend/` |
| `MENU_CASE_RESTORE.md` | `docs/design/frontend/` |
| `STATE_MANAGEMENT.md` | `docs/design/frontend/` |
| `UPLOAD_CENTER.md` | `docs/design/frontend/` |
| `TEST_MODULE_STANDARD.md` | `docs/design/frontend/` |
| `REQUIREMENT_MODULE.md` | `docs/design/requirement/` |
| `REQUIREMENT_PRODUCT.md` | `docs/design/requirement/` |
| `SESSION_ARCH.md` | `docs/design/session/` |
| `SESSION_CENTER.md` | `docs/design/session/` |
| `LOG_CENTER.md` | `docs/design/session/` |
| `WORKFLOW.md` | `docs/design/workflow/` |
| `WORKFLOW_EVENT.md` | `docs/design/workflow/` |
| `WORKFLOW_MONITOR.md` | `docs/design/workflow/` |
| `FINAL_ARCHITECTURE.md` | `docs/design/workflow/` |
| `API_ANALYZE.md` | `docs/design/api/` |
| `API_EXTRACTION.md` | `docs/design/api/` |
| `API_TEST.md` | `docs/design/api/` |
| `SUITE_MODEL.md` | `docs/design/suite/` |
| `SUITE_OPTIONAL.md` | `docs/design/suite/` |
| `MIGRATION_PLAN.md` | `docs/design/migration/` |
| `RAG_INTEGRATION.md` | `docs/design/integration/` |
| `PERFORMANCE.md` | `docs/design/performance/` |

### Step 4: 保留根目录 3 个文件

| 文件 | 保留原因 |
|------|---------|
| `README.md` | 项目入口文档，环境要求和启动命令 |
| `CURRENT_ARCHITECTURE.md` | 当前架构快照，最新最全（2026-06-17） |
| `REFACTOR_PLAN.md` | 活跃重构计划文档 |

### Step 5: 不动的文件

以下文件保持原位，不做任何操作：

- `backend/docs/` 下 5 个文件（DATABASE_DELIVERY.md, DATABASE_DESIGN.md, DATABASE_PHASE1_SUMMARY.md, database_schema.sql, er_diagram.html）— 已在正确位置
- `backend/app/agent_runtime/README.md` — 模块级文档
- `backend/app/context/README.md` — 模块级文档
- `.gitignore`, `.idea/`, `.vscode/`, `.venv/` 等配置目录
- `frontend/`, `backend/` 代码目录

## Assumptions & Decisions

1. **设计文档归档而非删除**：33 个设计文档虽散乱但有参考价值，归档到 `docs/design/` 分类目录而非删除
2. **backend/docs/ 保留原位**：已在子目录中，不影响根目录整洁，作为历史记录保留
3. **不修改文件内容**：仅做文件移动和删除，不修改任何文件内容
4. **不触碰代码和配置**：`backend/`、`frontend/`、`.idea/`、`.venv/` 等不受影响
5. **根目录最终状态**：仅 3 个 MD 文件 + 代码目录 + 配置目录

## Verification Steps

1. 删除 7 个文件后，确认根目录不再有 `.txt` 文件和 `0.4` 文件
2. 移动 33 个文件后，确认 `docs/design/` 下 12 个子目录均已创建且文件就位
3. 根目录仅剩 3 个 MD 文件（README.md、CURRENT_ARCHITECTURE.md、REFACTOR_PLAN.md）
4. 用 Grep 搜索确认无代码引用了被删除文件的路径（设计文档不被代码引用）
5. 确认 `backend/docs/` 和子目录 README 文件未受影响
