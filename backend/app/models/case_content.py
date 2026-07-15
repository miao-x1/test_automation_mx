"""
用例内容模型

存储单条测试用例的详细信息
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey
from app.models.base import OwnedModel


class CaseType(str, enum.Enum):
    """用例类型"""
    FUNCTIONAL = "functional"   # 功能测试
    ERROR = "error"             # 异常测试
    BOUNDARY = "boundary"       # 边界测试


class CasePriority(str, enum.Enum):
    """用例优先级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CaseContent(OwnedModel):
    """用例内容"""
    case_task_id = Column(
        Integer, ForeignKey("case_task.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="关联用例任务ID"
    )
    title = Column(String(200), nullable=False, comment="用例标题")
    case_type = Column(
        String(20), nullable=False, default=CaseType.FUNCTIONAL,
        comment="用例类型: functional/error/boundary"
    )
    precondition = Column(Text, nullable=True, comment="前置条件")
    steps = Column(Text, nullable=True, comment="测试步骤(JSON Array)")
    expected = Column(Text, nullable=True, comment="预期结果")
    priority = Column(
        String(10), nullable=False, default=CasePriority.MEDIUM,
        comment="优先级: high/medium/low"
    )
    tags = Column(String(500), nullable=True, comment="标签(JSON Array)")
    # ===== 草稿/发布状态 =====
    case_status = Column(
        String(20), nullable=False, default="draft",
        comment="用例状态: draft/review/published/archived"
    )
    source_type = Column(
        String(20), nullable=False, default="ai",
        comment="来源: ai/manual/swagger/import"
    )
    test_type = Column(
        String(20), nullable=False, default="API",
        comment="测试类型: API/UI/WEB/ANDROID"
    )
    api_case_id = Column(
        Integer, nullable=True, index=True,
        comment="同步到api_case后的ID（映射关系）"
    )
    version = Column(Integer, nullable=False, default=1, comment="版本号")
    is_deleted = Column(Boolean, nullable=False, default=False, comment="是否删除")

    # ===== 兼容方法：转换为统一 TestAsset =====
    def to_test_asset(self) -> dict:
        """
        转换为 TestAsset 字典（用于迁移/兼容）

        禁止直接执行 CaseContent，必须转为 TestAsset 后执行。
        """
        import json

        # 解析 steps
        steps = []
        if self.steps:
            try:
                raw_steps = json.loads(self.steps) if isinstance(self.steps, str) else self.steps
                if isinstance(raw_steps, list):
                    for s in raw_steps:
                        if isinstance(s, dict):
                            steps.append({
                                "action": s.get("action", s.get("step", "")),
                                "url": s.get("url", ""),
                                "method": s.get("method", "POST"),
                                "headers": s.get("headers", {}),
                                "body": s.get("body", {}),
                            })
                        elif isinstance(s, str):
                            steps.append({"action": s, "url": "", "method": "POST", "headers": {}, "body": {}})
            except (json.JSONDecodeError, TypeError):
                if self.steps:
                    steps.append({"action": str(self.steps)[:200], "url": "", "method": "POST", "headers": {}, "body": {}})

        # 解析 preconditions
        preconditions = []
        if self.precondition:
            preconditions = [self.precondition] if isinstance(self.precondition, str) else self.precondition

        # 构建 content_json
        content = {
            "preconditions": preconditions,
            "steps": steps,
            "assertions": [],  # CaseContent 没有 assertions，迁移时补空
            "expected_result": self.expected or "",
            "env": "test",
            "variables": {},
        }

        # 解析 tags
        tags_str = ""
        if self.tags:
            try:
                tag_list = json.loads(self.tags) if isinstance(self.tags, str) else self.tags
                if isinstance(tag_list, list):
                    tags_str = ",".join(str(t) for t in tag_list)
            except (json.JSONDecodeError, TypeError):
                tags_str = str(self.tags)

        # 映射 test_type → asset_type
        type_map = {"API": "api", "UI": "web", "WEB": "web", "ANDROID": "android"}
        asset_type = type_map.get(self.test_type, "api")

        # 映射 source_type
        source_map = {"ai": "ai", "manual": "manual", "swagger": "swagger", "import": "import"}
        source_type = source_map.get(self.source_type, "manual")

        return {
            "title": self.title,
            "asset_type": asset_type,
            "source_type": source_type,
            "status": "draft",
            "content_json": json.dumps(content, ensure_ascii=False),
            "priority": self.priority or "P1",
            "tags": tags_str,
            "version": self.version or 1,
            "user_id": self.user_id,
            "created_by": self.user_id,
            "legacy_case_content_id": self.id,
        }
