"""
AI 测试反馈学习服务

职责:
  - 创建反馈学习任务(创建汇总记录 + 调用 FeedbackLearningAgent)
  - 学习记录 CRUD(查询/列表/删除)
  - 优化建议 CRUD(查询/列表/应用/拒绝)
  - 应用优化建议(RAG/Prompt/Strategy)
  - 通过 AgentFactory 创建 Agent,通过 LLMGateway 调用 LLM

集成:
  - FeedbackLearningAgent(app.agents.flows.feedback_learning_agent)
  - AgentFactory(app.runtime.agent_factory)
  - PromptManager(app.services.prompt_manager) - 应用 Prompt 优化
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
from app.models.feedback_learning import FeedbackLearningRecord, FeedbackOptimization

logger = logging.getLogger(__name__)


class FeedbackLearningService:
    """AI 测试反馈学习服务"""

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
    # 创建学习任务
    # ============================================================

    def create_learning(
        self,
        payload: Dict[str, Any],
        *,
        user_id: Optional[int] = None,
        background: bool = True,
    ) -> Dict[str, Any]:
        """创建反馈学习任务

        Args:
            payload: 包含 title, description, collect_scope
            user_id: 用户ID
            background: 是否后台执行(True=立即返回,异步执行;False=同步等待)

        Returns:
            学习任务信息(含 optimization_id)
        """
        title = (payload.get("title") or "").strip()
        if not title:
            raise ValueError("title is required")

        description = payload.get("description", "")
        collect_scope = payload.get("collect_scope", {})

        # 1. 创建汇总优化记录(作为学习任务的载体)
        with self._session() as db:
            optimization = FeedbackOptimization(
                title=title,
                description=description,
                optimization_type="strategy",  # 汇总记录用 strategy 类型
                optimization_json=json.dumps(
                    {"collect_scope": collect_scope, "is_summary": True},
                    ensure_ascii=False
                ),
                summary="",
                status="pending",
                user_id=user_id,
                created_by=user_id,
                is_deleted=False,
            )
            db.add(optimization)
            db.flush()
            optimization_id = optimization.id
            result = optimization.to_dict(include_optimization=False)

        logger.info(f"[FeedbackLearningService] 创建学习任务 optimization_id={optimization_id}")

        # 2. 启动 Agent 学习
        if background:
            try:
                asyncio.create_task(
                    self._run_learning_background(optimization_id, collect_scope, user_id)
                )
            except RuntimeError:
                # 无运行中的事件循环(如同步测试环境),忽略后台任务
                logger.warning(
                    f"[FeedbackLearningService] 无事件循环,跳过后台执行 optimization_id={optimization_id}"
                )
        else:
            asyncio.run(
                self._run_learning_background(optimization_id, collect_scope, user_id)
            )

        return result

    async def _run_learning_background(
        self,
        optimization_id: int,
        collect_scope: Dict[str, Any],
        user_id: Optional[int] = None,
    ) -> None:
        """后台执行反馈学习(调用 Agent)"""
        try:
            result = await self.run_learning(optimization_id, collect_scope, user_id)
            logger.info(
                f"[FeedbackLearningService] 后台学习完成 optimization_id={optimization_id} "
                f"status={result.get('status')}"
            )
        except Exception as e:
            logger.error(
                f"[FeedbackLearningService] 后台学习失败 optimization_id={optimization_id}: {e}",
                exc_info=True,
            )
            # 更新状态为失败
            db = SessionLocal()
            try:
                opt = db.query(FeedbackOptimization).filter(
                    FeedbackOptimization.id == optimization_id
                ).first()
                if opt:
                    opt.status = "failed"
                    opt.summary = f"学习失败: {str(e)}"
                    db.commit()
            finally:
                db.close()

    async def run_learning(
        self,
        optimization_id: int,
        collect_scope: Optional[Dict[str, Any]] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """执行反馈学习(调用 FeedbackLearningAgent)

        通过 AgentFactory 创建 Agent 实例,调用 execute 方法。
        """
        from app.runtime.agent_factory import AgentFactory

        # 1. 获取任务信息
        db = SessionLocal()
        try:
            opt = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id
            ).first()
            if opt is None:
                raise ValueError(f"FeedbackOptimization not found: {optimization_id}")
            if not collect_scope:
                opt_json = opt.to_dict().get("optimization_json") or {}
                collect_scope = opt_json.get("collect_scope", {}) if isinstance(opt_json, dict) else {}
            if not user_id:
                user_id = opt.user_id
        finally:
            db.close()

        # 2. 通过 AgentFactory 创建 Agent(硬性约束: 所有 Agent 必须经 AgentFactory)
        agent = AgentFactory.create("feedback_learning_agent")

        # 3. 构造 payload
        payload = {
            "optimization_id": optimization_id,
            "collect_scope": collect_scope,
            "user_id": user_id,
        }

        # 4. 调用 Agent(模拟 MessageContext)
        from autogen_core import MessageContext

        ctx = MessageContext()
        result = await agent.execute(payload, ctx)

        return result

    # ============================================================
    # 学习记录 CRUD
    # ============================================================

    def list_records(
        self,
        *,
        record_type: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """学习记录列表(分页)"""
        db = SessionLocal()
        try:
            q = db.query(FeedbackLearningRecord).filter(
                FeedbackLearningRecord.is_deleted == False
            )
            if user_id is not None:
                q = q.filter(FeedbackLearningRecord.user_id == user_id)
            if record_type:
                q = q.filter(FeedbackLearningRecord.record_type == record_type)
            if agent_name:
                q = q.filter(FeedbackLearningRecord.agent_name == agent_name)
            if status:
                q = q.filter(FeedbackLearningRecord.status == status)

            total = q.count()
            items = (
                q.order_by(desc(FeedbackLearningRecord.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [r.to_dict() for r in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_record(
        self,
        record_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取学习记录详情"""
        db = SessionLocal()
        try:
            q = db.query(FeedbackLearningRecord).filter(
                FeedbackLearningRecord.id == record_id,
                FeedbackLearningRecord.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(FeedbackLearningRecord.user_id == user_id)
            record = q.first()
            return None if record is None else record.to_dict()
        finally:
            db.close()

    def delete_record(
        self,
        record_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除学习记录(默认软删除)"""
        with self._session() as db:
            q = db.query(FeedbackLearningRecord).filter(
                FeedbackLearningRecord.id == record_id
            )
            if user_id is not None:
                q = q.filter(FeedbackLearningRecord.user_id == user_id)
            record = q.first()
            if record is None:
                return False
            if hard:
                db.delete(record)
            else:
                record.is_deleted = True
            db.flush()
        return True

    # ============================================================
    # 优化建议 CRUD
    # ============================================================

    def list_optimizations(
        self,
        *,
        optimization_type: Optional[str] = None,
        agent_name: Optional[str] = None,
        status: Optional[str] = None,
        user_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        """优化建议列表(分页)"""
        db = SessionLocal()
        try:
            q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.is_deleted == False
            )
            if user_id is not None:
                q = q.filter(FeedbackOptimization.user_id == user_id)
            if optimization_type:
                q = q.filter(FeedbackOptimization.optimization_type == optimization_type)
            if agent_name:
                q = q.filter(FeedbackOptimization.agent_name == agent_name)
            if status:
                q = q.filter(FeedbackOptimization.status == status)

            total = q.count()
            items = (
                q.order_by(desc(FeedbackOptimization.created_at))
                .offset((page - 1) * page_size)
                .limit(page_size)
                .all()
            )
            return {
                "items": [o.to_dict() for o in items],
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        finally:
            db.close()

    def get_optimization(
        self,
        optimization_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取优化建议详情"""
        db = SessionLocal()
        try:
            q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id,
                FeedbackOptimization.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(FeedbackOptimization.user_id == user_id)
            opt = q.first()
            return None if opt is None else opt.to_dict()
        finally:
            db.close()

    def delete_optimization(
        self,
        optimization_id: int,
        *,
        hard: bool = False,
        user_id: Optional[int] = None,
    ) -> bool:
        """删除优化建议(默认软删除)"""
        with self._session() as db:
            q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id
            )
            if user_id is not None:
                q = q.filter(FeedbackOptimization.user_id == user_id)
            opt = q.first()
            if opt is None:
                return False
            if hard:
                db.delete(opt)
            else:
                opt.is_deleted = True
            db.flush()
        return True

    # ============================================================
    # 应用优化建议
    # ============================================================

    def apply_optimization(
        self,
        optimization_id: int,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """应用优化建议

        根据 optimization_type 执行不同的应用逻辑:
        - rag: 更新 RAG 检索参数配置(记录建议,人工确认)
        - prompt: 通过 PromptManager 创建新版本并激活
        - strategy: 更新 Agent 配置(记录建议,人工确认)
        """
        db = SessionLocal()
        try:
            opt = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id,
                FeedbackOptimization.is_deleted == False,
            ).first()
            if opt is None:
                raise ValueError(f"FeedbackOptimization not found: {optimization_id}")

            if opt.status == "applied":
                return {
                    "optimization_id": optimization_id,
                    "status": "already_applied",
                    "message": "该优化建议已应用",
                }

            opt_type = opt.optimization_type
            opt_json = opt.to_dict().get("optimization_json") or {}
            if not isinstance(opt_json, dict):
                opt_json = {}

            if opt_type == "prompt":
                # 应用 Prompt 优化: 通过 PromptManager 创建新版本
                applied_result = self._apply_prompt_optimization(opt, opt_json, user_id, db)
            elif opt_type == "rag":
                # RAG 优化: 记录建议参数(实际应用需要人工确认或系统配置)
                applied_result = {
                    "applied": True,
                    "message": "RAG优化建议已标记应用,检索参数需在系统配置中确认",
                    "retrieval_params": opt_json.get("retrieval_params", {}),
                    "index_suggestions": opt_json.get("index_suggestions", []),
                    "knowledge_gaps": opt_json.get("knowledge_gaps", []),
                }
            elif opt_type == "strategy":
                # 策略优化: 记录建议配置
                applied_result = {
                    "applied": True,
                    "message": "策略优化建议已标记应用,Agent配置需在系统管理中确认",
                    "suggested_config": opt_json.get("suggested_config", {}),
                    "current_config": opt_json.get("current_config", {}),
                }
            else:
                applied_result = {"applied": True, "message": "优化建议已应用"}

            # 更新状态
            opt.status = "applied"
            opt.applied_at = datetime.now().isoformat()
            opt.applied_by = user_id
            opt.applied_result = json.dumps(applied_result, ensure_ascii=False)
            db.commit()

            logger.info(
                f"[FeedbackLearningService] 应用优化建议 optimization_id={optimization_id} "
                f"type={opt_type}"
            )

            return {
                "optimization_id": optimization_id,
                "status": "applied",
                "optimization_type": opt_type,
                "applied_result": applied_result,
            }
        except ValueError:
            raise
        except Exception as e:
            db.rollback()
            raise RuntimeError(f"应用优化建议失败: {e}")
        finally:
            db.close()

    def _apply_prompt_optimization(
        self, opt: FeedbackOptimization, opt_json: Dict[str, Any],
        user_id: Optional[int] = None,
        db: Optional[Session] = None,
    ) -> Dict[str, Any]:
        """应用 Prompt 优化: 通过 PromptManager 创建新版本"""
        from app.services.prompt_manager import PromptManager

        agent_name = opt_json.get("agent_name") or opt.agent_name or "unknown"
        prompt_key = opt_json.get("prompt_key", "system_prompt")
        suggested_content = opt_json.get("suggested_content", "")
        change_summary = opt_json.get("change_summary", opt.title)

        if not suggested_content:
            return {
                "applied": False,
                "message": "Prompt优化建议缺少 suggested_content,无法应用",
            }

        # 获取当前活跃版本号
        current_prompt = PromptManager.get_prompt(agent_name, prompt_key)

        # 生成新版本号
        new_version = self._generate_version_number()

        try:
            # 创建新版本
            PromptManager.create_version(
                db=db,
                agent_name=agent_name,
                prompt_key=prompt_key,
                version=new_version,
                content=suggested_content,
                description=change_summary,
                created_by=user_id,
            )

            # 激活新版本
            PromptManager.activate(db, agent_name, prompt_key, new_version)

            return {
                "applied": True,
                "message": f"Prompt新版本 {new_version} 已创建并激活",
                "agent_name": agent_name,
                "prompt_key": prompt_key,
                "new_version": new_version,
                "previous_content_length": len(current_prompt) if current_prompt else 0,
                "new_content_length": len(suggested_content),
            }
        except Exception as e:
            logger.error(f"[FeedbackLearningService] Prompt应用失败: {e}")
            return {
                "applied": False,
                "message": f"Prompt应用失败: {str(e)}",
                "agent_name": agent_name,
                "prompt_key": prompt_key,
            }

    @staticmethod
    def _generate_version_number() -> str:
        """生成版本号"""
        return f"v{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def reject_optimization(
        self,
        optimization_id: int,
        *,
        reason: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """拒绝优化建议"""
        with self._session() as db:
            q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.id == optimization_id,
                FeedbackOptimization.is_deleted == False,
            )
            if user_id is not None:
                q = q.filter(FeedbackOptimization.user_id == user_id)
            opt = q.first()
            if opt is None:
                raise ValueError(f"FeedbackOptimization not found: {optimization_id}")

            opt.status = "rejected"
            opt.applied_at = datetime.now().isoformat()
            opt.applied_by = user_id
            if reason:
                opt.applied_result = json.dumps(
                    {"rejected": True, "reason": reason}, ensure_ascii=False
                )
            db.flush()

            logger.info(
                f"[FeedbackLearningService] 拒绝优化建议 optimization_id={optimization_id}"
            )

            return {
                "optimization_id": optimization_id,
                "status": "rejected",
                "reason": reason,
            }

    # ============================================================
    # 仪表盘
    # ============================================================

    def get_dashboard(
        self,
        *,
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """反馈学习仪表盘(聚合统计)"""
        db = SessionLocal()
        try:
            # 学习记录统计
            record_q = db.query(FeedbackLearningRecord).filter(
                FeedbackLearningRecord.is_deleted == False
            )
            if user_id is not None:
                record_q = record_q.filter(FeedbackLearningRecord.user_id == user_id)
            records = record_q.all()

            record_by_type = {"success": 0, "failure": 0, "modification": 0}
            record_by_status = {"pending": 0, "analyzed": 0, "archived": 0}
            for r in records:
                record_by_type[r.record_type] = record_by_type.get(r.record_type, 0) + 1
                record_by_status[r.status] = record_by_status.get(r.status, 0) + 1

            # 优化建议统计
            opt_q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.is_deleted == False
            )
            if user_id is not None:
                opt_q = opt_q.filter(FeedbackOptimization.user_id == user_id)
            optimizations = opt_q.all()

            opt_by_type = {"rag": 0, "prompt": 0, "strategy": 0}
            opt_by_status = {"pending": 0, "applied": 0, "rejected": 0, "archived": 0}
            avg_confidence = 0.0
            confidence_count = 0

            for o in optimizations:
                opt_by_type[o.optimization_type] = opt_by_type.get(o.optimization_type, 0) + 1
                opt_by_status[o.status] = opt_by_status.get(o.status, 0) + 1
                if o.confidence is not None:
                    avg_confidence += o.confidence
                    confidence_count += 1

            if confidence_count > 0:
                avg_confidence = round(avg_confidence / confidence_count, 4)

            # 最近优化建议
            recent_opts = (
                db.query(FeedbackOptimization)
                .filter(
                    FeedbackOptimization.is_deleted == False,
                    FeedbackOptimization.user_id == user_id if user_id else True,
                )
                .order_by(desc(FeedbackOptimization.created_at))
                .limit(5)
                .all()
            )

            return {
                "records": {
                    "total": len(records),
                    "by_type": record_by_type,
                    "by_status": record_by_status,
                },
                "optimizations": {
                    "total": len(optimizations),
                    "by_type": opt_by_type,
                    "by_status": opt_by_status,
                    "avg_confidence": avg_confidence,
                },
                "recent_optimizations": [o.to_dict(include_optimization=False) for o in recent_opts],
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
            # 记录统计
            record_q = db.query(FeedbackLearningRecord).filter(
                FeedbackLearningRecord.is_deleted == False
            )
            if user_id is not None:
                record_q = record_q.filter(FeedbackLearningRecord.user_id == user_id)
            records = record_q.all()

            # 优化建议统计
            opt_q = db.query(FeedbackOptimization).filter(
                FeedbackOptimization.is_deleted == False
            )
            if user_id is not None:
                opt_q = opt_q.filter(FeedbackOptimization.user_id == user_id)
            optimizations = opt_q.all()

            applied = [o for o in optimizations if o.status == "applied"]
            pending = [o for o in optimizations if o.status == "pending"]
            rejected = [o for o in optimizations if o.status == "rejected"]

            avg_confidence = 0.0
            if applied:
                avg_confidence = sum(o.confidence or 0 for o in applied) / len(applied)

            return {
                "records_total": len(records),
                "records_by_type": {
                    "success": sum(1 for r in records if r.record_type == "success"),
                    "failure": sum(1 for r in records if r.record_type == "failure"),
                    "modification": sum(1 for r in records if r.record_type == "modification"),
                },
                "optimizations_total": len(optimizations),
                "optimizations_applied": len(applied),
                "optimizations_pending": len(pending),
                "optimizations_rejected": len(rejected),
                "avg_confidence": round(avg_confidence, 4),
            }
        finally:
            db.close()


# ============================================================
# 单例
# ============================================================
_service: Optional[FeedbackLearningService] = None


def get_feedback_learning_service() -> FeedbackLearningService:
    global _service
    if _service is None:
        _service = FeedbackLearningService()
    return _service


def reset_feedback_learning_service() -> None:
    """重置单例(测试用)"""
    global _service
    _service = None
