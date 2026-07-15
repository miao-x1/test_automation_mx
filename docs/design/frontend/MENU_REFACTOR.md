# Phase 2 — 重构菜单和页面（用户可见）

## 目标

用户视角重新组织菜单和页面。禁止暴露内部概念（L1/L2/L3/CaseContent/ApiCase）。

## 最终菜单

| 序号 | 一级菜单 | 子菜单 | 路由 |
|------|---------|--------|------|
| 1 | 仪表盘 | — | /dashboard |
| 2 | 管理 | 用户/权限/项目/环境/数据源/系统设置 | /admin/* |
| 3 | 需求 | 需求列表/新建需求/上传中心/AI分析/会话管理 | /requirement/* |
| 4 | 测试设计 | AI生成/用例列表/草稿/审查/发布/历史 | /test-design/* |
| 5 | 接口测试 | 用例管理/套件(可选)/执行中心/报告中心 | /api-test/* |
| 6 | Web自动化 | 页面管理/测试设计/执行中心/报告中心/定时任务 | /web/* |
| 7 | 执行中心 | 最近执行/接口执行/Web执行/定时任务/测试报告 | /execution/* |
| 8 | 知识库 | — | /knowledge |
| 9 | 个人中心 | — | /profile |
| 10 | 系统设置 | — | /settings |

## 步骤1：菜单重构

### 删除
- "测试资产" — 已在 Phase 1 删除
- "测试用例" — 替换为"测试设计"
- "Android"（disabled 占位） — 移除

### 替换
- "测试用例" → "测试设计"，路由 /test-cases → /test-design
- "Web" → "Web自动化"

### 新增
- "知识库" 一级菜单（路由 /knowledge，图标 BookOutlined）

### 修改文件
- `frontend/src/App.tsx`
  - menuItems: /test-cases-group → /test-design-group，label "测试设计"
  - Web group label "Web" → "Web自动化"
  - 删除 Android disabled 菜单项
  - 新增 { key: '/knowledge', label: '知识库', icon: <BookOutlined /> }
  - getSelectedKeys: /test-cases → /test-design
  - Routes: /test-cases → /test-design，element <TestDesignPage />
  - 兼容重定向: /test-assets/* → /test-design/*, /test-cases/* → /test-design/*

## 步骤2：页面迁移

### 目录结构
```
pages/test-assets/          →  pages/test-design/
  TestAssetsPage.tsx        →  TestDesignPage.tsx
  AssetDetailDrawer.tsx     →  CaseDrawer.tsx
  GeneratePage.tsx          →  GeneratePage.tsx（不变）
  DraftPage.tsx             →  DraftPage.tsx（不变）
  ReviewPage.tsx            →  ReviewPage.tsx（不变）
  PublishPage.tsx           →  PublishPage.tsx（不变）
  HistoryPage.tsx           →  HistoryPage.tsx（不变）
  constants.ts              →  constants.ts（不变）
```

### 组件重命名
- `TestAssetsPage` → `TestDesignPage`
- `AssetDetailDrawer` → `CaseDrawer`

### 修改文件
- `frontend/src/pages/test-design/TestDesignPage.tsx` — 新文件，导入 CaseDrawer
- `frontend/src/pages/test-design/CaseDrawer.tsx` — 新文件，组件名 CaseDrawer
- `frontend/src/App.tsx` — import TestDesignPage from './pages/test-design/TestDesignPage'

## 步骤3：禁止内部概念

### 页面状态（用户可见）
只允许显示：
- draft → 草稿
- reviewed → 已审查
- published → 已发布
- executed → 已执行
- failed → 失败

### 禁止出现
- L1 → 改为"测试设计"
- L2 → 改为"用例编译"
- L3 → 改为"脚本生成"
- CaseContent / ApiCase — 仅内部代码使用，用户界面不出现

### 修改文件
- `frontend/src/pages/test-case/CaseGenerate.tsx` — levelMap: L1→测试设计, L2→用例编译, L3→脚本生成
- `frontend/src/stores/uploadStore.ts` — progress_msg: L1→需求理解, L2→用例编译
- `frontend/src/pages/session/SessionCenter.tsx` — Select: L1→测试设计, L2→用例编译
- `frontend/src/pages/upload/UploadTaskCenter.tsx` — statusMap + Select: L1→设计中, L2→编译中

## 步骤4：生成完成行为

### 禁止
- 自动跳转到接口测试或其他页面

### 允许（停留当前页）
生成完成后显示三个按钮：
1. **查看结果** — 跳转 /test-design/draft
2. **继续生成** — 重新触发生成
3. **发布** — 调用 /api/assets/v2/publish 发布当前批次

### 修改文件
- `frontend/src/pages/test-case/CaseGenerate.tsx`
  - 删除 "查看任务中心" 和 "查看测试资产" 按钮
  - 新增 "查看结果"（→ /test-design/draft）、"继续生成"、"发布" 按钮

## 步骤5：发布后导入

### 允许导入目标
- 接口测试（/api-test/cases）
- Web自动化（/web/create）
- Android（/android，预留）

### 推荐目标自动识别
根据 asset_type 自动推荐：
| asset_type | 推荐目标（优先级排序） |
|-----------|---------------------|
| api | 接口测试 > Web自动化 |
| web | Web自动化 > 接口测试 |
| android | Android > 接口测试 |
| manual | 接口测试 > Web自动化 |

### 修改文件
- `frontend/src/pages/test-design/CaseDrawer.tsx`
  - 新增 importTargetMap 映射表
  - published 状态显示 "导入到" Dropdown 按钮
  - 使用 useNavigate 跳转到目标模块

## 验证

- [x] TypeScript 编译通过（0 errors）
- [x] 菜单结构符合最终菜单规范
- [x] 路由 /test-design/* 正确映射
- [x] 旧路由 /test-assets/* /test-cases/* 兼容重定向到 /test-design/*
- [x] L1/L2/L3 不出现在用户界面
- [x] 生成完成后停留当前页，显示查看结果/继续生成/发布
- [x] 发布后显示导入到按钮，自动识别推荐目标
