"""
RequirementCenter 数据模型

第二阶段新增表：
- RequirementSession: 需求分析会话
- RequirementFile: 上传文件
- RequirementContext: 附加上下文
- RequirementAnalysis: Agent分析结果
- RequirementReview: AI评审结果
- RequirementSummary: 最终需求摘要
- RequirementQuestion: 补充问题
"""
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, Float,
    DateTime, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship

from app.models.base import BaseModel, OwnedModel


class RequirementSession(OwnedModel):
    """
    需求分析会话。

    每次用户点击"开始AI分析"创建一个Session，
    贯穿整个需求理解流程。
    """
    __tablename__ = "requirement_session"

    # ---- 基础信息 ----
    title = Column(String(200), nullable=False, default="未命名需求", comment="会话标题")
    status = Column(String(20), nullable=False, default="created", index=True, comment="状态: created/analyzing/reviewing/finalized/failed")

    # ---- 输入来源 ----
    input_text = Column(Text, comment="自然语言需求文本（Markdown）")
    input_urls = Column(Text, comment="URL列表(JSON数组)")
    additional_context = Column(Text, comment="附加上下文(JSON): 系统名称/业务背景/测试范围/账号密码/注意事项/特殊要求")

    # ---- 关联 ----
    task_id = Column(Integer, ForeignKey("task.id", ondelete="SET NULL"), nullable=True, index=True, comment="最终生成的Task ID")
    requirement_task_id = Column(Integer, ForeignKey("requirement_task.id", ondelete="SET NULL"), nullable=True, comment="关联旧版RequirementTask")

    # ---- 流程状态 ----
    current_step = Column(String(50), default="upload", comment="当前步骤: upload/analyzing/reviewing/finalized")
    steps_json = Column(Text, comment="步骤执行记录(JSON数组)")

    # ---- 最终输出 ----
    final_requirement = Column(Text, comment="最终确认的需求文本")
    finalized = Column(Boolean, default=False, comment="是否已完成确认")

    # ---- 软删除 ----
    is_deleted = Column(Boolean, default=False, index=True)

    # ---- 关系 ----
    files = relationship("RequirementFile", back_populates="session", cascade="all, delete-orphan")
    analyses = relationship("RequirementAnalysis", back_populates="session", cascade="all, delete-orphan")
    reviews = relationship("RequirementReview", back_populates="session", cascade="all, delete-orphan")
    questions = relationship("RequirementQuestion", back_populates="session", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_req_session_user_status", "user_id", "status"),
        Index("idx_req_session_created", "created_at"),
    )


class RequirementFile(BaseModel):
    """
    需求分析上传文件。

    每个文件属于一个RequirementSession，
    记录文件类型、路径、解析状态等。
    """
    __tablename__ = "requirement_file"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)
    session = relationship("RequirementSession", back_populates="files")

    # ---- 文件信息 ----
    file_name = Column(String(500), nullable=False, comment="原始文件名")
    file_path = Column(String(1024), nullable=False, comment="存储路径（相对UPLOAD_DIR）")
    file_type = Column(String(50), nullable=False, comment="文件类型: image/document/video/schema")
    file_ext = Column(String(20), comment="文件扩展名: png/pdf/mp4/sql...")
    file_size = Column(Integer, comment="文件大小(字节)")
    mime_type = Column(String(100), comment="MIME类型")

    # ---- 文件分类 ----
    category = Column(String(20), nullable=False, default="image", comment="文件分类: image/document/video/schema")
    sort_order = Column(Integer, default=0, comment="排序序号")

    # ---- 解析状态 ----
    parse_status = Column(String(20), default="pending", comment="解析状态: pending/parsing/parsed/failed")
    parse_error = Column(Text, comment="解析错误信息")
    parse_result = Column(Text, comment="解析结果(JSON)")

    __table_args__ = (
        Index("idx_req_file_session", "session_id"),
        Index("idx_req_file_category", "category"),
    )


class RequirementContext(BaseModel):
    """
    需求附加上下文。

    用户填写的系统名称、业务背景、测试范围、
    账号密码、注意事项、特殊要求等。
    """
    __tablename__ = "requirement_context"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)

    # ---- 上下文字段 ----
    system_name = Column(String(200), comment="系统名称")
    business_background = Column(Text, comment="业务背景")
    test_scope = Column(Text, comment="测试范围")
    credentials = Column(Text, comment="账号密码(JSON): {username, password, ...}")
    notes = Column(Text, comment="注意事项")
    special_requirements = Column(Text, comment="特殊要求")

    # ---- 扩展字段 ----
    extra_json = Column(Text, comment="扩展字段(JSON)")

    __table_args__ = (
        Index("idx_req_context_session", "session_id"),
    )


class RequirementAnalysis(BaseModel):
    """
    Agent分析结果。

    每个Agent（ImageAgent/DocumentAgent/VideoAgent/ApiAgent/SchemaAgent/RequirementAgent）
    的分析结果单独存储一条记录。
    """
    __tablename__ = "requirement_analysis"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)
    session = relationship("RequirementSession", back_populates="analyses")
    file_id = Column(Integer, ForeignKey("requirement_file.id", ondelete="SET NULL"), nullable=True, comment="关联文件ID（如适用）")

    # ---- Agent信息 ----
    agent_name = Column(String(50), nullable=False, comment="Agent名称: image_agent/document_agent/video_agent/api_agent/schema_agent/requirement_agent/merge_agent")
    agent_display_name = Column(String(100), comment="Agent显示名称")
    intent_type = Column(String(30), comment="意图类型: image/document/video/swagger/schema/text/url")

    # ---- 执行信息 ----
    status = Column(String(20), nullable=False, default="pending", comment="执行状态: pending/running/completed/failed")
    duration = Column(Float, default=0.0, comment="执行耗时(秒)")

    # ---- 输入输出 ----
    input_summary = Column(Text, comment="输入摘要")
    output_json = Column(Text, comment="分析输出(JSON)")
    error_message = Column(Text, comment="错误信息")

    # ---- 合并结果 ----
    is_merged = Column(Boolean, default=False, comment="是否已合并到Summary")
    merge_contribution = Column(Float, default=0.0, comment="对最终结果的贡献度(0-1)")

    __table_args__ = (
        Index("idx_req_analysis_session", "session_id"),
        Index("idx_req_analysis_agent", "agent_name"),
        Index("idx_req_analysis_status", "status"),
    )


class RequirementReview(BaseModel):
    """
    AI评审结果。

    RequirementReviewAgent 对整合后的需求进行评审，
    检查完整性、冲突、缺失项，生成补充问题。
    """
    __tablename__ = "requirement_review"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)
    session = relationship("RequirementSession", back_populates="reviews")

    # ---- 评审信息 ----
    review_round = Column(Integer, default=1, comment="评审轮次（第1轮/第2轮...）")
    status = Column(String(20), default="pending", comment="评审状态: pending/completed/needs_input/user_answered")

    # ---- 评审结果 ----
    completeness_score = Column(Float, default=0.0, comment="完整性评分(0-1)")
    conflict_score = Column(Float, default=0.0, comment="冲突评分(0-1, 越低越好)")
    missing_items = Column(Text, comment="缺失项列表(JSON数组)")
    conflicts = Column(Text, comment="冲突项列表(JSON数组)")
    suggestions = Column(Text, comment="改进建议(JSON数组)")

    # ---- 总结 ----
    review_summary = Column(Text, comment="评审总结")
    needs_user_input = Column(Boolean, default=False, comment="是否需要用户补充")

    # ---- 用户回答 ----
    user_answers = Column(Text, comment="用户回答(JSON数组)")

    __table_args__ = (
        Index("idx_req_review_session", "session_id"),
        Index("idx_req_review_status", "status"),
    )


class RequirementSummary(BaseModel):
    """
    需求最终摘要。

    RequirementMergeAgent 整合所有Agent结果后的输出。
    """
    __tablename__ = "requirement_summary"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)

    # ---- 摘要内容 ----
    requirement_text = Column(Text, comment="需求摘要文本")
    page_description = Column(Text, comment="页面说明(JSON)")
    page_elements = Column(Text, comment="页面元素(JSON数组)")
    business_flows = Column(Text, comment="业务流程(JSON数组)")
    test_goals = Column(Text, comment="测试目标(JSON数组)")
    risk_points = Column(Text, comment="风险点(JSON数组)")
    recommended_test_types = Column(Text, comment="建议测试类型(JSON数组)")
    related_pages = Column(Text, comment="关联页面(JSON数组)")
    recommended_strategy = Column(Text, comment="推荐测试策略(JSON)")

    # ---- 元信息 ----
    confidence = Column(Float, default=0.0, comment="置信度(0-1)")
    source_agents = Column(Text, comment="来源Agent列表(JSON数组)")
    analysis_count = Column(Integer, default=0, comment="合并的分析数量")

    __table_args__ = (
        Index("idx_req_summary_session", "session_id"),
    )


class RequirementQuestion(BaseModel):
    """
    AI补充问题。

    RequirementReviewAgent 发现需要用户补充的信息时，
    生成问题列表，前端弹出等待用户回答。
    """
    __tablename__ = "requirement_question"

    # ---- 关联 ----
    session_id = Column(Integer, ForeignKey("requirement_session.id", ondelete="CASCADE"), nullable=False, index=True)
    session = relationship("RequirementSession", back_populates="questions")
    review_id = Column(Integer, ForeignKey("requirement_review.id", ondelete="SET NULL"), nullable=True, comment="关联评审记录")

    # ---- 问题信息 ----
    question_text = Column(Text, nullable=False, comment="问题内容")
    question_type = Column(String(30), default="text", comment="问题类型: text/choice/boolean")
    category = Column(String(30), comment="问题分类: login/permission/sms/captcha/environment/data/other")
    options = Column(Text, comment="选项(JSON数组，choice类型用)")
    default_answer = Column(Text, comment="默认答案")
    required = Column(Boolean, default=False, comment="是否必答")

    # ---- 回答信息 ----
    answer = Column(Text, comment="用户回答")
    answered = Column(Boolean, default=False, comment="是否已回答")
    answered_at = Column(DateTime, comment="回答时间")

    __table_args__ = (
        Index("idx_req_question_session", "session_id"),
        Index("idx_req_question_answered", "answered"),
    )
