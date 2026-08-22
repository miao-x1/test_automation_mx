# API_TEST.md — 接口测试重构

## 目录结构

```
api-test/
├── ApiTestPage.tsx          # 接口测试主页（Tab视图）
├── ApiCasePage.tsx          # 用例管理
├── ApiSuitePage.tsx         # 套件（可选）
├── ApiExecutionPage.tsx     # 执行中心
├── ApiReportPage.tsx        # 报告
├── ImportAssetDialog.tsx    # ★ 新增：从TestAsset导入
├── ApiFolderTree.tsx        # 目录树
├── ApiCaseEditor.tsx        # 用例编辑
├── ApiCaseImport.tsx        # 旧导入（兼容）
└── ApiCaseDetail.tsx        # 用例详情
```

## 页面说明

### CasePage（用例管理）
- 数据来源：全部来自 TestAsset(API)
- 禁止：AI生成（接口测试模块不生成，只导入）
- 新增：ImportAssetDialog 导入按钮

### SuitePage（套件-可选）
- 降级为高级功能
- 菜单标签：套件（可选）
- 新增：生成推荐套件按钮

### ExecutionPage（执行中心）
- 两种模式：直接执行用例 / 执行套件
- 异步执行

### ReportPage（报告）
- 统一报告展示

## ImportAssetDialog

支持导入来源：
| 来源 | 说明 |
|------|------|
| Draft | 草稿用例 |
| Published | 已发布用例 |
| Swagger | Swagger导入的用例 |
| JSON | JSON导入的用例 |

数据源：`GET /api/assets/v2/list?asset_type=api`

## 禁止

- 接口测试模块内AI生成
- 直接创建用例（必须从测试用例模块导入或手动创建）

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 旧ApiCase数据未迁移 | 低 | 已在第二步迁移到TestAsset |
| ImportAssetDialog导入后状态不一致 | 低 | 导入后刷新列表 |

---

## 接口分析页

### 新增页面
ApiAnalyzePage — 路由 /api-test/analyze

### 功能
- 输入会话ID加载API分析结果
- 表格展示: 接口名、方法、路径、优先级、依赖
- 详情Drawer: 请求头、请求体Schema、响应体Schema
- 确认并生成用例

### 数据源
GET /workflow/result?session_id={id}&agent=APIExtraction

### 支持人工修正
- 查看提取结果
- 确认后触发生成

---

## API信息提取阶段

### 流程位置
需求理解 → **APIExtraction** → RAG → CaseGenerate → Review → Publish

### APIExtractionAgent
- 文件: `backend/app/agent/case/api_extraction_agent.py`
- 职责: 从需求文本中提取接口元数据
- 输出: ApiMeta `{session_id, apis: [{name, method, path, headers, request_schema, response_schema, depends, priority}]}`

### api_metadata 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| session_id | Integer FK | 会话ID |
| content | Text | API元数据(JSON) |
| status | String | pending/extracted/confirmed/modified |
| api_count | Integer | 提取的API数量 |

### 降级
- LLM提取失败 → 规则提取（mock）
- 结果标记 `fallback: true`
