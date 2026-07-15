"""
Session模型 - 会话管理体系

一次测试分析过程形成完整会话，支持恢复、回看、继续生成、历史记录
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Float
from app.models.base import OwnedModel


class SessionStatus(str, enum.Enum):
    """会话状态"""
    ACTIVE = "active"         # 活跃中
    PAUSED = "paused"         # 已暂停
    COMPLETED = "completed"   # 已完成
    ARCHIVED = "archived"     # 已归档


class Session(OwnedModel):
    """测试分析会话"""
    session_name = Column(String(200), nullable=False, comment="会话名称")
    project_id = Column(String(100), nullable=True, comment="项目ID")
    status = Column(
        String(20), nullable=False, default=SessionStatus.ACTIVE,
        index=True, comment="会话状态"
    )
    # 当前步骤追踪
    current_step = Column(String(50), nullable=True, comment="当前步骤: upload/parse/chunk/testpoint/case/review/mindmap")
    # 关联的CaseTask
    case_task_id = Column(Integer, ForeignKey("case_task.id"), nullable=True, comment="关联的任务ID")
    task_id = Column(Integer, ForeignKey("task.id"), nullable=True, index=True, comment="关联的Task ID（企业级任务追踪）")
    # 需求摘要
    requirement_summary = Column(Text, nullable=True, comment="需求摘要")
    # 会话配置
    config_json = Column(Text, nullable=True, comment="会话配置(JSON)")
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除")

    # ===== GraphFlow 集成 =====
    session_key = Column(
        String(128), nullable=True, index=True,
        comment="RuntimeManager 会话标识 (user_{uid}_session_{sid})"
    )
    graphflow_task_id = Column(
        String(64), nullable=True, index=True,
        comment="GraphFlow 任务ID"
    )
    requirement_text = Column(
        Text, nullable=True,
        comment="原始需求文本"
    )
    input_mode = Column(
        String(20), nullable=True, default="text",
        comment="输入模式: text/image/file/url"
    )
    total_tokens = Column(
        Integer, nullable=True, default=0,
        comment="总 Token 消耗"
    )
    total_duration = Column(
        Float, nullable=True, default=0.0,
        comment="总耗时(秒)"
    )
    artifact_count = Column(
        Integer, nullable=False, default=0,
        comment="制品数量"
    )
    error_count = Column(
        Integer, nullable=False, default=0,
        comment="错误数量"
    )


class SessionContentType(str, enum.Enum):
    """会话内容类型"""
    REQUIREMENT = "requirement"   # 需求
    CASE = "case"                 # 用例
    MINDMAP = "mindmap"           # 思维导图
    LOGS = "logs"                 # 日志
    RAG = "rag"                   # RAG上下文
    TESTPOINT = "testpoint"       # 测试点
    CHUNK = "chunk"               # 分块进度


class SessionContent(OwnedModel):
    """会话步骤内容（每步产出都记录）"""
    session_id = Column(Integer, ForeignKey("session.id", ondelete="CASCADE"), nullable=False, index=True, comment="会话ID")
    step = Column(String(50), nullable=False, comment="步骤: upload/parse/chunk/testpoint/case/review/mindmap")
    content_type = Column(String(30), nullable=False, default=SessionContentType.LOGS, comment="内容类型")
    content = Column(Text, nullable=True, comment="内容(JSON)")
    step_index = Column(Integer, default=0, comment="步骤序号")
    is_deleted = Column(Boolean, default=False, nullable=False, index=True, comment="软删除")
