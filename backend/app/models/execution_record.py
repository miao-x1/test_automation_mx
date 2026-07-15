"""
执行记录模型（Execution First）

统一执行入口，所有执行类型共用此模型。

字段说明：
  - asset_id: 关联 TestAsset（Case First 执行入口）
  - suite_id: 关联 TestSuite（可选，套件执行）
  - session_id: 关联 Session（批量执行）
  - execution_type: 执行类型 api/web/android/suite/batch
  - status: 执行状态 waiting/running/success/failed/cancelled
  - duration: 执行耗时（秒）
  - report_path: 报告文件路径
"""
import enum
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class ExecutionStatus(str, enum.Enum):
    """执行状态枚举"""
    WAITING = "waiting"         # 等待执行（已入队）
    PENDING = "pending"         # 待执行（兼容旧数据）
    RUNNING = "running"         # 执行中
    SUCCESS = "success"         # 执行成功
    FAILED = "failed"           # 执行失败
    CANCELLED = "cancelled"     # 已取消


class ExecutionType(str, enum.Enum):
    """执行类型枚举"""
    API = "api"             # 接口测试执行
    WEB = "web"             # Web自动化执行
    ANDROID = "android"     # Android测试执行
    SUITE = "suite"         # 套件执行
    BATCH = "batch"         # 批量执行


class ExecutionRecord(OwnedModel):
    """
    执行记录表（统一）

    替代：旧 execution_record（仅 Playwright）+ api_test/execution（仅接口）
    统一入口：POST /execution/run/asset
    """
    __tablename__ = "execution_record"

    # ===== 关联 =====
    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="任务ID（兼容旧 Playwright 执行）"
    )

    asset_id = Column(
        Integer,
        ForeignKey("test_asset.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
        comment="关联 TestAsset ID（Case First 执行入口）"
    )

    suite_id = Column(
        Integer,
        nullable=True,
        index=True,
        comment="关联 TestSuite ID（套件执行）"
    )

    session_id = Column(
        Integer,
        nullable=True,
        index=True,
        comment="关联 Session ID（批量执行）"
    )

    # ===== 执行类型 =====
    execution_type = Column(
        String(20),
        default=ExecutionType.API,
        nullable=True,
        index=True,
        comment="执行类型: api/web/android/suite/batch"
    )

    # ===== 状态 =====
    status = Column(
        String(20),
        default=ExecutionStatus.WAITING,
        nullable=False,
        index=True,
        comment="执行状态: waiting/pending/running/success/failed/cancelled"
    )

    trigger_source = Column(
        String(30),
        default="manual",
        nullable=True,
        comment="触发来源: manual/schedule/script_upload/retry/api_test"
    )

    # ===== 时间 =====
    start_time = Column(
        String(30),
        nullable=True,
        comment="执行开始时间"
    )

    end_time = Column(
        String(30),
        nullable=True,
        comment="执行结束时间"
    )

    duration = Column(
        Float,
        nullable=True,
        comment="执行耗时(秒)"
    )

    # ===== 结果 =====
    success_count = Column(
        Integer,
        default=0,
        comment="通过的测试用例数"
    )

    failed_count = Column(
        Integer,
        default=0,
        comment="失败的测试用例数"
    )

    error_message = Column(
        Text,
        nullable=True,
        comment="错误信息"
    )

    log_content = Column(
        MEDIUMTEXT,
        nullable=True,
        comment="执行日志"
    )

    # ===== 报告 =====
    report_path = Column(
        String(512),
        nullable=True,
        comment="测试报告路径"
    )

    screenshot_path = Column(
        String(512),
        nullable=True,
        comment="截图保存路径"
    )

    analysis_result = Column(
        MEDIUMTEXT,
        nullable=True,
        comment="LLM失败分析结果(JSON): success, fail_step, root_cause, suggestion"
    )

    # ===== 关联关系 =====
    task = relationship("Task", back_populates="execution_records")

    def __repr__(self):
        return f"<ExecutionRecord(id={self.id}, type={self.execution_type}, status={self.status})>"


Index('idx_execution_task_status', ExecutionRecord.task_id, ExecutionRecord.status)
Index('idx_execution_asset_status', ExecutionRecord.asset_id, ExecutionRecord.status)
Index('idx_execution_type_status', ExecutionRecord.execution_type, ExecutionRecord.status)
