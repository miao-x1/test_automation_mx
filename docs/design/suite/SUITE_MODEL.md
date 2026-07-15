# SUITE_MODEL.md — TestSuite 对象职责定义

## 核心原则

**套件只是组合能力。禁止保存步骤。禁止覆盖用例内容。只允许引用Case。**

## 对象定义：TestSuite

模型：`TestSuite`（表名 `test_suite`）

### 结构

```json
{
  "suite_id": 1,
  "suite_name": "用户模块回归测试",
  "case_ids": [1, 5, 3, 12]
}
```

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| name | String(200) | 套件名称 |
| description | Text | 描述 |
| suite_type | Enum | regression/smoke/custom |
| case_ids | Text(JSON) | 用例ID列表（有序） |
| env | String(20) | 执行环境 |
| base_url | String(500) | Base URL覆盖 |
| headers | Text(JSON) | 请求头覆盖 |
| variables | Text(JSON) | 变量池覆盖 |
| concurrency | Integer | 并发数 |
| fail_strategy | String | continue/stop |
| retry_count | Integer | 重试次数 |

### 禁止

- 保存步骤（步骤只在Case中）
- 覆盖用例内容（套件只引用case_ids）
- 自动生成套件
- 自动发布套件

### 允许

- 引用Case（case_ids有序列表）
- 环境配置覆盖（env/base_url/headers/variables）
- 执行编排（并发/失败策略/重试）

### 文件位置

- 模型：`backend/app/models/test_suite.py`
- API：`backend/app/api/api_test/suite_controller.py`
- 前端：`frontend/src/pages/api-test/ApiSuitePage.tsx`
