# 数据迁移方案：CaseContent / ApiCase / 旧TestAsset → 统一 TestAsset

> 生成时间：2026-06-17
> 状态：**已执行完成**

---

## 一、迁移概览

| 源模型 | 源表 | 目标表 | 迁移数 | 状态 |
|--------|------|--------|--------|------|
| CaseContent | case_content | test_asset | 385 | ✅ 完成 |
| ApiCase | api_case | test_asset | 217 | ✅ 完成 |
| 旧TestAsset | test_asset → web_script_asset | test_asset | 24 | ✅ 完成 |
| **总计** | | | **546** | **✅ 0错误** |

---

## 二、统一领域模型 TestAsset

### 2.1 字段定义

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer PK | 主键 |
| session_id | Integer FK | 关联会话ID |
| project_id | Integer | 项目ID |
| asset_type | String(20) | 资产类型: api/web/android/manual |
| source_type | String(20) | 来源: ai/manual/swagger/import/reused |
| title | String(500) | 资产标题 |
| description | Text | 描述 |
| content_json | Text | 统一内容(JSON) |
| status | String(20) | 状态: draft/reviewed/published/executed/failed |
| version | Integer | 版本号 |
| published | Boolean | 是否已发布 |
| execution_state | Text | 执行状态(JSON) |
| priority | String(5) | 优先级: P0/P1/P2/P3 |
| tags | String(500) | 标签(逗号分隔) |
| creator | (user_id) | 创建者 |
| created_at | DateTime | 创建时间 |
| updated_at | DateTime | 更新时间 |
| legacy_case_content_id | Integer | 旧CaseContent ID |
| legacy_api_case_id | Integer | 旧ApiCase ID |
| legacy_test_asset_id | Integer | 旧TestAsset ID |
| is_deleted | Boolean | 软删除 |

### 2.2 枚举定义

**AssetType**:
- `api` - API接口测试
- `web` - Web UI测试
- `android` - Android测试
- `manual` - 手动/通用测试用例

**AssetStatus**:
- `draft` → `reviewed` → `published` → `executed`
- `failed` (任意阶段可进入)

**SourceType**:
- `ai` / `manual` / `swagger` / `import` / `reused`

### 2.3 content_json 结构

```json
{
  "method": "POST",
  "url": "/api/login",
  "headers": {"Content-Type": "application/json"},
  "body": {"username": "admin"},
  "timeout": 5000,
  "precondition": "用户已注册",
  "steps": [...],
  "assertions": [...],
  "pre_steps": [...],
  "variables": {},
  "env_override": {},
  "runtime": {"retry": 0, "env": "test"}
}
```

Web脚本资产：
```json
{
  "script_content": "def test_login(): ...",
  "script_language": "python",
  "script_path": "",
  "input_config": {},
  "exec_config": {}
}
```

---

## 三、迁移映射规则

### 3.1 CaseContent → TestAsset

| CaseContent字段 | TestAsset字段 | 转换规则 |
|-----------------|---------------|----------|
| id | legacy_case_content_id | 直接映射 |
| title | title | 直接映射 |
| precondition | description | 直接映射 |
| test_type | asset_type | API→api, UI/WEB→web, ANDROID→android |
| case_status | status | draft→draft, review→reviewed, published→published |
| source_type | source_type | ai→ai, manual→manual, swagger→swagger |
| steps + expected | content_json | 合并为统一JSON |
| priority | priority | 直接映射 |
| tags | tags | 直接映射 |
| version | version | 直接映射 |
| user_id | user_id | 直接映射 |
| api_case_id | legacy_api_case_id | 直接映射 |

### 3.2 ApiCase → TestAsset

| ApiCase字段 | TestAsset字段 | 转换规则 |
|-------------|---------------|----------|
| id | legacy_api_case_id | 直接映射 |
| title | title | 直接映射 |
| description | description | 直接映射 |
| test_type | asset_type | API→api, UI→web, ANDROID→android |
| status | status | draft→draft, review→reviewed, published→published, deprecated→draft |
| source | source_type | ai→ai, manual→manual, swagger→swagger |
| steps + assertions + extracts + method + url | content_json | 合并为统一JSON |
| priority | priority | 直接映射 |
| tags | tags | 直接映射 |
| version | version | 直接映射 |
| user_id | user_id | 直接映射 |
| source_content_id | legacy_case_content_id | 关联CaseContent |

### 3.3 旧TestAsset → TestAsset

| 旧TestAsset字段 | TestAsset字段 | 转换规则 |
|-----------------|---------------|----------|
| id | legacy_test_asset_id | 直接映射 |
| name | title | 直接映射 |
| asset_type | asset_type | web→web, api→api |
| status | status | ready/completed→published, 其他→draft |
| source | source_type | generated→ai, reused→reused, manual→manual |
| script_content + input_config + exec_config | content_json | 合并为统一JSON |
| version | version | 直接映射 |
| user_id | user_id | 直接映射 |

---

## 四、旧表处理

| 旧表 | 处理方式 | 状态 |
|------|----------|------|
| case_content | 保留（不删除） | ✅ |
| api_case | 保留（不删除） | ✅ |
| case_task | 保留（不删除） | ✅ |
| test_asset | 重命名为 web_script_asset | ✅ 已执行 |

旧表数据完整保留，通过 `legacy_*_id` 字段可双向查询。

---

## 五、兼容旧接口

| 旧API | 兼容方式 |
|-------|----------|
| GET /case/list | 保留，直接查case_content表 |
| GET /test-assets/drafts | 保留，直接查旧逻辑 |
| POST /test-assets/publish | 保留，同步写入TestAsset |
| GET /api-test/cases | 保留，直接查api_case表 |
| POST /api-test/import/ai | 保留，标记兼容，重定向到AssetService |
| POST /api-test/sync/to-api-test | 保留，标记兼容，推荐使用 /assets/v2/publish |
| GET /assets | 保留，查web_script_asset表 |
| GET /assets/v2/* | 新API，查test_asset表 |

---

## 六、迁移脚本

```bash
# 预览模式（不写入数据）
cd backend
python -m migrations.migrate_case_to_asset --dry-run

# 实际迁移
python -m migrations.migrate_case_to_asset

# 幂等：可重复执行，已迁移的会跳过
```

---

## 七、回滚方案

如果迁移出现问题：

1. **新表test_asset可安全删除**：旧表数据完整保留
2. **web_script_asset可重命名回test_asset**：`RENAME TABLE web_script_asset TO test_asset`
3. **旧API继续工作**：所有旧路由未删除

```sql
-- 回滚SQL（仅在紧急情况下使用）
DROP TABLE IF EXISTS test_asset;
RENAME TABLE web_script_asset TO test_asset;
```

---

## 八、风险说明

| # | 风险 | 影响 | 缓解措施 |
|---|------|------|----------|
| 1 | 旧API写入CaseContent/ApiCase不会同步到TestAsset | 数据不一致 | 新代码统一使用TestAsset；旧API逐步废弃 |
| 2 | TestSuite.case_ids引用ApiCase | 迁移后引用断裂 | TestSuite暂时保留引用ApiCase，后续迁移 |
| 3 | 前端旧页面仍调旧API | 用户看到旧数据 | 旧页面重定向到新页面 |
| 4 | web_script_asset表名变更 | Task.test_assets关系需更新 | 已更新Task模型引用LegacyWebAsset |
