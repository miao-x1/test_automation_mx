"""
任务模型
"""
import enum
from sqlalchemy import Column, String, Float, Integer, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class TaskStatus(str, enum.Enum):
    """任务状态枚举"""
    PENDING = "pending"         # 待处理
    PROCESSING = "processing"   # 处理中
    SUCCESS = "success"         # 成功
    FAILED = "failed"           # 失败


class InputMode(str, enum.Enum):
    """输入模式枚举"""
    IMAGE = "image"             # 上传截图
    URL = "url"                 # 输入URL
    REQUIREMENT = "requirement" # 需求驱动


class TaskType(str, enum.Enum):
    """测试类型枚举（统一测试类型）"""
    WEB = "web"                 # Web UI 测试
    API = "api"                 # API 接口测试
    PERFORMANCE = "performance" # 性能测试
    ANDROID = "android"         # Android 测试


class Task(OwnedModel):
    """
    任务表

    核心业务表，记录每个UI自动化测试任务
    """
    __tablename__ = "task"

    project_id = Column(
        Integer,
        ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="所属项目",
    )

    task_name = Column(
        String(255),
        nullable=False,
        index=True,
        comment="任务名称"
    )

    status = Column(
        SQLEnum(TaskStatus, values_callable=lambda x: [e.value for e in x]),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
        comment="任务状态"
    )

    input_mode = Column(
        SQLEnum(InputMode, values_callable=lambda x: [e.value for e in x]),
        default=InputMode.IMAGE,
        nullable=False,
        index=True,
        comment="输入模式: image/url"
    )

    page_url = Column(
        String(1024),
        nullable=True,
        comment="页面URL（URL模式时填写）"
    )

    task_type = Column(
        SQLEnum(TaskType, values_callable=lambda x: [e.value for e in x]),
        default=TaskType.WEB,
        nullable=False,
        index=True,
        comment="测试类型: web/api/performance/android"
    )

    # 测试类型配置（JSON格式，按类型动态渲染）
    type_config = Column(
        String(4096),
        nullable=True,
        comment="测试类型配置(JSON): Web→{url,browser}, API→{endpoint,headers}, Performance→{concurrency,tps}, Android→{device,app}"
    )

    # AI智能识别结果字段
    framework = Column(
        String(64),
        nullable=True,
        index=True,
        comment="测试框架: playwright/appium/pytest/jmeter"
    )

    platform = Column(
        String(64),
        nullable=True,
        index=True,
        comment="测试平台: browser/mobile/server"
    )

    confidence = Column(
        Float,
        nullable=True,
        comment="AI识别置信度(0-1)"
    )

    error_message = Column(
        String(1024),
        nullable=True,
        comment="错误信息"
    )

    # 关联关系
    images = relationship(
        "ImageFile",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    analysis_result = relationship(
        "AnalysisResult",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    script = relationship(
        "Script",
        back_populates="task",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    ui_elements = relationship(
        "UIElement",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # 保留page_elements关系以兼容旧数据
    page_elements = relationship(
        "PageElement",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # 执行记录
    execution_records = relationship(
        "ExecutionRecord",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    # 旧版Web脚本资产（已统一到TestAsset）
    test_assets = relationship(
        "TestAsset",
        back_populates="task",
        cascade="all, delete-orphan",
        lazy="selectin"
    )

    def __repr__(self):
        return f"<Task(id={self.id}, name={self.task_name}, status={self.status.value})>"


# 复合索引
Index('idx_task_status_created', Task.status, Task.created_at)
Index('idx_task_input_mode', Task.input_mode)
