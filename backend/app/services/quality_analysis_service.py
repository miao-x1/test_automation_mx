"""
测试质量分析服务

职责:
  - 创建质量分析任务(创建报告记录 + 调用 QualityAnalysisAgent)
  - 报告 CRUD(创建/查询/列表/删除)
  - 质量仪表盘(聚合统计)
  - 通过 AgentFactory 创建 Agent,通过 LLMGateway 调用 LLM

集成:
  - QualityAnalysisAgent(app.agents.flows.quality_analysis_agent)
  - AgentFactory(app.runtime.agent_factory)
  - 数据库(app.db.database)
"""
import asyncio
import json
import logging
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Iterator, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.db.database import SessionLocal
from app.models.quality_report import QualityReport

logger = logging.getLogger(__name__)


class QualityAnalysisService:
    """测试质量分析服务"""

    # 不可更新字段
    _IMMUTABLE = {"id", "created_at", "updated_at", "user_id", "created_by"}

    @contextmanager
    def _session(self) -> Iterator[Session]:
        """事务会话上下文管理器"""
        db = SessionLocal()
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ============================================================
    # 创建分析任务
    # ============================================================

    def create_analysis(
        self,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
        background: bool = True,
    ) -> Dict[str, Any]:
        """创建质量分析任务

        Args:
            payload: 包含 title, description, analysis_scope
            user_id: 用户ID
            background: 是否后台执行(True=立即返回,异步执行;False=同步等待)

        Returns:
            报告信息(含 report_id)
        """
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        description = payload.get("description", "")
        analysis_scope = payload.get("analysis_scope", {})

        # 1. 创建报告记录
        with self._session() as db:
            report = QualityReport(
                title=title,
                description=description,
                analysis_scope=json.dumps(analysis_scope, ensure_ascii=False) if analysis_scope else None,
                status="pending",
                user_id=user_id,
                created_by=user_id,
                is_deleted=False,
            )
            db.add(report)
            db.flush()
            report_id = report.id
            result = report.to_dict(include_analysis=False)

        logger.info(f"[QualityAnalysisService] 创建分析任务 report_id={report_id}")

        # 2. 启动 Agent 分析
        if background:
            # 后台执行
            asyncio.create_task(self._run_analysis_background(report_id, analysis_scope, user_id))
        else:
            # 同步执行
            asyncio.run(self._run_analysis_background(report_id, analysis_scope, user_id))

        return result

    async def _run_analysis_background(
        self,
        report_id: int,
        analysis_scope: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> None:
        """后台执行质量分析(调用 Agent)"""
        try:
            result = await self.run_analysis(report_id, analysis_scope, user_id)
            logger.info(
                f"[QualityAnalysisService] 后台分析完成 report_id={report_id} "
                f"quality_score={result.get('quality_score')}"
            )
        except Exception as e:
            logger.error(
                f"[QualityAnalysisService] 后台分析失败 report_id={report_id}: {e}",
                exc_info=True,
            )
            # 更新状态为失败
            db = SessionLocal()
            try:
                report = db.query(QualityReport).filter(QualityReport.id == report_id).first()
                if report:
                    report.status = "failed"
                    report.error_message = str(e)
                    report.completed_at = datetime.now()
                    db.commit()
            finally:
                db.close()

    async def run_analysis(
        self,
        report_id: int,
        analysis_scope: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行质量分析(调用 QualityAnalysisAgent)

        通过 AgentFactory 创建 Agent 实例,调用 execute 方法。
        """
        from app.runtime.agent_factory import AgentFactory

        # 1. 获取报告信息
        db = SessionLocal()
        try:
            report = db.query(QualityReport).filter(QualityReport.id == report_id).first()
            if report is None:
                raise ValueError(f"QualityReport not found: {report_id}")
            if not analysis_scope:
                analysis_scope = report.to_dict().get("analysis_scope") or {}
            if not user_id:
                user_id = report.user_id
        finally:
            db.close()

        # 2. 通过 AgentFactory 创建 Agent(硬性约束: 所有 Agent 必须经 AgentFactory)
        agent = AgentFactory.create("quality_analysis_agent")

        # 3. 构造 payload
        payload = {
            "report_id": report_id,
            "analysis_scope": analysis_scope,
            "user_id": user_id,
        }

        # 4. 调用 Agent(模拟 MessageContext)
        from autogen_core import MessageContext

        ctx = MessageContext()  # 简化:不需要真实 runtime
        result = await agent.execute(payload, ctx)

        return result

    # ============================================================
    # 报告 CRUD
    # ============================================================

    def get_report(
        self,
        report_id: int,
        *,
        user_id: Optional[int] = None,
        include_analysis: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """获取报告详情"""
        db = SessionLocal()
        try:
            q = db.query(QualityReport).filter(
                QualityReport.id == report_id,
                QualityReport.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)
            report = q.first()
            return None if report is None else report.to_dict(include_analysis=include_analysis)
        finally:
            db.close()

    def list_reports(
        self,
        *,
        keyword: Optional[str] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """报告列表(分页)"""
        db = SessionLocal()
        try:
            q = db.query(QualityReport).filter(QualityReport.is_deleted == False)
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)
            if status:
                q = q.filter(QualityReport.status == status)
            if keyword:
                q = q.filter(QualityReport.title.like(f"%{keyword}%"))

            total = q.count()
            items = (
                q.order_by(desc(QualityReport.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [r.to_dict(include_analysis=False) for r in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def update_report(
        self,
        report_id: int,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """更新报告(仅允许更新 title/description)"""
        with self._session() as db:
            q = db.query(QualityReport).filter(
                QualityReport.id == report_id,
                QualityReport.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)
            report = q.first()
            if report is None:
                raise ValueError(f"QualityReport not found: {report_id}")

            for key, value in payload.items():
                if key in self._IMMUTABLE:
                    continue
                if key in ("title", "description"):
                    setattr(report, key, value)

            db.flush()
            result = report.to_dict(include_analysis=False)

        logger.info(f"[QualityAnalysisService] 更新报告 report_id={report_id}")
        return result

    def delete_report(
        self,
        report_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除报告(默认软删除)"""
        with self._session() as db:
            q = db.query(QualityReport).filter(QualityReport.id == report_id)
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)
            report = q.first()
            if report is None:
                return False
            if hard:
                db.delete(report)
            else:
                report.is_deleted = True
            db.flush()
        logger.info(f"[QualityAnalysisService] 删除报告 report_id={report_id} hard={hard}")
        return True

    # ============================================================
    # 重新分析
    # ============================================================

    def regenerate(
        self,
        report_id: int,
        *,
        user_id: Optional[int] = None,
        background: bool = True,
    ) -> Dict[str, Any]:
        """重新生成分析"""
        db = SessionLocal()
        try:
            q = db.query(QualityReport).filter(
                QualityReport.id == report_id,
                QualityReport.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)
            report = q.first()
            if report is None:
                raise ValueError(f"QualityReport not found: {report_id}")

            # 重置报告状态
            report.status = "pending"
            report.quality_score = None
            report.coverage_score = None
            report.risk_score = None
            report.duplication_score = None
            report.defect_score = None
            report.summary = None
            report.coverage_analysis = None
            report.risk_analysis = None
            report.duplication_analysis = None
            report.defect_trend = None
            report.recommendations = None
            report.error_message = None
            report.started_at = None
            report.completed_at = None
            report.updated_at = datetime.now()
            db.commit()

            analysis_scope = report.to_dict().get("analysis_scope") or {}
            result = report.to_dict(include_analysis=False)
        finally:
            db.close()

        # 启动分析
        if background:
            asyncio.create_task(self._run_analysis_background(report_id, analysis_scope, user_id))
        else:
            asyncio.run(self._run_analysis_background(report_id, analysis_scope, user_id))

        logger.info(f"[QualityAnalysisService] 重新生成分析 report_id={report_id}")
        return result

    # ============================================================
    # 质量仪表盘
    # ============================================================

    def get_dashboard(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """质量仪表盘(聚合统计)"""
        db = SessionLocal()
        try:
            q = db.query(QualityReport).filter(QualityReport.is_deleted == False)
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)

            reports = q.all()

            total = len(reports)
            by_status = {
                "pending": 0,
                "analyzing": 0,
                "completed": 0,
                "failed": 0,
            }
            scores = []
            avg_scores = {
                "quality": 0.0,
                "coverage": 0.0,
                "risk": 0.0,
                "duplication": 0.0,
                "defect": 0.0,
            }
            recent_reports = []

            for r in reports:
                by_status[r.status] = by_status.get(r.status, 0) + 1
                if r.status == "completed" and r.quality_score is not None:
                    scores.append(r.quality_score)
                    avg_scores["quality"] += r.quality_score or 0
                    avg_scores["coverage"] += r.coverage_score or 0
                    avg_scores["risk"] += r.risk_score or 0
                    avg_scores["duplication"] += r.duplication_score or 0
                    avg_scores["defect"] += r.defect_score or 0

            completed_count = len(scores)
            if completed_count > 0:
                for k in avg_scores:
                    avg_scores[k] = round(avg_scores[k] / completed_count, 2)

            # 最近 5 条报告
            recent = (
                db.query(QualityReport)
                .filter(
                    QualityReport.is_deleted == False,
                    QualityReport.user_id == user_id if user_id else True,
                )
                .order_by(desc(QualityReport.created_at))
                .limit(5)
                .all()
            )
            recent_reports = [r.to_dict(include_analysis=False) for r in recent]

            return {
                "total": total,
                "by_status": by_status,
                "avg_scores": avg_scores,
                "completed_count": completed_count,
                "highest_score": max(scores) if scores else None,
                "lowest_score": min(scores) if scores else None,
                "recent_reports": recent_reports,
            }
        finally:
            db.close()

    # ============================================================
    # 统计信息
    # ============================================================

    def get_stats(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """统计信息"""
        db = SessionLocal()
        try:
            q = db.query(QualityReport).filter(QualityReport.is_deleted == False)
            if user_id is not None:
                q = q.filter(QualityReport.user_id == user_id)

            reports = q.all()
            total = len(reports)
            completed = [r for r in reports if r.status == "completed"]
            analyzing = [r for r in reports if r.status == "analyzing"]
            failed = [r for r in reports if r.status == "failed"]

            avg_quality = (
                sum(r.quality_score or 0 for r in completed) / len(completed)
                if completed else 0
            )

            return {
                "total": total,
                "completed": len(completed),
                "analyzing": len(analyzing),
                "failed": len(failed),
                "pending": total - len(completed) - len(analyzing) - len(failed),
                "avg_quality_score": round(avg_quality, 2),
            }
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================
_service: Optional[QualityAnalysisService] = None


def get_quality_analysis_service() -> QualityAnalysisService:
    global _service
    if _service is None:
        _service = QualityAnalysisService()
    return _service


def reset_quality_analysis_service() -> None:
    """重置单例(测试用)"""
    global _service
    _service = None
