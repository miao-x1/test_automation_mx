"""
需求任务模型

存储用户自然语言需求驱动的测试任务
"""
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.db.types import MEDIUMTEXT
from app.models.base import OwnedModel


class RequirementStatus(str, enum.Enum):
    """需求任务状态"""
    PENDING = "pending"             # 待处理
    ANALYZING = "analyzing"         # 需求解析中
    GENERATING_CASE = "generating_case"   # 生成用例中
    RETRIEVING = "retrieving"       # RAG检索中
    GENERATING_SCRIPT = "generating_script"  # 生成脚本中
    EXECUTING = "executing"         # 执行中
    COMPLETED = "completed"         # 已完成
    FAILED = "failed"               # 失败


class RequirementTask(OwnedModel):
    """
    需求任务表

    存储用户输入的自然语言需求，以及AI自动生成的测试用例、脚本和执行结果
    """
    __tablename__ = "requirement_task"

    requirement = Column(
        Text,
        nullable=False,
        comment="用户输入的自然语言需求"
    )

    status = Column(
        String(30),
        default=RequirementStatus.PENDING,
        nullable=False,
        index=True,
        comment="任务状态"
    )

    intent = Column(
        String(100),
        nullable=True,
        comment="AI解析的意图标识，如 login_test"
    )

    generated_case = Column(
        Text,
        nullable=True,
        comment="AI生成的测试用例(JSON)"
    )

    generated_script = Column(
        Text,
        nullable=True,
        comment="AI生成的Playwright脚本"
    )

    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属项目",
    )

    task_id = Column(
        Integer,
        nullable=True,
        comment="关联的任务ID（自动创建）"
    )

    execution_id = Column(
        Integer,
        nullable=True,
        comment="关联的执行记录ID"
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="错误信息"
    )

    # 知识库审核状态（用于用例审核）
    kb_status = Column(
        String(20),
        default="approved",
        nullable=False,
        index=True,
        comment="知识库审核状态: draft/approved/rejected"
    )

    # RAG召回结果（JSON）
    rag_result = Column(
        Text,
        nullable=True,
        comment="RAG召回结果(JSON): 元素、用例、脚本及相似度"
    )

    # 脚本来源
    script_source = Column(
        String(20),
        default="generated",
        nullable=True,
        comment="脚本来源: generated(新生成)/reused(复用历史)"
    )

    # 复用相似度
    reuse_similarity = Column(
        String(20),
        nullable=True,
        comment="复用时的相似度分数"
    )

    # Graph推理结果（JSON）
    graph_result = Column(
        MEDIUMTEXT,
        nullable=True,
        comment="Graph推理结果(JSON): 页面路径、元素、业务流"
    )

    # 附加信息
    additional_info = Column(
        Text,
        nullable=True,
        comment="用户附加信息（URL、备注等）"
    )

    # 上传图片路径（JSON数组）
    image_paths = Column(
        MEDIUMTEXT,
        nullable=True,
        comment="上传的图片路径列表(JSON数组)"
    )

    # 脚本格式
    script_format = Column(
        String(20),
        default="playwright",
        nullable=True,
        comment="脚本格式: playwright/yaml"
    )

    # AI推断的测试类型
    task_type = Column(
        String(20),
        default="web",
        nullable=False,
        index=True,
        comment="AI推断的测试类型: web/api/performance/android/hybrid"
    )

    # 测试类型范围（JSON）
    type_config = Column(
        Text,
        nullable=True,
        comment="AI推断的测试范围(JSON): {web:true, api:false, performance:false, android:false}"
    )

    # YAML格式脚本
    generated_yaml = Column(
        Text,
        nullable=True,
        comment="AI生成的YAML格式脚本"
    )

    # 页面概述（流式填充）
    page_overview = Column(
        Text,
        nullable=True,
        comment="AI生成的页面概述"
    )

    # 页面元素（流式填充）
    page_elements = Column(
        Text,
        nullable=True,
        comment="AI识别的页面元素(JSON)"
    )

    # 测试场景（流式填充）
    test_scenarios = Column(
        Text,
        nullable=True,
        comment="AI生成的测试场景(JSON)"
    )

    # 预期结果（流式填充）
    expected_results = Column(
        Text,
        nullable=True,
        comment="AI生成的预期结果(JSON)"
    )

    def __repr__(self):
        return f"<RequirementTask(id={self.id}, requirement='{self.requirement[:20]}...', status={self.status})>"


Index('idx_requirement_status', RequirementTask.status)
