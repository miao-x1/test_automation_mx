# 测试资产→测试用例 恢复

## ① 新目录树

```
src/
├── pages/
│   └── test-cases/                    # 原 test-assets/ 目录重命名（可选，仅路由层变更）
│       ├── TestCasesPage.tsx          # 原 TestAssetsPage.tsx（术语替换）
│       ├── CaseList.tsx               # 原 AssetList.tsx（术语替换）
│       ├── AIGeneratePage.tsx         # AI生成页面
│       ├── CaseDraftPage.tsx          # 草稿页面
│       ├── CaseReviewPage.tsx         # 审查页面
│       ├── CasePublishPage.tsx        # 发布页面
│       └── CaseHistoryPage.tsx        # 历史页面
├── components/
│   └── test-cases/
│       ├── CaseDetailDrawer.tsx       # 原 AssetDetailDrawer.tsx（术语替换）
│       ├── CaseStatusTag.tsx          # 原 AssetStatusTag.tsx
│       └── CaseFilterBar.tsx          # 原 AssetFilterBar.tsx
├── models/
│   └── TestAsset.ts                   # 内部模型名不变
├── services/
│   └── assetService.ts                # API路径 /api/assets/v2/* 不变
└── App.tsx                            # 菜单/路由/重定向变更
```

## ② 新路由

| 旧路由 | 新路由 | 说明 |
|--------|--------|------|
| `/test-assets` | `/test-cases` | 一级路由重命名 |
| `/test-assets/ai-generate` | `/test-cases/ai-generate` | AI生成 |
| `/test-assets/list` | `/test-cases/list` | 用例列表 |
| `/test-assets/draft` | `/test-cases/draft` | 草稿 |
| `/test-assets/review` | `/test-cases/review` | 审查 |
| `/test-assets/publish` | `/test-cases/publish` | 发布 |
| `/test-assets/history` | `/test-cases/history` | 历史 |
| `/test-assets/*` | 重定向→`/test-cases/*` | 旧路由兼容重定向 |

**路由配置示例（App.tsx）：**

```tsx
// 旧路由兼容重定向
<Route path="/test-assets" element={<Navigate to="/test-cases" replace />} />
<Route path="/test-assets/*" element={<Navigate to="/test-cases/*" replace />} />

// 新路由
<Route path="/test-cases" element={<TestCasesPage />}>
  <Route index element={<Navigate to="list" replace />} />
  <Route path="ai-generate" element={<AIGeneratePage />} />
  <Route path="list" element={<CaseList />} />
  <Route path="draft" element={<CaseDraftPage />} />
  <Route path="review" element={<CaseReviewPage />} />
  <Route path="publish" element={<CasePublishPage />} />
  <Route path="history" element={<CaseHistoryPage />} />
</Route>
```

## ③ 页面图

### 一级菜单

```
┌─────────────────────────────────────────────────┐
│  📋 测试用例                                      │
│    ├── AI生成                                     │
│    ├── 用例列表                                    │
│    ├── 草稿                                       │
│    ├── 审查                                       │
│    ├── 发布                                       │
│    └── 历史                                       │
└─────────────────────────────────────────────────┘
```

### 用例列表页

```
┌──────────────────────────────────────────────────────────────────┐
│  测试用例 > 用例列表                                               │
├──────────────────────────────────────────────────────────────────┤
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                         │
│  │ 用例总计  │ │ 草稿数    │ │ 待审查    │                         │
│  │   128    │ │   23     │ │   15     │                         │
│  └──────────┘ └──────────┘ └──────────┘                         │
│                                                                  │
│  [搜索用例...]                    [AI生成] [+ 新建]               │
│                                                                  │
│  ┌────┬──────────┬────────┬────────┬──────────┬────────┐        │
│  │选择│ 用例名称  │ 优先级  │ 状态   │ 更新时间  │ 操作   │        │
│  ├────┼──────────┼────────┼────────┼──────────┼────────┤        │
│  │ ☐  │ 登录验证  │ 高     │ 草稿   │ 06-18    │ 编辑…  │        │
│  │ ☐  │ 搜索功能  │ 中     │ 已审查  │ 06-17    │ 编辑…  │        │
│  └────┴──────────┴────────┴────────┴──────────┴────────┘        │
└──────────────────────────────────────────────────────────────────┘
```

### 用例详情抽屉

```
┌────────────────────────────────────┐
│  用例详情                    [×]    │
├────────────────────────────────────┤
│  用例名称：登录验证                 │
│  优先级：  高                      │
│  状态：    草稿                    │
│  创建时间：2026-06-18              │
│  更新时间：2026-06-18              │
│                                    │
│  ── 前置条件 ──                    │
│  用户已注册账号                     │
│                                    │
│  ── 测试步骤 ──                    │
│  1. 打开登录页                     │
│  2. 输入账号密码                   │
│  3. 点击登录                       │
│                                    │
│  ── 预期结果 ──                    │
│  登录成功，跳转首页                 │
│                                    │
│  [编辑] [提交审查] [删除]           │
└────────────────────────────────────┘
```

## ④ 用户操作流程

### 流程1：查看全部用例

```
用户点击一级菜单"测试用例"
  → 默认进入"用例列表"子菜单
  → 页面展示"全部用例"列表
  → 顶部显示"用例总计"统计卡片
  → 点击某用例行 → 右侧弹出"用例详情"抽屉
```

### 流程2：AI生成用例

```
用户点击一级菜单"测试用例"
  → 点击子菜单"AI生成"
  → 进入AI生成页面
  → 输入需求描述或上传文档
  → 点击"生成"
  → AI生成用例列表
  → 用户选择用例 → 保存为草稿
```

### 流程3：草稿→审查→发布

```
用户进入"草稿"子菜单
  → 查看草稿用例列表
  → 选择草稿 → 点击"提交审查"
  → 审查人员进入"审查"子菜单
  → 审查通过 → 状态变为"已审查"
  → 进入"发布"子菜单
  → 选择已审查用例 → 点击"发布"
  → 用例状态变为"已发布"
```

### 流程4：旧链接兼容访问

```
用户访问旧链接 /test-assets/list
  → 自动重定向到 /test-cases/list
  → 页面正常展示用例列表
  → 浏览器地址栏更新为新路由
```

## ⑤ 风险说明

| 风险项 | 风险等级 | 说明 | 缓解措施 |
|--------|---------|------|---------|
| 内部模型与UI术语不一致 | 中 | 内部仍用 TestAsset 模型名和 /api/assets/v2/* 路径，但UI显示"用例"，开发者可能混淆 | 在代码注释中标注映射关系：`// TestAsset = 用例（UI术语）`；API层封装统一转换 |
| 旧路由书签失效 | 低 | 用户浏览器收藏了 /test-assets/* 旧路由 | 实现全量重定向：`/test-assets/*` → `/test-cases/*`，使用 301/replace 避免历史记录污染 |
| 菜单选中态异常 | 中 | App.tsx 中 getSelectedKeys 逻辑需同步更新，否则菜单高亮错误 | 修改 getSelectedKeys 函数，将 `/test-assets` 前缀匹配改为 `/test-cases`；同时兼容旧路由重定向后的高亮 |
| 术语遗漏 | 中 | 页面中可能残留"资产"字样或英文 draft/review/publish | 全局搜索"资产""asset""draft""review""publish"关键词，逐一替换；建立术语表约束后续开发 |
| 国际化/多语言 | 低 | 若项目支持i18n，需同步更新语言包 | 检查并更新 locales 目录下所有语言文件中相关条目 |
| 数据库无变更 | 低 | 数据库表 test_asset 不变，无迁移风险 | 无需操作，但需确保新开发人员理解表名与UI术语的映射 |
