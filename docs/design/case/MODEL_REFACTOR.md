# MODEL_REFACTOR.md — 收口领域模型

## 问题

存在3个测试对象模型，形成重复：

```
AI生成 → CaseContent → 同步 → ApiCase → 执行
同时：TestAsset 也参与执行
```

## 目标架构

```
唯一资产：TestAsset
兼容：CaseContent / ApiCase
最终：TestAsset → Execution
```

---

## 步骤1：TestAsset 模型

### 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| title | String(500) | 用例标题 |
| asset_type | String(20) | api/web/android/manual |
| source_type | String(20) | ai/manual/swagger/import/reused |
| status | String(20) | draft/reviewed/published/executed/failed |
| content_json | Text | 完整可执行用例内容 |
| session_id | Integer | 关联会话 |
| requirement_id | Integer | **新增** 关联需求 |
| published | Boolean | 是否已发布 |
| executable | Boolean | 是否可执行 |
| priority | String(5) | P0/P1/P2/P3 |
| tags | String(500) | 标签 |
| version | Integer | 版本号 |
| created_by | Integer | 创建人 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |

### content_json 规范

```json
{
  "preconditions": ["前置条件1"],
  "steps": [
    {"action": "POST /api/users", "url": "/api/users", "method": "POST", "headers": {}, "body": {}}
  ],
  "assertions": [
    {"path": "$.status", "operator": "eq", "expected": 200}
  ],
  "expected_result": "返回201",
  "env": "test",
  "variables": {}
}
```

### validate_executable()

```python
def validate_executable(self) -> bool:
    content = self.get_content()
    steps = content.get("steps", [])
    assertions = content.get("assertions", [])
    has_steps = isinstance(steps, list) and len(steps) > 0
    has_assertions = isinstance(assertions, list) and len(assertions) > 0
    self.executable = has_steps and has_assertions
    return self.executable
```

---

## 步骤2：generation_flow.py 修改

**禁止**：写 CaseContent
**改**：生成 TestAsset（status=draft）

content_json 使用 Case First 格式（preconditions/steps/assertions/expected_result/env/variables），不再使用旧格式（method/url/headers/body）。

创建后自动调用 `asset.validate_executable()`。

---

## 步骤3：兼容方法

### CaseContent.to_test_asset()

```python
def to_test_asset(self) -> dict:
    """转换为 TestAsset 字典（用于迁移/兼容）"""
    # 解析 steps/preconditions/tags
    # 映射 test_type → asset_type
    # 映射 source_type
    # 返回 TestAsset 构造参数字典
```

### ApiCase.from_test_asset()

```python
@staticmethod
def from_test_asset(asset) -> dict:
    """从 TestAsset 生成 ApiCase 字典（兼容旧接口测试模块）"""
    # 从 content_json 提取 steps/assertions
    # 转换为 ApiCase 格式
```

### 禁止

- 直接执行 CaseContent（必须转为 TestAsset）
- 直接执行 ApiCase（应通过 TestAsset.to_execution_json()）
- CaseContent → ApiCase 同步

---

## 步骤4：services/assets/ 统一服务

| 文件 | 职责 |
|------|------|
| asset_service.py | CRUD：create/get/list/update/delete/stats |
| publish_service.py | 发布流程：review/publish/unpublish |
| asset_query.py | 查询：多维度筛选/统计/可执行列表 |

全部基于 TestAsset（非 TestAssetV2）。

---

## 步骤5：迁移脚本

```
scripts/migrate_case_asset.py
```

| 源 | 目标 | 规则 |
|----|------|------|
| CaseContent | TestAsset | to_test_asset()，幂等，禁止覆盖 |
| ApiCase | TestAsset | 手动转换，幂等，禁止覆盖 |
| TestAsset | TestAsset | validate_executable() 更新标记 |

用法：
```bash
python scripts/migrate_case_asset.py           # 执行迁移
python scripts/migrate_case_asset.py --dry-run  # 预览
```

---

## 文件变更

| 文件 | 变更 |
|------|------|
| models/test_asset.py | 新增 requirement_id 字段 |
| models/case_content.py | 新增 to_test_asset() 方法 |
| models/api_case.py | 新增 from_test_asset()，标记 to_case_json() 废弃 |
| services/workflow/generation_flow.py | content_json 改为 Case First 格式，调用 validate_executable() |
| services/assets/asset_service.py | 重写（基于 TestAsset） |
| services/assets/publish_service.py | 新建 |
| services/assets/asset_query.py | 新建 |
| services/assets/__init__.py | 更新导出 |
| scripts/migrate_case_asset.py | 新建 |

---

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 旧API仍用 CaseContent/ApiCase | 中 | 保留兼容，新增 to_test_asset()/from_test_asset() |
| 迁移数据 content_json 格式不一致 | 中 | safe_json_parse + 降级处理 |
| requirement_id 外键约束 | 低 | SET NULL，允许为空 |
