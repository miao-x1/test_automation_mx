# CASE_MODEL.md — TestCase 对象职责定义

## 核心原则

**测试用例本身必须完整可执行。禁止只生成标题。禁止步骤为空。**

## 对象定义：TestCase

内部模型：`TestAsset`（表名 `test_asset`）

用户视角：**测试用例**（非"测试资产"）

### 必须包含

| 字段 | 类型 | 说明 | 必须 |
|------|------|------|------|
| title | String(500) | 用例标题 | 是 |
| preconditions | List[str] | 前置条件 | 否 |
| steps | List[Step] | 测试步骤 | 是（≥1） |
| assertions | List[Assertion] | 断言 | 是（≥1） |
| expected_result | String | 预期结果 | 是（≥1） |
| env | String | 执行环境 | 否 |
| variables | Dict | 变量池 | 否 |
| tags | List[str] | 标签 | 否 |
| priority | String | 优先级 P0-P3 | 否 |
| executable | Boolean | 是否可执行 | 自动计算 |

### Step 结构

```json
{
  "action": "发送请求/点击按钮",
  "url": "/api/users",
  "method": "POST",
  "headers": {"Content-Type": "application/json"},
  "body": {"name": "test"},
  "timeout": 5000
}
```

### Assertion 结构

```json
{
  "path": "$.status",
  "operator": "eq",
  "expected": 200
}
```

### 可执行校验规则

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

### 状态机

```
draft → reviewed → published → executed
                              → failed
```

### 禁止

- 只生成标题，步骤为空
- 自然语言步骤（必须结构化）
- 必须先建套件才能执行

### 文件位置

- 模型：`backend/app/models/test_asset.py`
- API：`backend/app/api/assets_v2.py`
- 前端：`frontend/src/pages/test-assets/`
