# GENERATION_ARCH.md — 生成模块重构

## 目录结构

```
services/generation/
├── __init__.py                 # 模块导出
├── context.py                  # GenerationContext + DTO定义
├── requirement_agent.py        # 需求理解Agent
├── rag_agent.py                # RAG检索Agent
├── case_generate_agent.py      # 用例生成Agent
├── review_agent.py             # 审查Agent
└── mindmap_agent.py            # 思维导图Agent
```

## GenerationContext

```python
@dataclass
class GenerationContext:
    session: Dict[str, Any]           # 会话信息
    session_id: int                   # 会话ID
    requirement: str                  # 需求内容
    requirement_summary: str          # 需求摘要
    chunks: List[str]                 # 需求分块
    features: List[Dict[str, Any]]    # 测试点/特性
    rag: Optional[Dict[str, Any]]     # RAG检索结果
    history: List[Dict[str, Any]]     # 历史生成记录
    config: Dict[str, Any]            # 配置
    user_id: Optional[int]            # 用户ID
```

## DTO定义

| DTO | 用途 | 关键字段 |
|-----|------|----------|
| CaseDTO | 用例输出 | title, preconditions, steps, assertions, expected_result, priority, tags, env |
| ReviewResultDTO | 审查结果 | passed, issues, suggestions, quality_score |
| MindmapDTO | 思维导图 | nodes, edges, summary |
| RAGResultDTO | RAG结果 | context, elements, total, has_context |

## Agent职责

### RequirementAgent
- 输入：GenerationContext
- 输出：List[Dict]（特性列表）
- 职责：理解需求，提取特性/功能点
- 禁止：数据库/HTTP/文件

### RagAgent
- 输入：GenerationContext
- 输出：RAGResultDTO
- 职责：从知识库检索相关上下文
- 禁止：数据库/HTTP/文件（通过knowledge client）
- 降级：RAG失败时使用默认业务规则

### CaseGenerateAgent
- 输入：GenerationContext
- 输出：List[CaseDTO] / Generator[CaseDTO]
- 职责：根据需求和RAG上下文生成测试用例
- 禁止：数据库/HTTP/文件
- Case First：每条用例必须包含steps+assertions

### ReviewAgent
- 输入：GenerationContext + List[CaseDTO]
- 输出：ReviewResultDTO
- 职责：审查测试用例质量
- 禁止：数据库/HTTP/文件
- 校验：标题/步骤/断言/预期结果

### MindmapAgent
- 输入：GenerationContext
- 输出：MindmapDTO
- 职责：根据需求生成思维导图
- 禁止：数据库/HTTP/文件
- 降级：AI失败时基于features构建简单结构

## Agent规则

```
禁止：
  - 直接操作数据库（通过Service层）
  - 直接发起HTTP请求（通过knowledge client）
  - 直接读写文件（通过upload service）

统一：
  - 输入：GenerationContext
  - 输出：DTO（dict/dataclass）
```

## 与Workflow的关系

```
Workflow（编排层）：
  RequirementFlow → GenerationFlow → PublishFlow → ExecutionFlow

Generation（Agent层）：
  RequirementAgent / RagAgent / CaseGenerateAgent / ReviewAgent / MindmapAgent

调用关系：
  RequirementFlow → RequirementAgent
  GenerationFlow → RagAgent → CaseGenerateAgent
  PublishFlow → ReviewAgent
```

## 风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| 旧Agent仍被直接调用 | 中 | 新Agent封装旧Agent，逐步迁移 |
| RAG降级时质量下降 | 低 | 使用默认业务规则兜底 |
| CaseDTO转换遗漏字段 | 中 | _to_case_dto 覆盖所有旧格式 |
