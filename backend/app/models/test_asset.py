"""
统一测试资产模型（TestAsset）

收敛三套资产体系：
  - CaseContent（AI草稿层）→ TestAsset(status=draft)
  - ApiCase（发布层）       → TestAsset(status=published)
  - 旧 TestAsset（Web脚本） → TestAsset(asset_type=web)
  - TestAssetV2             → 已合并（draft_content/published_content 字段保留）

核心原则：
  - 一个 TestAsset = 一条测试用例，从创建到执行全生命周期
  - 状态机：created → analyzed → generated → reviewed → published → executed / failed / archived
  - content_json 统一存储内容；draft_content/published_content 分离草稿和发布内容（V2兼容）
  - 禁止 CaseContent → ApiCase 同步，统一 TestAsset

Case First 原则：
  - 用例本身必须完整可执行（标题+前置条件+步骤+断言+预期结果）
  - 套件只是组合能力，禁止强制生成套件
  - executable 标记用例是否可执行（至少1步+至少1断言）

资产类型（asset_type）：
  API / WEB / ANDROID / MANUAL / CASE / PERFORMANCE

状态（status）：
  created   - 刚创建（从需求生成）
  analyzed  - 需求分析完成（L1）
  generated - 用例生成完成（L2草稿）
  draft     - 草稿（AI生成/手动创建）
  reviewed  - 审核通过
  published - 已发布（可执行）
  executed  - 已执行
  failed    - 失败
  ready     - 就绪（旧版兼容）
  running   - 执行中（旧版兼容）
  completed - 已完成（旧版兼容）
  archived  - 归档
"""
import enum
import json
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class AssetType(str, enum.Enum):
    """资产类型"""
    API = "api"           # API接口测试
    WEB = "web"           # Web UI测试
    ANDROID = "android"   # Android测试
    MANUAL = "manual"     # 手动/通用测试用例
    CASE = "case"         # 通用测试用例（V2兼容）
    PERFORMANCE = "performance"  # 性能测试（旧版兼容）


class AssetStatus(str, enum.Enum):
    """资产状态（全生命周期）"""
    CREATED = "created"         # 刚创建
    ANALYZED = "analyzed"       # 需求分析完成(L1)
    GENERATED = "generated"     # 用例生成完成(L2草稿)
    DRAFT = "draft"             # 草稿
    REVIEWED = "reviewed"       # 审核通过
    PUBLISHED = "published"     # 已发布（可执行）
    EXECUTED = "executed"       # 已执行
    FAILED = "failed"           # 失败
    READY = "ready"             # 就绪（旧版兼容）
    RUNNING = "running"         # 执行中（旧版兼容）
    COMPLETED = "completed"     # 已完成（旧版兼容）
    ARCHIVED = "archived"       # 归档


class SourceType(str, enum.Enum):
    """来源类型"""
    AI = "ai"               # AI生成
    MANUAL = "manual"       # 手动创建
    SWAGGER = "swagger"     # Swagger导入
    IMPORT = "import"       # 文件导入
    REUSED = "reused"       # 复用


# V2兼容别名
AssetSource = SourceType


class TestAsset(OwnedModel):
    """
    统一测试资产表（Case First）

    替代：CaseContent + ApiCase + 旧TestAsset

    content_json 结构规范（完整可执行用例）：
    {
        "title": "用例标题",
        "preconditions": ["前置条件1"],
        "steps": [
            {"action": "请求/操作", "url": "", "method": "POST", "headers": {}, "body": {}}
        ],
        "assertions": [
            {"path": "$.status", "operator": "eq", "expected": 200}
        ],
        "expected_result": "预期结果描述",
        "env": "test",
        "variables": {},
        "tags": []
    }
    """
    __tablename__ = "test_asset"

    # ===== 基础信息 =====
    title = Column(String(500), nullable=False, comment="用例标题")
    description = Column(Text, nullable=True, comment="描述")

    # ===== 分类 =====
    asset_type = Column(
        String(20), nullable=False, default=AssetType.API,
        index=True, comment="资产类型: api/web/android/manual/case/performance"
    )
    source_type = Column(
        String(20), nullable=False, default=SourceType.AI,
        comment="来源: ai/manual/swagger/import/reused"
    )

    # ===== 状态 =====
    status = Column(
        String(20), nullable=False, default=AssetStatus.DRAFT,
        index=True, comment="状态: created/analyzed/generated/draft/reviewed/published/executed/failed/archived"
    )

    # ===== 可执行标记（Case First 核心） =====
    executable = Column(
        Boolean, default=False, nullable=False, index=True,
        comment="是否可执行：至少1步+至少1断言"
    )

    # ===== 关联 =====
    session_id = Column(Integer, ForeignKey("session.id", ondelete="SET NULL"),
                        nullable=True, index=True, comment="关联会话ID")
    requirement_id = Column(Integer, ForeignKey("requirement_task.id", ondelete="SET NULL"),
                            nullable=True, index=True, comment="关联需求ID")
    project_id = Column(Integer, nullable=True, index=True, comment="项目ID")
    task_id = Column(Integer, ForeignKey("task.id", ondelete="CASCADE"), nullable=True, index=True, comment="关联任务ID（旧版兼容）")
    folder_id = Column(Integer, nullable=True, index=True, comment="所属目录ID（V2兼容）")
    test_point_id = Column(Integer, ForeignKey("test_point.id", ondelete="SET NULL"),
                           nullable=True, comment="关联测试点ID（V2兼容）")

    # ===== 内容（统一JSON，完整可执行用例） =====
    content_json = Column(Text, nullable=True, comment="用例内容(JSON): {preconditions,steps,assertions,expected_result,env,variables}")
    # V2兼容：草稿内容与发布内容分离
    draft_content = Column(Text, nullable=True, comment="草稿内容(JSON)（V2兼容）")
    published_content = Column(Text, nullable=True, comment="发布内容(JSON)（V2兼容）")

    # ===== 旧版兼容字段（LegacyWebAsset） =====
    input_config = Column(Text, nullable=True, comment="输入配置(JSON)（旧版兼容）")
    exec_config = Column(Text, nullable=True, comment="执行配置(JSON)（旧版兼容）")
    script_content = Column(Text, nullable=True, comment="测试脚本内容（旧版兼容）")
    script_language = Column(String(20), default="python", comment="脚本语言: python/javascript（旧版兼容）")
    script_path = Column(String(512), nullable=True, comment="脚本文件路径（旧版兼容）")
    kb_status = Column(String(20), default="approved", nullable=False, index=True, comment="知识库审核状态（旧版兼容）")
    reuse_count = Column(Integer, default=0, nullable=False, comment="被复用次数（旧版兼容）")

    # ===== 发布标记 =====
    published = Column(Boolean, default=False, nullable=False, index=True, comment="是否已发布")

    # ===== 版本 =====
    version = Column(Integer, default=1, nullable=False, comment="版本号")

    # ===== 执行状态 =====
    execution_state = Column(Text, nullable=True, comment="执行状态(JSON): {last_run_id,last_status,last_run_at,duration_ms}")

    # ===== 优先级与标签 =====
    priority = Column(String(5), default="P1", comment="优先级: P0/P1/P2/P3")
    tags = Column(String(500), nullable=True, comment="标签(逗号分隔)")

    # ===== 兼容旧系统 =====
    legacy_case_content_id = Column(Integer, nullable=True, comment="旧CaseContent ID（迁移用）")
    legacy_api_case_id = Column(Integer, nullable=True, comment="旧ApiCase ID（迁移用）")
    legacy_test_asset_id = Column(Integer, nullable=True, comment="旧TestAsset ID（迁移用）")

    # ===== 软删除 =====
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除")

    # ===== 关联关系（旧版兼容） =====
    task = relationship("Task", back_populates="test_assets")

    # ===== 兼容属性 =====
    @property
    def name(self):
        """旧版兼容：name 属性别名"""
        return self.title

    @name.setter
    def name(self, value):
        self.title = value

    @property
    def source(self):
        """旧版兼容：source 属性别名"""
        return self.source_type

    @source.setter
    def source(self, value):
        self.source_type = value

    # ===== 方法 =====
    def validate_executable(self) -> bool:
        """校验用例是否可执行：至少1步+至少1断言"""
        content = self.get_content()
        if not content:
            return False
        steps = content.get("steps", [])
        assertions = content.get("assertions", [])
        has_steps = isinstance(steps, list) and len(steps) > 0
        has_assertions = isinstance(assertions, list) and len(assertions) > 0
        self.executable = has_steps and has_assertions
        return self.executable

    def to_execution_json(self) -> dict:
        """生成Execution Ready格式（从content_json，V2兼容fallback）"""
        content = self.content_json
        if not content:
            # V2兼容：fallback到 published_content 或 draft_content
            content = self.published_content or self.draft_content
        if not content:
            return {}
        try:
            data = json.loads(content)
            # 如果content_json已经是执行格式（有request字段），直接返回
            if "request" in data:
                return {
                    "execution_case_id": f"EX_{self.id}",
                    "title": self.title,
                    "asset_id": self.id,
                    **data,
                }
            # Case First 格式：从 steps/assertions 构建
            steps = data.get("steps", [])
            assertions = data.get("assertions", [])

            # API 类型：从第一个 step 构建 request
            if self.asset_type == AssetType.API and steps:
                first_step = steps[0] if isinstance(steps, list) else {}
                return {
                    "execution_case_id": f"EX_{self.id}",
                    "title": self.title,
                    "asset_id": self.id,
                    "request": {
                        "method": first_step.get("method", "POST"),
                        "url": first_step.get("url", ""),
                        "headers": first_step.get("headers", {}),
                        "body": first_step.get("body", {}),
                        "timeout": first_step.get("timeout", 5000),
                    },
                    "preconditions": data.get("preconditions", []),
                    "assertions": assertions,
                    "expected_result": data.get("expected_result", ""),
                    "variables": data.get("variables", {}),
                    "env": data.get("env", "test"),
                    "runtime": data.get("runtime", {"retry": 0, "env": "test"}),
                }

            # 通用格式
            return {
                "execution_case_id": f"EX_{self.id}",
                "title": self.title,
                "asset_id": self.id,
                "request": {
                    "method": data.get("method", "POST"),
                    "url": data.get("url", ""),
                    "headers": data.get("headers", {}),
                    "body": data.get("body", {}),
                    "timeout": data.get("timeout", 5000),
                },
                "pre_steps": data.get("pre_steps", []),
                "assertions": assertions,
                "variables": data.get("variables", {}),
                "runtime": data.get("runtime", {"retry": 0, "env": "test"}),
            }
        except json.JSONDecodeError:
            return {}

    def publish(self):
        """发布：标记为已发布，并将draft_content复制到published_content"""
        if self.draft_content and not self.published_content:
            self.published_content = self.draft_content
        self.published = True
        self.status = AssetStatus.PUBLISHED

    def unpublish(self):
        """取消发布：回退到草稿"""
        self.published = False
        self.status = AssetStatus.DRAFT

    def get_content(self) -> dict:
        """获取解析后的内容"""
        if not self.content_json:
            return {}
        try:
            return json.loads(self.content_json)
        except json.JSONDecodeError:
            return {}

    def set_content(self, data: dict):
        """设置内容并自动校验可执行性"""
        self.content_json = json.dumps(data, ensure_ascii=False)
        self.validate_executable()


# 复合索引
Index('idx_asset_type_status', TestAsset.asset_type, TestAsset.status)
Index('idx_asset_session_type', TestAsset.session_id, TestAsset.asset_type)
Index('idx_asset_project_type', TestAsset.project_id, TestAsset.asset_type)
Index('idx_asset_published', TestAsset.published, TestAsset.asset_type)
Index('idx_asset_executable', TestAsset.executable, TestAsset.status)
