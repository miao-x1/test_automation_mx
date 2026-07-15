# CASE_GENERATOR.md — 测试用例生成规范

## 生成目标

输出完整可执行用例，生成后即可执行。

## 必须生成的结构

```json
{
  "title": "创建用户-正常流程",
  "preconditions": [
    "用户已登录",
    "数据库已清空测试数据"
  ],
  "steps": [
    {
      "action": "发送创建用户请求",
      "url": "/api/users",
      "method": "POST",
      "headers": {
        "Content-Type": "application/json",
        "Authorization": "Bearer ${token}"
      },
      "body": {
        "name": "测试用户",
        "email": "test@example.com"
      }
    }
  ],
  "assertions": [
    {
      "path": "$.status",
      "operator": "eq",
      "expected": 201
    },
    {
      "path": "$.data.name",
      "operator": "eq",
      "expected": "测试用户"
    }
  ],
  "expected_result": "返回201，用户创建成功，name字段为'测试用户'",
  "priority": "P1",
  "tags": ["用户模块", "创建", "正向"],
  "env": "test"
}
```

## 校验规则

| 规则 | 要求 | 违反后果 |
|------|------|----------|
| 至少1步 | steps.length >= 1 | executable=false |
| 至少1断言 | assertions.length >= 1 | executable=false |
| 至少1预期结果 | expected_result 非空 | 警告 |
| 步骤结构化 | 每步含 action/url/method | 校验失败 |
| 断言结构化 | 每断言含 path/operator/expected | 校验失败 |

## 禁止

- 自然语言步骤（如"点击登录按钮"→ 必须转为 `{action: "点击登录按钮", url: "/login", method: "POST"}`）
- 空步骤
- 只有标题没有内容

## 自动校验

```python
def validate_executable(self) -> bool:
    content = self.get_content()
    if not content:
        return False
    steps = content.get("steps", [])
    assertions = content.get("assertions", [])
    has_steps = isinstance(steps, list) and len(steps) > 0
    has_assertions = isinstance(assertions, list) and len(assertions) > 0
    self.executable = has_steps and has_assertions
    return self.executable
```

## set_content 自动触发校验

```python
def set_content(self, data: dict):
    self.content_json = json.dumps(data, ensure_ascii=False)
    self.validate_executable()  # 自动计算 executable
```

## 生成流程中的保障

1. AI生成 → 输出完整结构化用例
2. 保存时 → `set_content()` 自动校验 executable
3. 列表显示 → 步骤数/断言数/可执行标记
4. 用户可见 → "立即执行"按钮仅在 executable=true 时显示
