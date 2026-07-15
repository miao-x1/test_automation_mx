"""
SessionManager - 统一会话管理服务

职责：
1. 每个用户请求自动生成 Session
2. Session 包含：需求/上传文件/Agent消息/测试点/用例/脚本/日志/思维导图/导出文件
3. 整个 Session 可以恢复
4. 数据库同步设计 - 所有制品持久化
5. 与 GraphFlow 集成

使用方式：
    manager = get_session_manager()

    # 创建会话
    session = manager.create_session(
        user_id=1,
        requirement="测试登录功能",
        input_mode="text",
    )

    # 添加制品
    manager.add_artifact(
        session_id=session.id,
        artifact_type="requirement",
        name="需求文本",
        content={"requirement": "测试登录功能"},
    )

    # 恢复会话
    state = manager.restore_session(session_id)

    # 列出会话
    sessions = manager.list_sessions(user_id=1)
"""
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.models.session import Session, SessionStatus
from app.models.session_artifact import SessionArtifact, ArtifactType
from app.models.agent_event import AgentEvent
from app.models.flow_result import FlowResult

logger = logging.getLogger(__name__)


class SessionManager:
    """
    统一会话管理服务

    特性：
    1. 自动创建 Session（每个用户请求自动生成）
    2. 统一制品存储（SessionArtifact）
    3. 会话恢复（从数据库重建完整状态）
    4. GraphFlow 集成（task_id 关联）
    5. 数据库同步（所有操作即时持久化）
    """

    def __init__(self) -> None:
        self._db = None

    @property
    def db(self):
        """获取数据库会话"""
        if self._db is None or self._db.is_active is False:
            self._db = SessionLocal()
        return self._db

    def _close_db(self) -> None:
        """关闭数据库会话"""
        if self._db and self._db.is_active:
            self._db.close()
        self._db = None

    # ------------------------------------------------------------------ #
    #  Session CRUD                                                        #
    # ------------------------------------------------------------------ #

    def create_session(
        self,
        user_id: Optional[int] = None,
        requirement: str = "",
        input_mode: str = "text",
        session_name: str = "",
        project_id: str = "",
        config: Optional[Dict] = None,
        task_id: Optional[int] = None,
    ) -> Session:
        """
        创建新会话

        每个用户请求自动生成一个 Session。
        """
        db = SessionLocal()
        try:
            if not session_name:
                # 自动生成名称：需求前20字 + 时间戳
                short_req = requirement[:20] if requirement else "新会话"
                session_name = f"{short_req} - {time.strftime('%m-%d %H:%M')}"

            session = Session(
                user_id=user_id,
                session_name=session_name,
                project_id=project_id,
                status=SessionStatus.ACTIVE,
                requirement_text=requirement,
                requirement_summary=requirement[:200] if requirement else "",
                input_mode=input_mode,
                config_json=json.dumps(config, ensure_ascii=False) if config else None,
                task_id=task_id,
                total_tokens=0,
                total_duration=0.0,
                artifact_count=0,
                error_count=0,
            )
            db.add(session)
            db.commit()
            db.refresh(session)

            # 生成 session_key
            session_key = f"user_{user_id or 'anon'}_session_{session.id}"
            session.session_key = session_key
            db.commit()
            db.refresh(session)

            # 保存需求为第一个制品
            if requirement:
                self._add_artifact(
                    db, session.id, user_id,
                    artifact_type=ArtifactType.REQUIREMENT,
                    name="需求文本",
                    content={"requirement": requirement, "input_mode": input_mode},
                    step="requirement",
                    source_agent="User",
                )

            logger.info(
                f"[SessionManager] Session created: id={session.id}, "
                f"key={session_key}, name={session_name}"
            )
            return session
        finally:
            db.close()

    def get_session(self, session_id: int) -> Optional[Session]:
        """获取会话"""
        db = SessionLocal()
        try:
            return db.query(Session).filter(
                Session.id == session_id,
                Session.is_deleted == False,
            ).first()
        finally:
            db.close()

    def list_sessions(
        self,
        user_id: Optional[int] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        列出会话

        返回会话列表，包含制品数量等摘要信息。
        """
        db = SessionLocal()
        try:
            query = db.query(Session).filter(Session.is_deleted == False)
            if user_id is not None:
                query = query.filter(Session.user_id == user_id)
            if status:
                query = query.filter(Session.status == status)
            query = query.order_by(Session.updated_at.desc())
            sessions = query.offset(skip).limit(limit).all()

            result = []
            for s in sessions:
                result.append({
                    "id": s.id,
                    "session_name": s.session_name,
                    "status": s.status,
                    "current_step": s.current_step,
                    "requirement_summary": (s.requirement_summary or "")[:100],
                    "input_mode": s.input_mode,
                    "session_key": s.session_key,
                    "graphflow_task_id": s.graphflow_task_id,
                    "total_tokens": s.total_tokens,
                    "total_duration": s.total_duration,
                    "artifact_count": s.artifact_count,
                    "error_count": s.error_count,
                    "created_at": s.created_at.isoformat() if s.created_at else None,
                    "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                })
            return result
        finally:
            db.close()

    def update_session(
        self,
        session_id: int,
        **kwargs,
    ) -> Optional[Session]:
        """更新会话字段"""
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session is None:
                return None

            for key, value in kwargs.items():
                if hasattr(session, key) and value is not None:
                    setattr(session, key, value)

            db.commit()
            db.refresh(session)
            return session
        finally:
            db.close()

    def delete_session(self, session_id: int) -> bool:
        """软删除会话"""
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session is None:
                return False
            session.is_deleted = True
            session.status = SessionStatus.ARCHIVED
            db.commit()
            return True
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  制品管理                                                            #
    # ------------------------------------------------------------------ #

    def add_artifact(
        self,
        session_id: int,
        artifact_type: str,
        name: str,
        content: Optional[Dict] = None,
        file_path: str = "",
        file_size: int = 0,
        mime_type: str = "",
        step: str = "",
        source_agent: str = "",
        tags: str = "",
        metadata: Optional[Dict] = None,
        user_id: Optional[int] = None,
    ) -> SessionArtifact:
        """
        添加会话制品

        制品类型：
        - requirement: 需求
        - file: 上传文件
        - agent_message: Agent 消息
        - test_point: 测试点
        - case: 生成用例
        - script: 脚本
        - log: 日志
        - mindmap: 思维导图
        - export: 导出文件
        - feedback: 人工反馈
        - review: 评审结果
        """
        db = SessionLocal()
        try:
            artifact = self._add_artifact(
                db, session_id, user_id,
                artifact_type=artifact_type,
                name=name,
                content=content,
                file_path=file_path,
                file_size=file_size,
                mime_type=mime_type,
                step=step,
                source_agent=source_agent,
                tags=tags,
                metadata=metadata,
            )

            # 更新会话的制品计数
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.artifact_count = (session.artifact_count or 0) + 1
                if step:
                    session.current_step = step
                db.commit()

            # 返回 detached 副本
            artifact_copy = type('ArtifactRef', (), {
                'id': artifact.id,
                'session_id': artifact.session_id,
                'artifact_type': artifact.artifact_type,
                'name': artifact.name,
                'step': artifact.step,
                'source_agent': artifact.source_agent,
                'created_at': artifact.created_at,
            })()
            return artifact_copy
        finally:
            db.close()

    def _add_artifact(
        self, db, session_id: int, user_id: Optional[int],
        artifact_type, name, content=None, file_path="", file_size=0,
        mime_type="", step="", source_agent="", tags="", metadata=None,
    ) -> SessionArtifact:
        """内部方法：添加制品（在已有 db 会话中操作）"""
        # 处理 artifact_type
        if isinstance(artifact_type, ArtifactType):
            art_type = artifact_type.value
        else:
            art_type = str(artifact_type)

        artifact = SessionArtifact(
            session_id=session_id,
            user_id=user_id,
            artifact_type=art_type,
            name=name,
            content_json=json.dumps(content, ensure_ascii=False, default=str) if content else None,
            file_path=file_path or None,
            file_size=file_size or None,
            mime_type=mime_type or None,
            step=step or None,
            source_agent=source_agent or None,
            tags=tags or None,
            metadata_json=json.dumps(metadata, ensure_ascii=False, default=str) if metadata else None,
        )
        db.add(artifact)
        db.commit()
        db.refresh(artifact)
        return artifact

    def get_artifacts(
        self,
        session_id: int,
        artifact_type: Optional[str] = None,
        step: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取会话制品列表

        可按类型和步骤过滤。
        """
        db = SessionLocal()
        try:
            query = db.query(SessionArtifact).filter(
                SessionArtifact.session_id == session_id,
                SessionArtifact.is_deleted == False,
            )
            if artifact_type:
                query = query.filter(SessionArtifact.artifact_type == artifact_type)
            if step:
                query = query.filter(SessionArtifact.step == step)
            query = query.order_by(SessionArtifact.order_index, SessionArtifact.created_at)
            artifacts = query.all()

            result = []
            for a in artifacts:
                item = {
                    "id": a.id,
                    "session_id": a.session_id,
                    "artifact_type": a.artifact_type,
                    "name": a.name,
                    "file_path": a.file_path,
                    "file_size": a.file_size,
                    "mime_type": a.mime_type,
                    "step": a.step,
                    "source_agent": a.source_agent,
                    "tags": a.tags,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                if a.content_json:
                    try:
                        item["content"] = json.loads(a.content_json)
                    except json.JSONDecodeError:
                        item["content"] = a.content_json
                if a.metadata_json:
                    try:
                        item["metadata"] = json.loads(a.metadata_json)
                    except json.JSONDecodeError:
                        item["metadata"] = a.metadata_json
                result.append(item)
            return result
        finally:
            db.close()

    def delete_artifact(self, artifact_id: int) -> bool:
        """软删除制品"""
        db = SessionLocal()
        try:
            artifact = db.query(SessionArtifact).filter(
                SessionArtifact.id == artifact_id
            ).first()
            if artifact is None:
                return False
            artifact.is_deleted = True
            db.commit()
            return True
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  会话恢复                                                            #
    # ------------------------------------------------------------------ #

    def restore_session(self, session_id: int) -> Dict[str, Any]:
        """
        恢复整个 Session

        返回完整的会话状态，包括：
        - 会话基本信息
        - 所有制品（按类型分组）
        - Agent 事件历史
        - Flow 结果
        - 统计信息

        前端点击会话后调用此方法，恢复整个 AI 执行历史。
        """
        db = SessionLocal()
        try:
            session = db.query(Session).filter(
                Session.id == session_id,
                Session.is_deleted == False,
            ).first()
            if session is None:
                return {"error": "Session not found"}

            # 获取所有制品
            artifacts = db.query(SessionArtifact).filter(
                SessionArtifact.session_id == session_id,
                SessionArtifact.is_deleted == False,
            ).order_by(SessionArtifact.order_index, SessionArtifact.created_at).all()

            # 按类型分组
            artifacts_by_type: Dict[str, List[Dict]] = {}
            for a in artifacts:
                art_type = a.artifact_type
                if art_type not in artifacts_by_type:
                    artifacts_by_type[art_type] = []

                item = {
                    "id": a.id,
                    "name": a.name,
                    "step": a.step,
                    "source_agent": a.source_agent,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                    "file_path": a.file_path,
                    "file_size": a.file_size,
                }
                if a.content_json:
                    try:
                        item["content"] = json.loads(a.content_json)
                    except json.JSONDecodeError:
                        item["content"] = a.content_json
                artifacts_by_type[art_type].append(item)

            # 获取 Agent 事件（如果有 task_id）
            agent_events = []
            if session.graphflow_task_id:
                events = db.query(AgentEvent).filter(
                    AgentEvent.task_id == session.graphflow_task_id
                ).order_by(AgentEvent.created_at).all()
                agent_events = [
                    {
                        "event_type": e.event_type,
                        "agent_name": e.agent_name,
                        "step": e.step,
                        "status": e.status,
                        "model_name": e.model_name,
                        "total_tokens": e.total_tokens,
                        "duration": e.duration,
                        "message": e.message,
                        "error_message": e.error_message,
                        "is_retry": e.is_retry,
                        "is_final": e.is_final,
                        "created_at": e.created_at.isoformat() if e.created_at else None,
                    }
                    for e in events
                ]

            # 获取 Flow 结果
            flow_results = []
            if session.graphflow_task_id:
                flows = db.query(FlowResult).filter(
                    FlowResult.task_id == session.graphflow_task_id
                ).order_by(FlowResult.created_at).all()
                flow_results = [
                    {
                        "step": f.step,
                        "agent_name": f.agent_name,
                        "status": f.status,
                        "duration": f.duration,
                        "output": f.output_json,
                        "error": f.error_message,
                        "created_at": f.created_at.isoformat() if f.created_at else None,
                    }
                    for f in flows
                ]

            # 获取 Agent 消息记录（来自 agent_message_record 表）
            agent_messages = []
            try:
                from app.models.agent_message_record import AgentMessageRecord
                session_key = session.session_key or str(session.id)
                msg_records = db.query(AgentMessageRecord).filter(
                    AgentMessageRecord.session_id == session_key
                ).order_by(AgentMessageRecord.id).limit(200).all()
                agent_messages = [r.to_dict() for r in msg_records]
            except Exception as e:
                logger.debug(f"[SessionManager] Agent messages query skipped: {e}")

            # 获取 TaskState（来自 task_state 表）
            task_states = []
            try:
                from app.models.task_state import TaskState
                if session.task_id:
                    states = db.query(TaskState).filter(
                        TaskState.task_id == session.task_id
                    ).order_by(TaskState.created_at.desc()).limit(10).all()
                    task_states = [s.to_dict() for s in states]
            except Exception as e:
                logger.debug(f"[SessionManager] TaskState query skipped: {e}")

            # 获取执行日志（来自 execution_record 表）
            execution_logs = []
            try:
                from app.models.execution_record import ExecutionRecord
                if session.task_id:
                    execs = db.query(ExecutionRecord).filter(
                        ExecutionRecord.task_id == session.task_id
                    ).order_by(ExecutionRecord.created_at.desc()).limit(20).all()
                    execution_logs = [
                        {
                            "id": e.id,
                            "status": e.status,
                            "execution_type": e.execution_type,
                            "duration": getattr(e, "duration", None),
                            "created_at": e.created_at.isoformat() if e.created_at else None,
                        }
                        for e in execs
                    ]
            except Exception as e:
                logger.debug(f"[SessionManager] Execution logs query skipped: {e}")

            # 构建完整状态
            return {
                "session": {
                    "id": session.id,
                    "session_name": session.session_name,
                    "status": session.status,
                    "current_step": session.current_step,
                    "requirement_text": session.requirement_text,
                    "requirement_summary": session.requirement_summary,
                    "input_mode": session.input_mode,
                    "session_key": session.session_key,
                    "session_id": session.session_key,
                    "user_id": session.user_id,
                    "task_id": session.task_id,
                    "graphflow_task_id": session.graphflow_task_id,
                    "total_tokens": session.total_tokens,
                    "total_duration": session.total_duration,
                    "artifact_count": session.artifact_count,
                    "error_count": session.error_count,
                    "config": json.loads(session.config_json) if session.config_json else {},
                    "created_at": session.created_at.isoformat() if session.created_at else None,
                    "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                },
                "artifacts": artifacts_by_type,
                "agent_events": agent_events,
                "flow_results": flow_results,
                "agent_messages": agent_messages,
                "task_states": task_states,
                "execution_logs": execution_logs,
                "stats": {
                    "total_artifacts": len(artifacts),
                    "total_events": len(agent_events),
                    "total_flow_results": len(flow_results),
                    "total_agent_messages": len(agent_messages),
                    "total_task_states": len(task_states),
                    "total_execution_logs": len(execution_logs),
                    "artifact_types": list(artifacts_by_type.keys()),
                },
            }
        finally:
            db.close()

    # ------------------------------------------------------------------ #
    #  GraphFlow 集成                                                      #
    # ------------------------------------------------------------------ #

    async def run_graphflow(
        self,
        session_id: int,
        requirement: str = "",
        context: Optional[Dict] = None,
    ) -> Dict[str, Any]:
        """
        为会话执行 GraphFlow 工作流

        1. 更新会话状态
        2. 调用 GraphFlowManager
        3. 保存结果为制品
        """
        from app.runtime.graph_flow_manager import get_graph_flow_manager

        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session is None:
                return {"error": "Session not found"}

            requirement = requirement or session.requirement_text or ""
            session_key = session.session_key or f"session_{session_id}"

            # 更新状态
            session.status = SessionStatus.ACTIVE
            session.current_step = "graphflow"
            db.commit()
        finally:
            db.close()

        # 执行 GraphFlow
        manager = get_graph_flow_manager()
        result = await manager.run(
            task=requirement,
            task_id=f"session_{session_id}",
            session_key=session_key,
            context=context,
        )

        # 保存结果
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session:
                session.graphflow_task_id = result.get("task_id", "")
                session.total_duration = result.get("duration", 0.0)
                session.status = SessionStatus.COMPLETED if result.get("status") == "completed" else SessionStatus.ACTIVE
                db.commit()

            # 保存最终结果为制品
            self._add_artifact(
                db, session_id, session.user_id if session else None,
                artifact_type=ArtifactType.EXPORT,
                name="GraphFlow 执行结果",
                content=result,
                step="graphflow",
                source_agent="GraphFlow",
            )
        finally:
            db.close()

        return result

    # ------------------------------------------------------------------ #
    #  统计                                                                #
    # ------------------------------------------------------------------ #

    def get_session_stats(self, session_id: int) -> Dict[str, Any]:
        """获取会话统计信息"""
        db = SessionLocal()
        try:
            session = db.query(Session).filter(Session.id == session_id).first()
            if session is None:
                return {"error": "Session not found"}

            # 按类型统计制品
            artifacts = db.query(SessionArtifact).filter(
                SessionArtifact.session_id == session_id,
                SessionArtifact.is_deleted == False,
            ).all()

            by_type: Dict[str, int] = {}
            for a in artifacts:
                by_type[a.artifact_type] = by_type.get(a.artifact_type, 0) + 1

            # Agent 事件统计
            event_count = 0
            if session.graphflow_task_id:
                event_count = db.query(AgentEvent).filter(
                    AgentEvent.task_id == session.graphflow_task_id
                ).count()

            return {
                "session_id": session_id,
                "status": session.status,
                "total_artifacts": len(artifacts),
                "artifacts_by_type": by_type,
                "total_events": event_count,
                "total_tokens": session.total_tokens,
                "total_duration": session.total_duration,
                "error_count": session.error_count,
            }
        finally:
            db.close()


# ------------------------------------------------------------------ #
#  单例                                                                #
# ------------------------------------------------------------------ #

_session_manager: Optional[SessionManager] = None


def get_session_manager() -> SessionManager:
    """获取 SessionManager 单例"""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
