"""
SessionArtifact - 会话制品统一存储模型

一个 Session 包含的所有制品：
  - 需求 (requirement)
  - 上传文件 (file)
  - Agent 消息 (agent_message)
  - 测试点 (test_point)
  - 生成用例 (case)
  - 脚本 (script)
  - 日志 (log)
  - 思维导图 (mindmap)
  - 导出文件 (export)

所有制品统一存储，支持按 session_id 恢复整个 AI 执行历史。
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Boolean, ForeignKey, Index, Float
from app.models.base import OwnedModel


class ArtifactType(str, enum.Enum):
    """制品类型"""
    REQUIREMENT = "requirement"        # 需求文本
    FILE = "file"                       # 上传文件
    AGENT_MESSAGE = "agent_message"    # Agent 消息/事件
    TEST_POINT = "test_point"          # 测试点
    CASE = "case"                       # 生成用例
    SCRIPT = "script"                   # 自动化脚本
    LOG = "log"                         # 执行日志
    MINDMAP = "mindmap"                 # 思维导图
    EXPORT = "export"                   # 导出文件
    FEEDBACK = "feedback"              # 人工反馈
    REVIEW = "review"                   # 评审结果


class SessionArtifact(OwnedModel):
    """
    会话制品 - 统一存储 Session 中的所有产出

    每个制品记录：
    - 所属会话 (session_id)
    - 制品类型 (artifact_type)
    - 制品名称 (name)
    - 制品内容 (content_json) - JSON 格式
    - 文件路径 (file_path) - 如果是文件
    - 步骤 (step) - 来自哪个流程步骤
    - 来源 Agent (source_agent)
    - 排序序号 (order_index)
    """
    __tablename__ = "session_artifact"

    # ===== 会话关联 =====
    session_id = Column(
        Integer, ForeignKey("session.id", ondelete="CASCADE"),
        nullable=False, index=True,
        comment="会话ID"
    )

    # ===== 制品类型 =====
    artifact_type = Column(
        String(30), nullable=False, index=True,
        comment="制品类型: requirement/file/agent_message/test_point/case/script/log/mindmap/export/feedback/review"
    )

    # ===== 制品内容 =====
    name = Column(
        String(200), nullable=False,
        comment="制品名称"
    )
    content_json = Column(
        Text, nullable=True,
        comment="制品内容(JSON)"
    )
    file_path = Column(
        String(500), nullable=True,
        comment="文件路径（如果是文件类型）"
    )
    file_size = Column(
        Integer, nullable=True,
        comment="文件大小(字节)"
    )
    mime_type = Column(
        String(100), nullable=True,
        comment="MIME类型"
    )

    # ===== 流程信息 =====
    step = Column(
        String(50), nullable=True,
        comment="流程步骤: requirement/case/review/script/export 等"
    )
    source_agent = Column(
        String(80), nullable=True,
        comment="来源 Agent 名称"
    )
    order_index = Column(
        Integer, nullable=False, default=0,
        comment="排序序号"
    )

    # ===== 元数据 =====
    metadata_json = Column(
        Text, nullable=True,
        comment="额外元数据(JSON)"
    )
    tags = Column(
        String(200), nullable=True,
        comment="标签(逗号分隔)"
    )

    # ===== 状态 =====
    is_deleted = Column(
        Boolean, default=False, nullable=False, index=True,
        comment="软删除"
    )


# 复合索引
Index('idx_session_artifact_session_type', SessionArtifact.session_id, SessionArtifact.artifact_type)
Index('idx_session_artifact_session_step', SessionArtifact.session_id, SessionArtifact.step)
Index('idx_session_artifact_user_type', SessionArtifact.user_id, SessionArtifact.artifact_type)
