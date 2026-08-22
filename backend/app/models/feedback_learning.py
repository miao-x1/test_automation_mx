"""
AI 测试反馈学习系统数据模型

两张表:
1. FeedbackLearningRecord - 反馈学习记录(收集的成功/失败/修改案例)
2. FeedbackOptimization - 优化建议(分析后生成的 RAG/Prompt/策略优化建议)

数据流:
  执行记录/审核记录/资产版本 → FeedbackLearningRecord(收集)
                                        ↓
                            FeedbackAgent(LLM 分析)
                                        ↓
                            FeedbackOptimization(优化建议)
                                        ↓
                    应用到 RAG(检索参数) / PromptManager(新版本) / 生成策略(配置)
"""
import json
from typing import Any, Dict, Optional

from sqlalchemy import Column, String, Text, Boolean, Float, Integer, Index

from app.models.base import OwnedModel


class FeedbackLearningRecord(OwnedModel):
    """反馈学习记录

    收集三类案例:
    - success: 成功执行案例(ExecutionRecord.status="success")
    - failure: 失败执行案例(ExecutionRecord.status="failed" + analysis_result)
    - modification: 人工修改记录(AssetVersion.diff_summary / TestCaseReview.suggestion)
    """
    __tablename__ = "feedback_learning_record"

    # ===== 基础信息 =====
    record_type = Column(
        String(20), nullable=False, index=True,
        comment="记录类型: success/failure/modification"
    )
    source = Column(
        String(30), nullable=False,
        comment="数据来源: execution/review/asset_version/feedback/quality_report"
    )
    source_id = Column(
        Integer, nullable=True,
        comment="来源记录ID(如 execution_record.id / test_case_review.id)"
    )

    # ===== 关联 Agent =====
    agent_name = Column(
        String(64), nullable=True, index=True,
        comment="关联Agent(case_agent/script_generation_agent/requirement_agent等)"
    )

    # ===== 案例内容 =====
    # JSON 结构因 record_type 而异:
    # success: {asset_id, title, content, execution_id, duration, success_count}
    # failure: {asset_id, title, error_message, log_content, analysis_result, failed_step}
    # modification: {asset_id, change_type, diff_summary, review_score, suggestion, reviewer_comment}
    content_json = Column(Text, nullable=True, comment="案例内容(JSON)")

    # ===== 分析结果 =====
    # JSON: {patterns, common_issues, root_causes, key_factors}
    analysis_json = Column(Text, nullable=True, comment="LLM分析结果(JSON)")

    # ===== 标签与分类 =====
    tags = Column(String(500), nullable=True, comment="标签(逗号分隔)")
    module = Column(String(100), nullable=True, index=True, comment="模块名")

    # ===== 状态 =====
    # pending: 待分析 / analyzed: 已分析 / archived: 已归档
    status = Column(
        String(20), nullable=False, default="pending",
        index=True, comment="状态: pending/analyzed/archived"
    )

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, default=False, nullable=False, index=True,
        comment="是否删除"
    )

    __table_args__ = (
        Index("idx_flr_type_status", "record_type", "status"),
        Index("idx_flr_agent_type", "agent_name", "record_type"),
        Index("idx_flr_user_created", "user_id", "created_at"),
    )

    def to_dict(self, include_content: bool = True) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "record_type": self.record_type,
            "source": self.source,
            "source_id": self.source_id,
            "agent_name": self.agent_name,
            "tags": self.tags,
            "module": self.module,
            "status": self.status,
            "is_deleted": self.is_deleted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user_id": self.user_id,
            "created_by": self.created_by,
        }
        if include_content:
            result["content_json"] = self._parse_json(self.content_json)
            result["analysis_json"] = self._parse_json(self.analysis_json)
        return result

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None


class FeedbackOptimization(OwnedModel):
    """反馈优化建议

    由 FeedbackAgent 分析学习记录后生成,分三类优化:
    - rag: RAG 优化(检索参数、索引策略、知识库补充)
    - prompt: Prompt 优化(通过 PromptManager 创建新版本)
    - strategy: 测试生成策略优化(temperature、max_tokens、模板调整)
    """
    __tablename__ = "feedback_optimization"

    # ===== 基础信息 =====
    title = Column(String(200), nullable=False, comment="优化建议标题")
    description = Column(Text, nullable=True, comment="优化建议描述")

    # ===== 优化类型 =====
    # rag / prompt / strategy
    optimization_type = Column(
        String(20), nullable=False, index=True,
        comment="优化类型: rag/prompt/strategy"
    )

    # ===== 关联 Agent =====
    agent_name = Column(
        String(64), nullable=True, index=True,
        comment="目标Agent(case_agent/script_generation_agent等)"
    )

    # ===== 优化内容 =====
    # JSON 结构因 optimization_type 而异:
    # rag: {retrieval_params: {top_k, threshold}, index_suggestions: [], knowledge_gaps: []}
    # prompt: {prompt_key, current_version, suggested_content, change_summary}
    # strategy: {current_config: {temperature, max_tokens}, suggested_config: {}, reasoning}
    optimization_json = Column(Text, nullable=True, comment="优化内容(JSON)")

    # ===== 关联学习记录 =====
    # JSON: [record_id1, record_id2, ...]
    source_record_ids = Column(Text, nullable=True, comment="来源学习记录ID列表(JSON)")

    # ===== 分析摘要 =====
    summary = Column(Text, nullable=True, comment="优化分析摘要")
    confidence = Column(
        Float, nullable=True,
        comment="置信度(0-1, LLM 对优化建议的自信程度)"
    )

    # ===== 应用状态 =====
    # pending: 待应用 / applied: 已应用 / rejected: 已拒绝 / archived: 已归档
    status = Column(
        String(20), nullable=False, default="pending",
        index=True, comment="状态: pending/applied/rejected/archived"
    )

    # ===== 应用结果 =====
    applied_at = Column(String(30), nullable=True, comment="应用时间(ISO格式)")
    applied_result = Column(Text, nullable=True, comment="应用结果(JSON)")
    applied_by = Column(Integer, nullable=True, comment="应用者用户ID")

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, default=False, nullable=False, index=True,
        comment="是否删除"
    )

    __table_args__ = (
        Index("idx_fo_type_status", "optimization_type", "status"),
        Index("idx_fo_agent_type", "agent_name", "optimization_type"),
        Index("idx_fo_user_created", "user_id", "created_at"),
    )

    def to_dict(self, include_optimization: bool = True) -> Dict[str, Any]:
        result = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "optimization_type": self.optimization_type,
            "agent_name": self.agent_name,
            "summary": self.summary,
            "confidence": self.confidence,
            "status": self.status,
            "applied_at": self.applied_at,
            "applied_by": self.applied_by,
            "is_deleted": self.is_deleted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user_id": self.user_id,
            "created_by": self.created_by,
        }
        if include_optimization:
            result["optimization_json"] = self._parse_json(self.optimization_json)
            result["source_record_ids"] = self._parse_json(self.source_record_ids)
            result["applied_result"] = self._parse_json(self.applied_result)
        return result

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
