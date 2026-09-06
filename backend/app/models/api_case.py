"""
结构化接口测试用例模型

与 CaseContent（AI生成，steps为文本）不同，
ApiCase 存储结构化的接口测试用例，支持：
- 步骤（steps）为JSON数组，每个步骤包含 action/url/headers/body
- 断言（assertions）为JSON数组，支持多种断言类型
- 变量提取（extracts）为JSON数组
- 所属目录/标签分类
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Index
from app.db.types import MEDIUMTEXT
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class ApiCaseMethod(str, enum.Enum):
    """HTTP方法"""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class TestType(str, enum.Enum):
    """测试类型"""
    API = "API"
    UI = "UI"
    WEB = "WEB"
    ANDROID = "ANDROID"


class ApiCasePriority(str, enum.Enum):
    """优先级"""
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ApiCaseStatus(str, enum.Enum):
    """用例状态"""
    DRAFT = "draft"           # 草稿
    REVIEW = "review"         # 待审核
    PUBLISHED = "published"   # 已发布（可执行）
    DEPRECATED = "deprecated" # 废弃


class ApiCase(OwnedModel):
    """
    结构化接口测试用例

    符合 Execution Engine Case JSON 标准：
    {
        "case_id": "C001",
        "type": "api",
        "title": "...",
        "steps": [{"action": "POST", "url": "/api/xxx", ...}],
        "assertions": [{"type": "equals", "path": "code", "expected": 200}],
        "extracts": [{"key": "token", "path": "data.token"}]
    }
    """
    __tablename__ = "api_case"

    title = Column(
        String(200), nullable=False, comment="用例标题"
    )
    case_id = Column(
        String(50), nullable=True, index=True, comment="用例编号（如 C001）"
    )
    description = Column(
        Text, nullable=True, comment="用例描述"
    )
    folder_id = Column(
        Integer, ForeignKey("api_case_folder.id", ondelete="SET NULL"),
        nullable=True, index=True, comment="所属目录ID"
    )
    priority = Column(
        String(10), nullable=False, default=ApiCasePriority.MEDIUM,
        comment="优先级: high/medium/low"
    )
    status = Column(
        String(20), nullable=False, default=ApiCaseStatus.DRAFT,
        comment="状态: draft/ready/deprecated"
    )
    tags = Column(
        String(500), nullable=True, comment="标签（JSON数组）"
    )
    precondition = Column(
        Text, nullable=True, comment="前置条件"
    )

    # ===== 核心结构化字段 =====
    steps = Column(
        MEDIUMTEXT, nullable=False,
        comment="测试步骤（JSON数组）: [{action, url, headers, body, extract, timeout}]"
    )
    assertions = Column(
        MEDIUMTEXT, nullable=True,
        comment="断言规则（JSON数组）: [{type, path, expected}]"
    )
    extracts = Column(
        Text, nullable=True,
        comment="变量提取（JSON数组）: [{key, path}]"
    )

    # ===== 执行级字段（L3编译后填充） =====
    method = Column(
        String(10), nullable=True, comment="HTTP方法: GET/POST/PUT/DELETE/PATCH"
    )
    url = Column(
        String(500), nullable=True, comment="请求URL"
    )
    pre_steps = Column(
        Text, nullable=True, comment="前置步骤（JSON数组）: [{name, request, extract}]"
    )
    variables = Column(
        Text, nullable=True, comment="变量定义（JSON）: {token: '{{token}}'}"
    )

    # ===== 环境配置覆盖 =====
    env_override = Column(
        Text, nullable=True,
        comment="环境覆盖配置（JSON）: {base_url, headers, variables}"
    )

    # ===== 统计 =====
    version = Column(
        Integer, nullable=False, default=1, comment="版本号"
    )
    last_run_status = Column(
        String(20), nullable=True, comment="最近执行状态: PASS/FAIL/ERROR"
    )
    last_run_at = Column(
        String(30), nullable=True, comment="最近执行时间"
    )
    run_count = Column(
        Integer, nullable=False, default=0, comment="执行次数"
    )
    # ===== 测试类型 =====
    test_type = Column(
        String(20), nullable=False, default="API",
        comment="测试类型: API/UI/WEB/ANDROID"
    )
    module_name = Column(
        String(100), nullable=True,
        comment="所属模块（如：登录模块、支付模块）"
    )

    # ===== 来源追踪 =====
    source = Column(
        String(20), nullable=False, default="manual",
        comment="来源: ai/manual/swagger/import"
    )
    canonical_case_id = Column(
        String(50), nullable=True, index=True,
        comment="统一用例编号（跨系统唯一标识）"
    )
    source_content_id = Column(
        Integer, nullable=True, index=True,
        comment="来源CaseContent ID（AI生成时关联）"
    )

    is_deleted = Column(
        Boolean, nullable=False, default=False, comment="是否删除"
    )

    # 关联
    folder = relationship("ApiCaseFolder", back_populates="cases")

    def to_case_json(self) -> dict:
        """
        转换为 Execution Engine 标准的 Case JSON

        ⚠ 废弃：禁止直接执行 ApiCase，应通过 TestAsset.to_execution_json() 执行
        保留兼容：旧接口测试模块仍使用此方法
        """
        import json

        # 如果有method/url（L3编译后的格式），直接构建request
        if self.method:
            request_obj = {
                "method": self.method,
                "url": self.url or "",
                "headers": {},
                "body": {},
                "timeout": 5000,
            }
            # 从steps中提取完整请求信息
            steps = json.loads(self.steps) if self.steps else []
            if steps and isinstance(steps, list):
                first_step = steps[0] if steps else {}
                if isinstance(first_step, dict) and first_step.get("action", "").upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    request_obj = {
                        "method": first_step.get("action", self.method),
                        "url": first_step.get("url", self.url or ""),
                        "headers": first_step.get("headers", {}),
                        "body": first_step.get("body", {}),
                        "timeout": first_step.get("timeout", 5000),
                    }
                elif isinstance(first_step, dict):
                    # steps存的是headers等补充信息
                    request_obj["headers"] = first_step if isinstance(first_step, dict) and "action" not in first_step else {}

            return {
                "case_id": self.case_id or f"C{self.id}",
                "title": self.title,
                "type": "api",
                "request": request_obj,
                "pre_steps": json.loads(self.pre_steps) if self.pre_steps else [],
                "assertions": json.loads(self.assertions) if self.assertions else [],
                "extracts": json.loads(self.extracts) if self.extracts else [],
                "variables": json.loads(self.variables) if self.variables else {},
                "runtime": {"retry": 0, "env": "test"},
            }
        else:
            # 旧格式兼容：steps是标准格式数组
            return {
                "case_id": self.case_id or f"C{self.id}",
                "title": self.title,
                "type": "api",
                "precondition": self.precondition,
                "steps": json.loads(self.steps) if self.steps else [],
                "assertions": json.loads(self.assertions) if self.assertions else [],
                "extracts": json.loads(self.extracts) if self.extracts else [],
            }

    @staticmethod
    def from_test_asset(asset) -> dict:
        """
        从 TestAsset 生成 ApiCase 字典（兼容旧接口测试模块）

        禁止直接执行 ApiCase，应通过 TestAsset 执行。
        此方法仅用于旧模块需要 ApiCase 格式数据的场景。
        """
        import json as _json

        content = asset.get_content() if hasattr(asset, 'get_content') else {}
        if isinstance(asset.content_json, str):
            try:
                content = _json.loads(asset.content_json)
            except (_json.JSONDecodeError, TypeError):
                content = {}

        steps = content.get("steps", [])
        assertions = content.get("assertions", [])

        # 构建 ApiCase 格式的 steps
        api_steps = []
        for s in steps:
            if isinstance(s, dict):
                api_steps.append({
                    "action": s.get("method", s.get("action", "POST")),
                    "url": s.get("url", ""),
                    "headers": s.get("headers", {}),
                    "body": s.get("body", {}),
                    "timeout": s.get("timeout", 5000),
                })

        # 构建 ApiCase 格式的 assertions
        api_assertions = []
        for a in assertions:
            if isinstance(a, dict):
                api_assertions.append({
                    "type": a.get("operator", "equals"),
                    "path": a.get("path", ""),
                    "expected": a.get("expected", ""),
                })

        # 从第一个 step 提取 method/url（兼容旧 ApiCase 字段）
        first_step = steps[0] if steps else {}
        method = first_step.get("method", "POST") if isinstance(first_step, dict) else "POST"
        url = first_step.get("url", "") if isinstance(first_step, dict) else ""

        return {
            "title": asset.title,
            "method": method,
            "url": url,
            "steps": _json.dumps(api_steps, ensure_ascii=False),
            "assertions": _json.dumps(api_assertions, ensure_ascii=False),
            "precondition": "\n".join(content.get("preconditions", [])),
            "priority": asset.priority or "P1",
            "status": "draft",
            "tags": asset.tags,
            "test_type": getattr(asset, 'asset_type', 'api').upper(),
            "source": "ai",
            "source_content_id": getattr(asset, 'legacy_case_content_id', None),
        }


class ApiCaseFolder(OwnedModel):
    """接口用例目录（分类管理）"""
    __tablename__ = "api_case_folder"

    name = Column(
        String(100), nullable=False, comment="目录名称"
    )
    parent_id = Column(
        Integer, ForeignKey("api_case_folder.id", ondelete="CASCADE"),
        nullable=True, index=True, comment="父目录ID"
    )
    description = Column(
        Text, nullable=True, comment="目录描述"
    )
    sort_order = Column(
        Integer, nullable=False, default=0, comment="排序"
    )
    is_deleted = Column(
        Boolean, nullable=False, default=False, comment="是否删除"
    )

    # 关联
    cases = relationship("ApiCase", back_populates="folder")
    children = relationship("ApiCaseFolder", backref="parent", remote_side="ApiCaseFolder.id")


Index('idx_api_case_folder_user', ApiCaseFolder.user_id, ApiCaseFolder.is_deleted)
Index('idx_api_case_user_status', ApiCase.user_id, ApiCase.status, ApiCase.is_deleted)
