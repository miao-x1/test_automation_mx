"""项目理解索引与 Project Memory — 绑定 User → Workspace(Organization) → Project。"""
from sqlalchemy import Column, String, Text, Integer, Index

from app.db.types import MEDIUMTEXT
from app.models.base import OwnedModel


class ProjectSource(OwnedModel):
    """导入的代码项目（GitHub / 本地快照）。"""
    __tablename__ = "project_source"

    organization_id = Column(Integer, nullable=False, index=True, comment="所属团队")
    project_id = Column(Integer, nullable=False, index=True, comment="所属项目")
    source_type = Column(String(20), nullable=False, default="github")
    repo_url = Column(String(512), nullable=True)
    repo_owner = Column(String(128), nullable=True)
    repo_name = Column(String(200), nullable=True)
    default_branch = Column(String(100), nullable=True)
    local_path = Column(String(512), nullable=True)
    status = Column(String(20), nullable=False, default="ready")
    file_count = Column(Integer, default=0)
    symbol_count = Column(Integer, default=0)
    overview_json = Column(MEDIUMTEXT, nullable=True)


class ProjectCodeIndex(OwnedModel):
    """文件 / 模块 / 函数 / 组件 / API 的可追溯索引。"""
    __tablename__ = "project_code_index"
    __table_args__ = (
        Index("idx_code_index_scope", "user_id", "project_id", "kind"),
        Index("idx_code_index_path", "project_id", "path"),
    )

    organization_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    kind = Column(String(20), nullable=False, comment="file/module/function/class/component/api")
    name = Column(String(255), nullable=False)
    path = Column(String(512), nullable=False)
    language = Column(String(20), nullable=True)
    module = Column(String(255), nullable=True)
    line_start = Column(Integer, nullable=True)
    line_end = Column(Integer, nullable=True)
    signature = Column(String(512), nullable=True)
    snippet = Column(Text, nullable=True)
    extra_json = Column(Text, nullable=True)


class ProjectMemoryItem(OwnedModel):
    """项目级记忆，不是 Chat History。跨三个工作区共享。"""
    __tablename__ = "project_memory_item"
    __table_args__ = (
        Index("idx_memory_scope", "user_id", "organization_id", "project_id", "kind"),
    )

    organization_id = Column(Integer, nullable=False, index=True)
    project_id = Column(Integer, nullable=False, index=True)
    kind = Column(
        String(32),
        nullable=False,
        comment="understanding/structure/question/confirmed/focus/conclusion/test_design/test_execution/message",
    )
    title = Column(String(255), nullable=False)
    content = Column(MEDIUMTEXT, nullable=True)
    workspace = Column(String(20), nullable=True, comment="understand/design/execute")
    role = Column(String(20), nullable=True, comment="user/assistant，仅 message")
    extra_json = Column(Text, nullable=True)
    test_task_id = Column(Integer, nullable=True, index=True, comment="可选：绑定专业测试任务")
