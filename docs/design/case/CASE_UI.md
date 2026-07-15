# CASE_UI.md — 测试用例页面重构

## 一级菜单

```
测试用例
├── AI生成
├── 用例列表
├── 草稿
├── 审查
├── 发布
└── 历史
```

## CaseList 页面

### 列表显示

| 列 | 字段 | 说明 |
|----|------|------|
| ID | id | 用例ID |
| 标题 | title | 用例标题 |
| 类型 | asset_type | API/Web/Android/通用 |
| 步骤数 | steps.length | 从content_json解析 |
| 断言数 | assertions.length | 从content_json解析 |
| 状态 | status | 草稿/已审查/已发布/已执行/失败 |
| 可执行 | executable | 是/否 |
| 标签 | tags | 标签列表 |

### 操作按钮

| 按钮 | 条件 | 行为 |
|------|------|------|
| 查看详情 | 始终 | 打开Drawer |
| 编辑 | 始终 | 打开编辑Modal |
| 复制 | 始终 | 复制用例 |
| 发布 | status=draft/reviewed | 发布用例 |
| **立即执行** | executable=true | POST /execution/run/case |
| 删除 | 始终 | 确认后删除 |

### 批量操作

- 批量发布
- 批量执行（仅executable=true的用例）
- 批量删除

### 用例详情 Drawer

```
┌─────────────────────────────────────────┐
│ 用例详情                    [发布] [立即执行] │
├─────────────────────────────────────────┤
│ ID: 1    标题: xxx    类型: API          │
│ 状态: 草稿  来源: AI   优先级: P1        │
│ 可执行: 是  版本: 1                       │
├─────────────────────────────────────────┤
│ 前置条件                                  │
│ • 用户已登录                              │
├─────────────────────────────────────────┤
│ 步骤 (2)                                 │
│ # │ 操作     │ 方法  │ URL              │
│ 1 │ 创建用户 │ POST │ /api/users       │
│ 2 │ 查询用户 │ GET  │ /api/users/1     │
├─────────────────────────────────────────┤
│ 断言 (2)                                 │
│ # │ 路径       │ 操作符 │ 预期值         │
│ 1 │ $.status   │ eq    │ 200           │
│ 2 │ $.data.id  │ eq    │ 1             │
├─────────────────────────────────────────┤
│ 预期结果                                  │
│ 返回201，用户ID为1                        │
└─────────────────────────────────────────┘
```

### 禁止

- 必须先建套件才能执行
- 生成成功自动跳转
- 页面跳页面（用Drawer/Modal）

### 文件变更

| 文件 | 变更 |
|------|------|
| `pages/test-assets/constants.ts` | 新增 executable 字段、runCase/runSuite 函数 |
| `pages/test-assets/AssetDetailDrawer.tsx` | 增强显示步骤/断言/前置条件/预期结果，新增"立即执行"按钮 |
| `pages/test-assets/DraftPage.tsx` | 操作列新增"执行"按钮 |
| `pages/test-assets/ReviewPage.tsx` | 操作列新增"执行"按钮 |
| `pages/test-assets/PublishPage.tsx` | 操作列新增"执行"按钮 |
