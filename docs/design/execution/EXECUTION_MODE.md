# EXECUTION_MODE.md — 执行入口重构

## 核心原则

**用例可直接执行，无需套件。套件是可选的高级功能。**

## 模式1：直接执行用例（默认）

### 入口

```
测试用例 → 用例列表/草稿/审查/发布 → 立即执行
```

### 流程

```
Case → Execution → Report
```

### API

```
POST /api/assets/v2/execution/run/case
```

### 请求

```json
{
  "case_id": 1,
  "env": "test",
  "base_url": "http://localhost:8080"
}
```

### 响应

```json
{
  "execution_id": 42,
  "case_id": 1,
  "status": "queued",
  "message": "用例执行已提交"
}
```

### 前端调用

```typescript
import { runCase } from './constants';

const result = await runCase(caseId);
message.success(`执行已提交 (ID: ${result.execution_id})`);
```

### 触发位置

| 页面 | 触发方式 |
|------|----------|
| 用例列表 | 操作列"执行"按钮 |
| 草稿页 | 操作列"执行"按钮（executable=true时） |
| 审查页 | 操作列"执行"按钮 |
| 发布页 | 操作列"执行"按钮 |
| 用例详情Drawer | 顶部"立即执行"按钮 |

---

## 模式2：执行套件（可选高级功能）

### 入口

```
接口测试 → 套件（可选） → 执行
```

### 流程

```
Suite → Execution → Report
```

### API

```
POST /api/assets/v2/execution/run/suite
```

### 请求

```json
{
  "suite_id": 1,
  "env": "test"
}
```

### 响应

```json
{
  "execution_id": 43,
  "suite_id": 1,
  "case_count": 5,
  "status": "queued",
  "message": "套件执行已提交"
}
```

### 前端调用

```typescript
import { runSuite } from './constants';

const result = await runSuite(suiteId);
message.success(`套件执行已提交 (${result.case_count}条用例)`);
```

---

## 执行引擎内部

两种模式最终都通过 `ExecutionDispatcher.dispatch()` 执行：

```
run/case  → dispatch(asset_ids=[case_id])
run/suite → dispatch(asset_ids=case_ids_from_suite)
```

## 对比

| 维度 | 直接执行用例 | 执行套件 |
|------|-------------|----------|
| 入口 | 测试用例菜单 | 接口测试菜单 |
| 前置条件 | executable=true | 套件已创建 |
| API | /execution/run/case | /execution/run/suite |
| 适用场景 | 单条用例快速验证 | 批量回归/冒烟 |
| 用户 | 所有用户 | 高级用户 |
