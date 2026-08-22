"""
测试质量分析报告模型

存储 AI 质量分析的结果,包括:
- 覆盖不足分析(coverage_analysis)
- 高风险模块分析(risk_analysis)
- 重复测试分析(duplication_analysis)
- 缺陷趋势分析(defect_trend)
- 改进建议(recommendations)
- 综合质量分数(quality_score)

状态机: pending → analyzing → completed / failed
"""
import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import Column, String, Text, Boolean, Float, DateTime, Index

from app.models.base import OwnedModel


class QualityReport(OwnedModel):
    """测试质量分析报告

    由 QualityAnalysisAgent 生成,包含覆盖/风险/重复/缺陷趋势四大维度分析。
    """
    __tablename__ = "quality_report"

    # ===== 基础信息 =====
    title = Column(String(200), nullable=False, comment="报告标题")
    description = Column(Text, nullable=True, comment="报告描述")

    # ===== 分析范围 =====
    # JSON: {"asset_ids": [], "execution_ids": [], "time_range": {"start": "", "end": ""},
    #        "modules": [], "env": "", "asset_types": []}
    analysis_scope = Column(Text, nullable=True, comment="分析范围(JSON)")

    # ===== 状态 =====
    # pending / analyzing / completed / failed
    status = Column(
        String(20), nullable=False, default="pending",
        index=True, comment="状态: pending/analyzing/completed/failed"
    )

    # ===== 质量分数 =====
    quality_score = Column(
        Float, nullable=True,
        comment="综合质量分数(0-100), 由四个维度加权计算"
    )
    # 分项分数
    coverage_score = Column(Float, nullable=True, comment="覆盖率分数(0-100)")
    risk_score = Column(Float, nullable=True, comment="风险分数(0-100, 越高越安全)")
    duplication_score = Column(Float, nullable=True, comment="重复度分数(0-100, 越高越少重复)")
    defect_score = Column(Float, nullable=True, comment="缺陷分数(0-100, 越高缺陷越少)")

    # ===== 分析结果(JSON) =====
    summary = Column(Text, nullable=True, comment="总体摘要")

    # 覆盖不足分析 JSON:
    # {
    #   "total_modules": 10,
    #   "covered_modules": 7,
    #   "coverage_rate": 0.7,
    #   "uncovered_modules": [{"module": "...", "reason": "...", "severity": "high/medium/low"}],
    #   "by_type": {"api": 0.8, "web": 0.6, "android": 0.5},
    #   "suggestions": ["..."]
    # }
    coverage_analysis = Column(Text, nullable=True, comment="覆盖不足分析(JSON)")

    # 高风险模块分析 JSON:
    # {
    #   "high_risk_modules": [{"module": "...", "risk_score": 0.85, "reasons": [...], "defect_count": 5}],
    #   "medium_risk_modules": [...],
    #   "low_risk_modules": [...],
    #   "risk_distribution": {"high": 2, "medium": 5, "low": 10},
    #   "suggestions": ["..."]
    # }
    risk_analysis = Column(Text, nullable=True, comment="高风险模块分析(JSON)")

    # 重复测试分析 JSON:
    # {
    #   "duplicate_groups": [{"group_id": "...", "cases": [...], "similarity": 0.9, "suggestion": "merge"}],
    #   "total_cases": 100,
    #   "duplicate_count": 15,
    #   "duplication_rate": 0.15,
    #   "suggestions": ["..."]
    # }
    duplication_analysis = Column(Text, nullable=True, comment="重复测试分析(JSON)")

    # 缺陷趋势分析 JSON:
    # {
    #   "trend": "increasing/stable/decreasing",
    #   "by_period": [{"period": "2026-01", "count": 10, "severity": {"high": 2, "medium": 5, "low": 3}}],
    #   "by_module": [{"module": "...", "count": 8, "top_errors": [...]}],
    #   "by_type": {"assertion": 5, "timeout": 3, "element_not_found": 2},
    #   "predictions": "预计下周期缺陷数...",
    #   "suggestions": ["..."]
    # }
    defect_trend = Column(Text, nullable=True, comment="缺陷趋势分析(JSON)")

    # 改进建议 JSON: ["建议1", "建议2", ...]
    recommendations = Column(Text, nullable=True, comment="改进建议(JSON数组)")

    # ===== 输入数据统计 =====
    # JSON: {"asset_count": 100, "execution_count": 50, "defect_count": 15,
    #        "time_range": {"start": "", "end": ""}, "modules": ["login", "payment"]}
    input_stats = Column(Text, nullable=True, comment="输入数据统计(JSON)")

    # ===== 错误信息 =====
    error_message = Column(Text, nullable=True, comment="分析失败时的错误信息")

    # ===== 时间戳 =====
    started_at = Column(DateTime, nullable=True, comment="分析开始时间")
    completed_at = Column(DateTime, nullable=True, comment="分析完成时间")

    # ===== 软删除 =====
    is_deleted = Column(
        Boolean, default=False, nullable=False, index=True,
        comment="是否删除"
    )

    # ===== 索引 =====
    __table_args__ = (
        Index("idx_quality_report_user_status", "user_id", "status"),
        Index("idx_quality_report_status_created", "status", "created_at"),
        Index("idx_quality_report_user_created", "user_id", "created_at"),
    )

    def to_dict(self, include_analysis: bool = True) -> Dict[str, Any]:
        """转换为字典

        Args:
            include_analysis: 是否包含分析结果(JSON 字段自动解析)
        """
        result = {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "quality_score": self.quality_score,
            "coverage_score": self.coverage_score,
            "risk_score": self.risk_score,
            "duplication_score": self.duplication_score,
            "defect_score": self.defect_score,
            "error_message": self.error_message,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "user_id": self.user_id,
            "created_by": self.created_by,
            "is_deleted": self.is_deleted,
        }

        if include_analysis:
            result["analysis_scope"] = self._parse_json(self.analysis_scope)
            result["summary"] = self.summary
            result["coverage_analysis"] = self._parse_json(self.coverage_analysis)
            result["risk_analysis"] = self._parse_json(self.risk_analysis)
            result["duplication_analysis"] = self._parse_json(self.duplication_analysis)
            result["defect_trend"] = self._parse_json(self.defect_trend)
            result["recommendations"] = self._parse_json(self.recommendations)
            result["input_stats"] = self._parse_json(self.input_stats)
        else:
            # 列表/摘要模式,不返回大字段
            result["analysis_scope"] = self._parse_json(self.analysis_scope)
            result["input_stats"] = self._parse_json(self.input_stats)
            result["summary"] = (self.summary[:200] + "...") if self.summary and len(self.summary) > 200 else self.summary

        return result

    @staticmethod
    def _parse_json(value: Optional[str]) -> Any:
        """安全解析 JSON 字段,失败返回 None"""
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None
