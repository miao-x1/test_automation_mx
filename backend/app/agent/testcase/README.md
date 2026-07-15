# TestCase Agent 模块

企业级测试用例生成智能体体系。

## 目录结构

```
backend/app/agent/testcase/
├── __init__.py
├── requirement_analysis_agent.py   # 需求解析Agent
├── test_point_analysis_agent.py    # 测试点分析Agent
├── testcase_generator_agent.py     # 用例生成Agent（含RAG集成）
├── testcase_review_agent.py        # 用例审核Agent
└── README.md
```

## Agent 列表

| Agent名称 | 类名 | 职责 | 模型 |
|-----------|------|------|------|
| requirement_analysis_agent | RequirementAnalysisAgent | 解析需求，提取业务模块/功能点/流程/范围 | qwen-plus |
| test_point_analysis_agent | TestPointAnalysisAgent | 分析测试点，覆盖5种类型 | qwen-plus |
| testcase_generator_agent | TestCaseGeneratorAgent | 生成结构化用例，内置RAG检索 | deepseek-chat |
| testcase_review_agent | TestCaseReviewAgent | 审核用例质量，评分+建议 | qwen-plus |

## 调用流程

```
需求输入
  ↓
RequirementAnalysisAgent        → business_module, function_points, business_flow, test_scope
  ↓
TestPointAnalysisAgent          → test_points[] (功能/异常/边界/权限/数据校验)
  ↓
TestCaseGeneratorAgent          → test_cases[] (含RAG检索: 检索→TopK→过滤→生成)
  ↓
TestCaseReviewAgent             → reviews[] (score, suggestions, issues)
  ↓
存储数据库 + 生成思维导图
```

## RAG集成

TestCaseGeneratorAgent 内置RAG检索，流程：

1. **检索**: 根据测试点名称、业务模块、关键词构建查询
2. **TopK**: 每类检索最多10条结果
3. **过滤**: 去除相似度低于0.3的结果
4. **生成**: 将过滤后的结果作为上下文发送给LLM

```python
# RAG配置
RAG_TOP_K = 10          # 每类检索最大数量
RAG_MIN_SCORE = 0.3     # 最低相似度阈值
RAG_MAX_CASES = 5       # 发送给LLM的历史用例最大数
RAG_MAX_ELEMENTS = 10   # 发送给LLM的元素最大数
```

## 工作流编排

通过 TaskOrchestrator 编排，工作流名称：`testcase_generation`

```python
from app.agent_runtime.orchestrator import get_task_orchestrator

orchestrator = get_task_orchestrator()
result = await orchestrator.run(
    requirement="测试商城登录功能",
    workflow_name="testcase_generation",
)
```

## 数据库表

| 表名 | 模型类 | 说明 |
|------|--------|------|
| test_requirement | TestRequirement | 测试需求 |
| test_case_point | TestCasePoint | 测试点 |
| test_case | TestCase | 测试用例 |
| test_case_review | TestCaseReview | 用例审核结果 |
| mind_map | MindMap | 思维导图数据 |

## API端点

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | /api/v1/testcase/generate | 开始测试用例生成 |
| GET | /api/v1/testcase/{task_id} | 查询生成结果 |
| GET | /api/v1/testcase/mindmap/{task_id} | 获取思维导图 |

## Prompt文件

```
backend/app/prompts/testcase/
├── __init__.py
├── requirement_analysis_prompt.py   # 需求解析Prompt
├── test_point_prompt.py             # 测试点分析Prompt
├── testcase_generate_prompt.py      # 用例生成Prompt
└── review_prompt.py                 # 用例审核Prompt
```

## 扩展指南

### 新增Agent

1. 在 `backend/app/agent/testcase/` 下创建新Agent文件
2. 继承 `BaseAgent`（`app.agent.base_agent`）
3. 实现 `execute(**kwargs)` 方法
4. 在 `agent_runtime/registry.py` 的 `DEFAULT_AGENTS` 中注册
5. 在 `agent_runtime/orchestrator.py` 的工作流中添加步骤

### 新增工作流步骤

```python
WorkflowStep(
    name="步骤名称",
    agent_name="agent_name",
    action="execute",
    input_key="上一步的output_key",  # 可选
    output_key="当前步骤的输出key",
    required=True,
    timeout=120.0,
    payload_builder=自定义构建函数,  # 可选，用于多输入步骤
)
```

## 后续接入脚本生成Agent

1. 在 `prompts/testcase/` 下新增 `script_generate_prompt.py`
2. 在 `agent/testcase/` 下新增 `ScriptGeneratorAgent`
3. 在 `TestCaseGenerationWorkflow` 中添加步骤：

```python
WorkflowStep(
    name="脚本生成",
    agent_name="script_generator_agent",
    action="execute",
    input_key="test_cases",
    output_key="scripts",
    required=False,
    timeout=180.0,
)
```

4. 在 `registry.py` 中注册新Agent
