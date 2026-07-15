"""
CaseSet - 用例集输出模型

CaseAgent 的输出格式，包含生成的测试用例和元信息。
"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# 用例类型枚举
CaseType = Literal["functional", "boundary", "error", "compatibility", "security"]

# 优先级枚举
Priority = Literal["high", "medium", "low"]


class CaseStep(BaseModel):
    """测试步骤"""
    step_no: int = 0
    action: str = ""  # 操作描述
    target: str = ""  # 目标元素/接口
    value: str = ""   # 输入值
    expected: str = ""  # 预期结果


class CaseItem(BaseModel):
    """单条测试用例"""
    id: str = ""
    title: str = ""
    description: str = ""

    # 用例分类
    case_type: CaseType = "functional"
    priority: Priority = "medium"
    tags: List[str] = []

    # 用例内容
    precondition: str = ""
    steps: List[CaseStep] = []
    steps_text: str = ""  # 纯文本格式的步骤（兼容）
    expected: str = ""

    # 引用追踪
    references: List[str] = []  # 引用的知识库 chunk
    source_chunk_ids: List[int] = []

    # 元信息
    confidence: float = 0.0  # LLM 生成置信度
    review_score: float = 0.0  # 审查评分
    review_issues: List[str] = []

    class Config:
        json_schema_extra = {
            "example": {
                "id": "case_001",
                "title": "用户登录成功",
                "case_type": "functional",
                "priority": "high",
                "precondition": "用户已注册",
                "steps": [
                    {"step_no": 1, "action": "打开登录页", "target": "/login"},
                    {"step_no": 2, "action": "输入用户名", "target": "username输入框", "value": "testuser"},
                    {"step_no": 3, "action": "输入密码", "target": "password输入框", "value": "******"},
                    {"step_no": 4, "action": "点击登录按钮", "target": "登录按钮"},
                ],
                "expected": "登录成功，跳转到首页",
                "references": ["[flow:登录流程]", "[api:POST /api/login]"]
            }
        }

    def to_storage_dict(self) -> Dict[str, Any]:
        """转换为数据库存储格式"""
        steps_str = self.steps_text or "\n".join(
            f"{s.step_no}. {s.action}" + (f" -> {s.target}" if s.target else "")
            for s in self.steps
        )
        return {
            "title": self.title,
            "case_type": self.case_type,
            "precondition": self.precondition,
            "steps": steps_str,
            "expected": self.expected,
            "priority": self.priority,
            "tags": ",".join(self.tags),
        }


class CaseSet(BaseModel):
    """
    用例集 - CaseAgent 的输出

    包含一次生成任务产生的所有用例
    """
    # 标识
    generation_id: str = ""
    project_id: str = ""
    task_id: str = ""
    version: int = 1

    # 用例列表
    cases: List[CaseItem] = []
    total: int = 0

    # 统计
    by_type: Dict[str, int] = Field(default_factory=dict)
    by_priority: Dict[str, int] = Field(default_factory=dict)

    # 来源追踪
    requirement_context_id: Optional[str] = None
    retrieved_chunk_ids: List[int] = []
    knowledge_ids: List[int] = []

    # 生成配置
    config: Dict[str, Any] = Field(default_factory=dict)

    # 元信息
    created_at: Optional[datetime] = None
    created_by: str = ""
    llm_model: str = ""
    llm_usage: Dict[str, int] = Field(default_factory=dict)  # {prompt_tokens, completion_tokens, total_tokens}
    latency_ms: int = 0

    class Config:
        json_schema_extra = {
            "example": {
                "generation_id": "gen_20240115_001",
                "project_id": "proj_001",
                "task_id": "task_123",
                "cases": [
                    {
                        "id": "case_001",
                        "title": "用户登录成功",
                        "case_type": "functional",
                        "priority": "high"
                    }
                ],
                "total": 1,
                "by_type": {"functional": 1},
                "by_priority": {"high": 1}
            }
        }

    def compute_stats(self) -> None:
        """计算统计信息"""
        self.total = len(self.cases)

        self.by_type = {}
        self.by_priority = {}

        for case in self.cases:
            # 按类型统计
            ct = case.case_type
            self.by_type[ct] = self.by_type.get(ct, 0) + 1

            # 按优先级统计
            pr = case.priority
            self.by_priority[pr] = self.by_priority.get(pr, 0) + 1

    def get_cases_by_type(self, case_type: CaseType) -> List[CaseItem]:
        """按类型筛选用例"""
        return [c for c in self.cases if c.case_type == case_type]

    def get_cases_by_priority(self, priority: Priority) -> List[CaseItem]:
        """按优先级筛选用例"""
        return [c for c in self.cases if c.priority == priority]

    def to_mindmap_data(self) -> Dict[str, Any]:
        """转换为思维导图数据结构"""
        type_labels = {
            "functional": "功能测试",
            "boundary": "边界测试",
            "error": "异常测试",
            "compatibility": "兼容性测试",
            "security": "安全测试",
        }

        # 按类型分组
        groups: Dict[str, List[Dict]] = {}
        for case in self.cases:
            ct = case.case_type
            if ct not in groups:
                groups[ct] = []
            groups[ct].append({
                "name": case.title,
                "priority": case.priority,
            })

        children = []
        for ct, items in groups.items():
            children.append({
                "name": type_labels.get(ct, ct),
                "children": items,
            })

        return {
            "name": f"测试用例 ({self.total}条)",
            "children": children,
        }

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return self.model_dump()


class CaseGenerationConfig(BaseModel):
    """用例生成配置"""
    case_types: List[CaseType] = ["functional", "boundary", "error"]
    max_cases: int = 20
    focus_areas: List[str] = []  # 额外关注点
    use_rag: bool = True
    knowledge_ids: List[int] = []  # 指定参考的知识
    score_threshold: float = 0.6
    top_k: int = 10

    class Config:
        json_schema_extra = {
            "example": {
                "case_types": ["functional", "boundary", "error", "security"],
                "max_cases": 30,
                "use_rag": True,
                "knowledge_ids": [1, 2, 3]
            }
        }
