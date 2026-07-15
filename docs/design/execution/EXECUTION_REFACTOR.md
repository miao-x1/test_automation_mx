# Phase 3 — 重构执行体系（Execution First）

## 目标

统一执行入口。所有执行类型共用 `/execution` 路由和 `ExecutionRecord` 模型。

## 步骤1：ExecutionCenter 前端页面

### 路由
`/execution`

### Tab 结构
| Tab | 内容 |
|-----|------|
| 最近执行 | 通用执行列表 + 快速执行面板 |
| 接口执行 | execution_type=api 过滤列表 |
| Web执行 | execution_type=web 过滤列表 |
| 定时任务 | 跳转到 /web/schedule |
| 报告 | 跳转到报告模块 |

### 功能
- 执行列表：分页、状态过滤、类型过滤
- 快速执行：输入 asset_id 直接执行
- 操作按钮：取消 / 重试 / 查看报告 / 删除
- 状态显示：waiting / pending / running / success / failed / cancelled

### 修改文件
- `frontend/src/pages/execution/ExecutionCenterPage.tsx` — 完全重写

## 步骤2：新增 POST /execution/run/asset

### 请求
```json
{
  "asset_id": 1,
  "env": "test",
  "base_url": "http://localhost:8080",
  "async_exec": true
}
```

### 响应
```json
{
  "execution_id": 42,
  "status": "queued",
  "asset_id": 1
}
```

### 流程
1. 加载 TestAsset，验证 executable=True
2. 创建 ExecutionRecord（asset_id, execution_type=asset.asset_type）
3. async_exec=True → 提交到执行队列
4. async_exec=False → 同步执行，返回结果

### 修改文件
- `backend/app/api/execution.py` — 新增端点

## 步骤3：同步/异步执行、SSE、取消、重试

### 执行模式
| 模式 | 参数 | 行为 |
|------|------|------|
| 异步 | async_exec=true | 提交队列，立即返回 execution_id |
| 同步 | async_exec=false | 等待执行完成，返回结果 |

### SSE 进度
`GET /execution/{execution_id}/stream` — 实时推送执行进度

### 取消
`POST /execution/{execution_id}/cancel` — 取消等待/执行中的任务

### 重试
`POST /execution/{execution_id}/retry` — 基于原执行记录创建新执行

### 修改文件
- `backend/app/api/execution.py` — 新增 cancel/retry/stream 端点

## 步骤4：ExecutionDispatcher

### 路由逻辑
```
asset.type
  ↓
api     → _run_api（CaseRunner + HttpRunner + AssertionEngine）
web     → _run_web（占位，返回 not_implemented）
android → _run_android（占位，返回 not_implemented）
```

### 方法
| 方法 | 说明 |
|------|------|
| dispatch_by_asset | 执行单个 TestAsset |
| dispatch_batch | 批量执行多个 TestAsset |
| _run_api | API 测试执行（CaseRunner） |
| _run_web | Web 执行（占位） |
| _run_android | Android 执行（占位） |

### 修改文件
- `backend/app/services/execution/dispatcher.py` — 完全重写

## 步骤5：report_generator.py

### 支持格式
| 格式 | 说明 |
|------|------|
| json | 结构化数据（默认） |
| html | 可视化 HTML 报告 |
| excel | .xlsx 报告（openpyxl） |

### 新增方法
| 方法 | 说明 |
|------|------|
| _build_report | 从 ExecutionRecord 构建统一报告数据 |
| _generate_excel | 生成 Excel 报告（openpyxl） |
| generate_and_save | 生成并保存到文件，更新 report_path |

### 修改文件
- `backend/app/services/execution/report_generator.py` — 完全重写

## 步骤6：ExecutionRecord 模型

### 新增字段
| 字段 | 类型 | 说明 |
|------|------|------|
| asset_id | Integer FK | 关联 TestAsset（Case First 执行入口） |
| suite_id | Integer | 关联 TestSuite（套件执行） |
| session_id | Integer | 关联 Session（批量执行） |
| execution_type | String(20) | 执行类型: api/web/android/suite/batch |

### 变更
- task_id: nullable=True（兼容旧 Playwright 执行，新执行不再依赖 task_id）
- 新增 ExecutionType 枚举: API/WEB/ANDROID/SUITE/BATCH
- 新增索引: idx_execution_asset_status, idx_execution_type_status

### 修改文件
- `backend/app/models/execution_record.py` — 重写

## 步骤7：删除旧执行接口

### 废弃接口
| 旧接口 | 状态 | 替代 |
|--------|------|------|
| POST /assets/v2/execution/run/case | deprecated | POST /execution/run/asset |
| POST /assets/v2/execution/run/suite | deprecated | POST /execution/run/suite |
| POST /api-test/execution/run | deprecated | POST /execution/run/asset |
| POST /api-test/execution/run/json | deprecated | POST /execution/run/batch |

### 前端迁移
- `test-design/constants.ts`: runCase → `/api/execution/run/asset`
- `test-design/constants.ts`: runSuite → `/api/execution/run/suite`

### 修改文件
- `backend/app/api/assets_v2.py` — 旧端点标记 deprecated，内部转发到新接口
- `backend/app/api/api_test/execution_controller.py` — 旧端点标记 deprecated
- `frontend/src/pages/test-design/constants.ts` — API 路径更新

## 统一执行 API 一览

| 端点 | 方法 | 说明 |
|------|------|------|
| /execution/run/asset | POST | 执行单个 TestAsset |
| /execution/run/suite | POST | 执行 TestSuite |
| /execution/run/batch | POST | 批量执行多个 asset |
| /execution/{id}/cancel | POST | 取消执行 |
| /execution/{id}/retry | POST | 重试执行 |
| /execution/{id}/stream | GET | SSE 进度推送 |
| /execution/{id} | GET | 查询执行详情 |
| /execution/list | GET | 分页列表（支持过滤） |
| /execution/{id}/report | GET | 报告（format=html/json/excel） |
| /execution/{id}/logs | GET | 执行日志 |
| /execution/{id} | DELETE | 删除记录 |
| /execution/batch | DELETE | 批量删除 |

## 验证

- [x] TypeScript 编译通过（0 errors）
- [x] Python 语法检查通过（所有关键文件）
- [x] ExecutionRecord 模型新增 asset_id/suite_id/session_id/execution_type
- [x] 统一执行入口 POST /execution/run/asset
- [x] ExecutionDispatcher 按 asset_type 路由到 runner
- [x] 报告生成支持 html/json/excel
- [x] 旧接口标记 deprecated，内部转发到新接口
- [x] 前端 constants.ts 迁移到新 API 路径
