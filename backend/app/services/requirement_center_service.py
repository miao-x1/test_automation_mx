"""
RequirementCenter Service - 需求中心服务

第二阶段核心服务，负责：
1. 创建需求分析会话
2. 管理文件上传
3. 调度多个Agent并行分析（ImageAgent/DocumentAgent/VideoAgent/ApiAgent/SchemaAgent/RequirementAgent）
4. 整合所有Agent结果（RequirementMergeAgent）
5. AI评审（RequirementReviewAgent）
6. 生成补充问题
7. 最终确认需求并创建Task

整个流程通过SSE实时推送给前端。
"""
import json
import time
import asyncio
import uuid
import os
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.requirement_center import (
    RequirementSession,
    RequirementFile,
    RequirementContext,
    RequirementAnalysis,
    RequirementReview,
    RequirementSummary,
    RequirementQuestion,
)
from app.models.task import Task, TaskStatus, InputMode, TaskType
from app.agent.router.intent_router import get_intent_router
from app.agent.core.types import IntentType
from app.agents.factory import AgentRegistry


class RequirementCenterService:
    """
    需求中心服务。

    整个流程：
        创建Session → 上传文件 → IntentRouter判断 → 并行Agent分析
        → RequirementMergeAgent整合 → RequirementReviewAgent评审
        → 生成补充问题（如需要）→ 用户确认 → 最终化 → 创建Task
    """

    def __init__(self):
        self._intent_router = get_intent_router()
        self._upload_dir = Path(settings.UPLOAD_DIR) / "requirement_center"

    # ================================================================
    # Session 管理
    # ================================================================

    def create_session(
        self,
        db: Session,
        user_id: int,
        title: str = "",
        input_text: str = "",
        input_urls: str = "",
        additional_context: str = "",
    ) -> RequirementSession:
        """创建需求分析会话"""
        if not title:
            title = f"需求分析-{datetime.now().strftime('%m-%d %H:%M')}"

        session = RequirementSession(
            user_id=user_id,
            created_by=user_id,
            title=title,
            status="created",
            input_text=input_text,
            input_urls=input_urls,
            additional_context=additional_context,
            current_step="upload",
            steps_json=json.dumps([], ensure_ascii=False),
        )
        db.add(session)
        db.commit()
        db.refresh(session)

        # 创建上传目录
        session_dir = self._upload_dir / str(session.id)
        session_dir.mkdir(parents=True, exist_ok=True)

        log.info(f"RequirementSession created: id={session.id}, title='{title}'")
        return session

    def get_session(self, db: Session, session_id: int, user_id: int) -> Optional[RequirementSession]:
        """获取会话（带权限校验）"""
        session = db.query(RequirementSession).filter(
            RequirementSession.id == session_id,
            RequirementSession.user_id == user_id,
            RequirementSession.is_deleted == False,
        ).first()
        return session

    def list_sessions(self, db: Session, user_id: int, limit: int = 20) -> List[RequirementSession]:
        """列出用户的会话"""
        return db.query(RequirementSession).filter(
            RequirementSession.user_id == user_id,
            RequirementSession.is_deleted == False,
        ).order_by(RequirementSession.created_at.desc()).limit(limit).all()

    def delete_session(self, db: Session, session_id: int, user_id: int) -> bool:
        """删除会话（软删除）"""
        session = self.get_session(db, session_id, user_id)
        if not session:
            return False
        session.is_deleted = True
        db.commit()
        return True

    # ================================================================
    # 文件上传
    # ================================================================

    def save_file(
        self,
        db: Session,
        session_id: int,
        file_name: str,
        file_content: bytes,
        file_type: str,
        mime_type: str,
        user_id: int,
    ) -> RequirementFile:
        """保存上传文件并创建记录"""
        session = db.query(RequirementSession).filter(
            RequirementSession.id == session_id,
            RequirementSession.user_id == user_id,
        ).first()
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # 生成存储路径
        ext = Path(file_name).suffix.lower()
        stored_name = f"{uuid.uuid4().hex}{ext}"
        rel_path = f"requirement_center/{session_id}/{stored_name}"
        abs_path = Path(settings.UPLOAD_DIR) / rel_path

        # 确保目录存在
        abs_path.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        with open(abs_path, "wb") as f:
            f.write(file_content)

        # 分类
        category = self._categorize_file(file_name, mime_type)

        # 创建记录
        req_file = RequirementFile(
            session_id=session_id,
            file_name=file_name,
            file_path=rel_path,
            file_type=file_type,
            file_ext=ext.lstrip("."),
            file_size=len(file_content),
            mime_type=mime_type,
            category=category,
            sort_order=0,
            parse_status="pending",
        )
        db.add(req_file)
        db.commit()
        db.refresh(req_file)

        log.info(f"File saved: {file_name} → {rel_path} (category={category})")
        return req_file

    def _categorize_file(self, filename: str, mime_type: str) -> str:
        """根据文件名和MIME类型分类"""
        ext = Path(filename).suffix.lower()
        mime = mime_type.lower()

        # 图片
        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp") or mime.startswith("image/"):
            return "image"

        # 视频
        if ext in (".mp4", ".avi", ".mov", ".mkv") or mime.startswith("video/"):
            return "video"

        # 数据库Schema
        if ext in (".sql", ".ddl") or "sql" in filename.lower():
            return "schema"

        # 文档
        if ext in (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".md", ".json", ".yaml", ".yml"):
            return "document"

        # Swagger/OpenAPI
        if ext == ".json" and ("swagger" in filename.lower() or "openapi" in filename.lower() or "postman" in filename.lower()):
            return "document"

        return "document"

    def get_files(self, db: Session, session_id: int) -> List[RequirementFile]:
        """获取会话的所有文件"""
        return db.query(RequirementFile).filter(
            RequirementFile.session_id == session_id,
        ).order_by(RequirementFile.sort_order, RequirementFile.created_at).all()

    def delete_file(self, db: Session, file_id: int, user_id: int) -> bool:
        """删除文件"""
        req_file = db.query(RequirementFile).join(RequirementSession).filter(
            RequirementFile.id == file_id,
            RequirementSession.user_id == user_id,
        ).first()
        if not req_file:
            return False

        # 删除物理文件
        abs_path = Path(settings.UPLOAD_DIR) / req_file.file_path
        if abs_path.exists():
            abs_path.unlink()

        db.delete(req_file)
        db.commit()
        return True

    # ================================================================
    # 附加上下文
    # ================================================================

    def save_context(
        self,
        db: Session,
        session_id: int,
        system_name: str = "",
        business_background: str = "",
        test_scope: str = "",
        credentials: str = "",
        notes: str = "",
        special_requirements: str = "",
    ) -> RequirementContext:
        """保存附加上下文"""
        # 检查是否已存在
        existing = db.query(RequirementContext).filter(
            RequirementContext.session_id == session_id,
        ).first()

        cred_json = json.dumps({"raw": credentials}, ensure_ascii=False) if credentials else None

        if existing:
            existing.system_name = system_name
            existing.business_background = business_background
            existing.test_scope = test_scope
            existing.credentials = cred_json
            existing.notes = notes
            existing.special_requirements = special_requirements
            db.commit()
            db.refresh(existing)
            return existing

        context = RequirementContext(
            session_id=session_id,
            system_name=system_name,
            business_background=business_background,
            test_scope=test_scope,
            credentials=cred_json,
            notes=notes,
            special_requirements=special_requirements,
        )
        db.add(context)
        db.commit()
        db.refresh(context)
        return context

    def get_context(self, db: Session, session_id: int) -> Optional[RequirementContext]:
        """获取附加上下文"""
        return db.query(RequirementContext).filter(
            RequirementContext.session_id == session_id,
        ).first()

    # ================================================================
    # AI 分析流程（核心）
    # ================================================================

    async def analyze(self, db: Session, session_id: int, user_id: int) -> AsyncGenerator[str, None]:
        """
        启动AI分析流程，SSE流式返回。

        流程步骤：
        1. 上传文件确认
        2. IntentRouter判断需求来源
        3. 并行调用Agent（图片/文档/视频/Schema/文本/URL）
        4. RequirementMergeAgent整合
        5. RequirementReviewAgent评审
        6. 生成补充问题（如有）
        7. 等待用户确认
        """
        session = self.get_session(db, session_id, user_id)
        if not session:
            yield self._sse("error", {"message": "Session not found"})
            return

        # 更新状态
        session.status = "analyzing"
        session.current_step = "analyzing"
        db.commit()

        steps = []
        total_steps = 10

        try:
            # ---- Step 1: 上传文件确认 ----
            step1 = {"name": "upload", "display": "上传文件", "status": "running", "started_at": time.time()}
            steps.append(step1)
            yield self._sse("step_start", {"step": 1, "total": total_steps, "name": "upload", "display": "上传文件"})

            files = self.get_files(db, session_id)
            context = self.get_context(db, session_id)

            step1["status"] = "completed"
            step1["completed_at"] = time.time()
            step1["duration"] = step1["completed_at"] - step1["started_at"]
            step1["output"] = {"file_count": len(files), "files": [{"name": f.file_name, "category": f.category} for f in files]}
            yield self._sse("step_completed", {
                "step": 1, "name": "upload",
                "duration": step1["duration"],
                "output": step1["output"],
            })
            self._save_steps(db, session, steps)

            # ---- Step 2: IntentRouter 判断需求来源 ----
            step2 = {"name": "intent_routing", "display": "智能路由分析", "status": "running", "started_at": time.time()}
            steps.append(step2)
            yield self._sse("step_start", {"step": 2, "total": total_steps, "name": "intent_routing", "display": "智能路由分析"})

            # 收集所有输入
            input_data = {
                "text": session.input_text or "",
                "urls": json.loads(session.input_urls) if session.input_urls else [],
                "files": [{"name": f.file_name, "category": f.category, "ext": f.file_ext} for f in files],
            }
            agent_name, intent = self._intent_router.route_with_intent(input_data)

            # 判断需要调用哪些Agent
            agents_to_run = self._determine_agents(files, session.input_text, session.input_urls)

            step2["status"] = "completed"
            step2["completed_at"] = time.time()
            step2["duration"] = step2["completed_at"] - step2["started_at"]
            step2["output"] = {
                "agents": agents_to_run,
                "intent": intent.value if hasattr(intent, 'value') else str(intent),
            }
            yield self._sse("step_completed", {
                "step": 2, "name": "intent_routing",
                "duration": step2["duration"],
                "output": step2["output"],
            })
            self._save_steps(db, session, steps)

            # ---- Steps 3-8: 并行 Agent 分析 ----
            analysis_results = []
            agent_step_map = {
                "image_agent": (3, "图片解析"),
                "document_agent": (4, "文档解析"),
                "video_agent": (5, "视频解析"),
                "schema_agent": (6, "Schema解析"),
                "requirement_agent": (7, "需求解析"),
                "url_agent": (8, "URL页面分析"),
            }

            # 并行执行所有Agent
            tasks = []
            for agent_key in agents_to_run:
                if agent_key in agent_step_map:
                    step_num, display = agent_step_map[agent_key]
                    step_data = {
                        "name": agent_key,
                        "display": display,
                        "status": "running",
                        "started_at": time.time(),
                    }
                    steps.append(step_data)
                    yield self._sse("step_start", {
                        "step": step_num, "total": total_steps,
                        "name": agent_key, "display": display,
                    })
                    tasks.append((agent_key, step_num, step_data))

            # 并行执行
            results = await self._run_agents_parallel(db, session, files, context, agents_to_run, user_id)

            for agent_key, step_num, step_data in tasks:
                result = results.get(agent_key, {})
                analysis_results.append(result)

                step_data["status"] = "completed" if result.get("status") != "failed" else "failed"
                step_data["completed_at"] = time.time()
                step_data["duration"] = step_data["completed_at"] - step_data["started_at"]
                step_data["output"] = result.get("output", {})
                step_data["error"] = result.get("error")

                event = "step_completed" if step_data["status"] == "completed" else "step_failed"
                yield self._sse(event, {
                    "step": step_num,
                    "name": agent_key,
                    "duration": step_data["duration"],
                    "output": step_data["output"],
                    "error": step_data.get("error"),
                })

            self._save_steps(db, session, steps)

            # ---- Step 9: RequirementMergeAgent 整合 ----
            step9 = {"name": "merge", "display": "Requirement整合", "status": "running", "started_at": time.time()}
            steps.append(step9)
            yield self._sse("step_start", {"step": 9, "total": total_steps, "name": "merge", "display": "Requirement整合"})

            merge_result = self._merge_analysis(db, session, analysis_results, context)

            step9["status"] = "completed"
            step9["completed_at"] = time.time()
            step9["duration"] = step9["completed_at"] - step9["started_at"]
            step9["output"] = merge_result
            yield self._sse("step_completed", {
                "step": 9, "name": "merge",
                "duration": step9["duration"],
                "output": merge_result,
            })
            self._save_steps(db, session, steps)

            # ---- Step 10: RequirementReviewAgent 评审 ----
            step10 = {"name": "review", "display": "AI评审", "status": "running", "started_at": time.time()}
            steps.append(step10)
            yield self._sse("step_start", {"step": 10, "total": total_steps, "name": "review", "display": "AI评审"})

            review_result = self._review_requirement(db, session, merge_result)

            step10["status"] = "completed"
            step10["completed_at"] = time.time()
            step10["duration"] = step10["completed_at"] - step10["started_at"]
            step10["output"] = review_result
            yield self._sse("step_completed", {
                "step": 10, "name": "review",
                "duration": step10["duration"],
                "output": review_result,
            })
            self._save_steps(db, session, steps)

            # 保存摘要到数据库
            self._save_summary(db, session, merge_result)

            # 如果需要用户补充
            if review_result.get("needs_user_input") and review_result.get("questions"):
                session.status = "reviewing"
                session.current_step = "reviewing"
                db.commit()

                yield self._sse("needs_input", {
                    "questions": review_result["questions"],
                    "review_summary": review_result.get("review_summary", ""),
                })
            else:
                # 不需要补充，直接完成
                session.status = "finalized"
                session.current_step = "finalized"
                session.final_requirement = merge_result.get("requirement_text", "")
                session.finalized = True
                db.commit()

                yield self._sse("analyzed", {
                    "summary": merge_result,
                    "review": review_result,
                    "final_requirement": session.final_requirement,
                })

        except Exception as e:
            log.error(f"RequirementCenter analyze error: {e}", exc_info=True)
            session.status = "failed"
            session.current_step = "failed"
            db.commit()
            yield self._sse("error", {"message": str(e)})

    def _determine_agents(self, files: List[RequirementFile], text: str, urls: str) -> List[str]:
        """根据输入确定需要调用的Agent"""
        agents = set()

        # 文件类型 → Agent
        for f in files:
            if f.category == "image":
                agents.add("image_agent")
            elif f.category == "video":
                agents.add("video_agent")
            elif f.category == "schema":
                agents.add("schema_agent")
            elif f.category == "document":
                agents.add("document_agent")

        # 文本 → RequirementAgent
        if text and text.strip():
            agents.add("requirement_agent")

        # URL → URL Agent
        if urls:
            url_list = json.loads(urls) if isinstance(urls, str) else urls
            if url_list:
                agents.add("url_agent")

        return list(agents)

    async def _run_agents_parallel(
        self,
        db: Session,
        session: RequirementSession,
        files: List[RequirementFile],
        context: Optional[RequirementContext],
        agents: List[str],
        user_id: int,
    ) -> Dict[str, Any]:
        """并行执行多个Agent"""
        results = {}

        async def run_single(agent_name: str):
            try:
                result = await self._run_single_agent(db, session, agent_name, files, context, user_id)
                results[agent_name] = result
            except Exception as e:
                log.error(f"Agent '{agent_name}' failed: {e}")
                results[agent_name] = {
                    "agent_name": agent_name,
                    "status": "failed",
                    "error": str(e),
                    "output": {},
                }

        # 并行执行
        await asyncio.gather(*[run_single(a) for a in agents])
        return results

    async def _run_single_agent(
        self,
        db: Session,
        session: RequirementSession,
        agent_name: str,
        files: List[RequirementFile],
        context: Optional[RequirementContext],
        user_id: int,
    ) -> Dict[str, Any]:
        """执行单个Agent"""
        start = time.time()
        agent_files = []
        input_text = ""
        intent_type = ""

        # 准备输入
        if agent_name == "image_agent":
            agent_files = [f for f in files if f.category == "image"]
            intent_type = "image"
        elif agent_name == "document_agent":
            agent_files = [f for f in files if f.category == "document"]
            intent_type = "document"
        elif agent_name == "video_agent":
            agent_files = [f for f in files if f.category == "video"]
            intent_type = "video"
        elif agent_name == "schema_agent":
            agent_files = [f for f in files if f.category == "schema"]
            intent_type = "schema"
        elif agent_name == "requirement_agent":
            input_text = session.input_text or ""
            intent_type = "text"
        elif agent_name == "url_agent":
            urls = json.loads(session.input_urls) if session.input_urls else []
            input_text = "\n".join(urls)
            intent_type = "url"

        # 创建分析记录
        analysis = RequirementAnalysis(
            session_id=session.id,
            agent_name=agent_name,
            agent_display_name=self._agent_display_name(agent_name),
            intent_type=intent_type,
            status="running",
            input_summary=self._build_input_summary(agent_name, agent_files, input_text, context),
        )
        if agent_files:
            analysis.file_id = agent_files[0].id
        db.add(analysis)
        db.commit()
        db.refresh(analysis)

        try:
            # 调用Agent
            output = await self._call_agent(agent_name, agent_files, input_text, context, session)

            # 更新记录
            analysis.status = "completed"
            analysis.duration = time.time() - start
            analysis.output_json = json.dumps(output, ensure_ascii=False, default=str)
            analysis.parse_status = "parsed" if agent_files else None

            # 更新文件解析状态
            for f in agent_files:
                f.parse_status = "parsed"
                f.parse_result = json.dumps(output, ensure_ascii=False, default=str)[:10000]

            db.commit()

            return {
                "agent_name": agent_name,
                "status": "completed",
                "duration": analysis.duration,
                "output": output,
            }

        except Exception as e:
            analysis.status = "failed"
            analysis.duration = time.time() - start
            analysis.error_message = str(e)
            db.commit()
            raise

    async def _call_agent(
        self,
        agent_name: str,
        files: List[RequirementFile],
        text: str,
        context: Optional[RequirementContext],
        session: RequirementSession,
    ) -> Dict[str, Any]:
        """调用具体Agent并返回结果"""

        # ImageAgent - 调用视觉LLM分析图片
        if agent_name == "image_agent":
            return await self._analyze_images(files, session)

        # DocumentAgent - 解析文档
        if agent_name == "document_agent":
            return await self._analyze_documents(files, session)

        # VideoAgent - 分析视频（预留，当前降级为图片分析）
        if agent_name == "video_agent":
            return await self._analyze_videos(files, session)

        # SchemaAgent - 解析数据库Schema
        if agent_name == "schema_agent":
            return await self._analyze_schema(files, session)

        # RequirementAgent - 解析自然语言需求
        if agent_name == "requirement_agent":
            return await self._analyze_requirement(text, context, session)

        # URL Agent - 分析URL
        if agent_name == "url_agent":
            return await self._analyze_urls(text, session)

        return {"status": "unknown", "output": {}}

    async def _analyze_images(self, files: List[RequirementFile], session: RequirementSession) -> Dict:
        """分析图片"""
        from app.agent.vision.element_agent import ElementAgent
        agent = ElementAgent()

        results = []
        for f in files:
            abs_path = Path(settings.UPLOAD_DIR) / f.file_path
            if not abs_path.exists():
                results.append({"file": f.file_name, "error": "File not found"})
                continue
            try:
                result = agent.analyze_image(str(f.id), str(abs_path))
                # analyze_image 是async generator
                async for item in result:
                    if item.get("type") == "complete":
                        results.append({
                            "file": f.file_name,
                            "elements": item.get("data", {}).get("elements", []),
                            "page_type": item.get("data", {}).get("page_type", ""),
                            "page_url": item.get("data", {}).get("page_url", ""),
                        })
                        break
            except Exception as e:
                results.append({"file": f.file_name, "error": str(e)})

        return {
            "type": "image_analysis",
            "file_count": len(files),
            "results": results,
            "total_elements": sum(len(r.get("elements", [])) for r in results),
        }

    async def _analyze_documents(self, files: List[RequirementFile], session: RequirementSession) -> Dict:
        """分析文档"""
        results = []
        for f in files:
            abs_path = Path(settings.UPLOAD_DIR) / f.file_path
            if not abs_path.exists():
                results.append({"file": f.file_name, "error": "File not found"})
                continue

            try:
                # 根据文件类型解析
                if f.file_ext in ("txt", "md"):
                    content = abs_path.read_text(encoding="utf-8", errors="replace")
                    results.append({
                        "file": f.file_name,
                        "type": "text",
                        "content": content[:5000],
                        "char_count": len(content),
                    })
                elif f.file_ext == "json":
                    content = abs_path.read_text(encoding="utf-8", errors="replace")
                    data = json.loads(content)
                    results.append({
                        "file": f.file_name,
                        "type": "json",
                        "is_swagger": "swagger" in f.file_name.lower() or "openapi" in f.file_name.lower(),
                        "paths": list(data.get("paths", {}).keys())[:20] if isinstance(data, dict) else [],
                        "title": data.get("info", {}).get("title", "") if isinstance(data, dict) else "",
                    })
                elif f.file_ext in ("yaml", "yml"):
                    content = abs_path.read_text(encoding="utf-8", errors="replace")
                    results.append({
                        "file": f.file_name,
                        "type": "yaml",
                        "content": content[:5000],
                    })
                else:
                    results.append({
                        "file": f.file_name,
                        "type": "binary",
                        "ext": f.file_ext,
                        "note": f"Binary file, need specific parser for {f.file_ext}",
                    })
            except Exception as e:
                results.append({"file": f.file_name, "error": str(e)})

        return {
            "type": "document_analysis",
            "file_count": len(files),
            "results": results,
        }

    async def _analyze_videos(self, files: List[RequirementFile], session: RequirementSession) -> Dict:
        """分析视频（预留，当前降级为元信息提取）"""
        results = []
        for f in files:
            results.append({
                "file": f.file_name,
                "type": "video",
                "ext": f.file_ext,
                "size": f.file_size,
                "note": "Video analysis not yet fully implemented, using metadata only",
            })

        return {
            "type": "video_analysis",
            "file_count": len(files),
            "results": results,
        }

    async def _analyze_schema(self, files: List[RequirementFile], session: RequirementSession) -> Dict:
        """分析数据库Schema"""
        results = []
        for f in files:
            abs_path = Path(settings.UPLOAD_DIR) / f.file_path
            if not abs_path.exists():
                results.append({"file": f.file_name, "error": "File not found"})
                continue

            try:
                content = abs_path.read_text(encoding="utf-8", errors="replace")
                # 简单解析SQL DDL
                tables = []
                current_table = None
                for line in content.split("\n"):
                    line = line.strip()
                    if line.upper().startswith("CREATE TABLE"):
                        table_name = line.split("CREATE TABLE")[-1].strip(" ();").strip("`").strip('"')
                        current_table = {"name": table_name, "columns": []}
                        tables.append(current_table)
                    elif current_table and line and not line.startswith("--") and not line.startswith(")"):
                        current_table["columns"].append(line)

                results.append({
                    "file": f.file_name,
                    "type": "schema",
                    "tables": [{"name": t["name"], "column_count": len(t["columns"])} for t in tables],
                    "table_count": len(tables),
                    "raw_content": content[:3000],
                })
            except Exception as e:
                results.append({"file": f.file_name, "error": str(e)})

        return {
            "type": "schema_analysis",
            "file_count": len(files),
            "results": results,
        }

    async def _analyze_requirement(self, text: str, context: Optional[RequirementContext], session: RequirementSession) -> Dict:
        """分析自然语言需求"""
        agent = AgentRegistry.create("requirement_agent")

        # 拼接上下文
        full_text = text
        if context:
            parts = []
            if context.system_name:
                parts.append(f"系统名称: {context.system_name}")
            if context.business_background:
                parts.append(f"业务背景: {context.business_background}")
            if context.test_scope:
                parts.append(f"测试范围: {context.test_scope}")
            if context.notes:
                parts.append(f"注意事项: {context.notes}")
            if context.special_requirements:
                parts.append(f"特殊要求: {context.special_requirements}")
            if parts:
                full_text += "\n\n附加上下文:\n" + "\n".join(parts)

        result = agent.analyze(full_text)
        return {
            "type": "requirement_analysis",
            "intent": result.get("intent", ""),
            "summary": result.get("summary", ""),
            "target_url": result.get("target_url", ""),
            "steps": result.get("steps", []),
        }

    async def _analyze_urls(self, urls_text: str, session: RequirementSession) -> Dict:
        """分析URL"""
        from app.agent.vision.page_crawler_agent import PageCrawlerAgent
        agent = PageCrawlerAgent()

        urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
        results = []

        for url in urls[:5]:  # 限制最多5个URL
            try:
                async for item in agent.crawl_page(str(session.id), url):
                    if item.get("type") == "complete":
                        data = item.get("data", {})
                        results.append({
                            "url": url,
                            "screenshot": data.get("screenshot_path", ""),
                            "element_count": data.get("element_count", 0),
                            "elements": data.get("elements", [])[:20],  # 限制元素数量
                        })
                        break
            except Exception as e:
                results.append({"url": url, "error": str(e)})

        return {
            "type": "url_analysis",
            "url_count": len(urls),
            "results": results,
            "total_elements": sum(r.get("element_count", 0) for r in results),
        }

    # ================================================================
    # 合并 & 评审
    # ================================================================

    def _merge_analysis(
        self,
        db: Session,
        session: RequirementSession,
        analysis_results: List[Dict],
        context: Optional[RequirementContext],
    ) -> Dict:
        """
        整合所有Agent结果。

        使用 RequirementMergeAgent 逻辑：
        - 需求摘要
        - 页面说明
        - 页面元素
        - 业务流程
        - 测试目标
        - 风险点
        - 建议测试类型
        - 关联页面
        - 推荐测试策略
        """
        # 收集所有元素
        all_elements = []
        all_steps = []
        all_keywords = []
        all_urls = []
        target_url = ""
        requirement_text_parts = []

        for result in analysis_results:
            output = result.get("output", {})

            # 图片分析结果
            if output.get("type") == "image_analysis":
                for r in output.get("results", []):
                    all_elements.extend(r.get("elements", []))

            # 需求分析结果
            if output.get("type") == "requirement_analysis":
                all_steps.extend(output.get("steps", []))
                all_keywords.extend(output.get("summary", "").split())
                target_url = output.get("target_url", "") or target_url
                requirement_text_parts.append(output.get("summary", ""))

            # URL分析结果
            if output.get("type") == "url_analysis":
                for r in output.get("results", []):
                    all_elements.extend(r.get("elements", []))
                    all_urls.append(r.get("url", ""))

            # 文档分析结果
            if output.get("type") == "document_analysis":
                for r in output.get("results", []):
                    if r.get("content"):
                        requirement_text_parts.append(r["content"][:1000])

            # Schema分析结果
            if output.get("type") == "schema_analysis":
                for r in output.get("results", []):
                    requirement_text_parts.append(f"数据库表: {', '.join(t['name'] for t in r.get('tables', []))}")

        # 上下文信息
        if context:
            if context.system_name:
                requirement_text_parts.append(f"系统: {context.system_name}")
            if context.test_scope:
                requirement_text_parts.append(f"测试范围: {context.test_scope}")

        # 去重
        all_elements = self._deduplicate_elements(all_elements)
        all_urls = list(set(all_urls))

        # 生成需求文本
        requirement_text = "\n\n".join(requirement_text_parts) if requirement_text_parts else "未提供具体需求文本"

        # 构建摘要
        summary = {
            "requirement_text": requirement_text,
            "page_description": {
                "target_url": target_url,
                "page_count": len(all_urls),
                "urls": all_urls,
            },
            "page_elements": all_elements[:100],
            "business_flows": [{"step": s} if isinstance(s, str) else s for s in all_steps],
            "test_goals": self._derive_test_goals(all_steps, all_keywords, context),
            "risk_points": self._derive_risk_points(all_elements, context),
            "recommended_test_types": self._recommend_test_types(all_elements, all_urls, analysis_results),
            "related_pages": all_urls,
            "recommended_strategy": {
                "primary": "playwright",
                "reason": "Web页面测试推荐使用Playwright",
                "has_elements": len(all_elements) > 0,
                "has_url": bool(target_url or all_urls),
            },
            "confidence": 0.7 if all_elements or all_steps else 0.3,
            "source_agents": [r.get("agent_name", "") for r in analysis_results],
            "analysis_count": len(analysis_results),
        }

        return summary

    def _deduplicate_elements(self, elements: List[Dict]) -> List[Dict]:
        """元素去重"""
        seen = set()
        result = []
        for el in elements:
            key = el.get("name", "") or el.get("text", "") or el.get("locator", "")
            if key and key not in seen:
                seen.add(key)
                result.append(el)
        return result

    def _derive_test_goals(self, steps: List, keywords: List, context: Optional[RequirementContext]) -> List[Dict]:
        """推导测试目标"""
        goals = []
        for step in steps:
            if isinstance(step, str):
                goals.append({"goal": step, "type": "functional"})
            elif isinstance(step, dict):
                goals.append({"goal": step.get("step", str(step)), "type": "functional"})

        if context and context.test_scope:
            goals.append({"goal": f"测试范围: {context.test_scope}", "type": "scope"})

        return goals[:20]

    def _derive_risk_points(self, elements: List[Dict], context: Optional[RequirementContext]) -> List[Dict]:
        """推导风险点"""
        risks = []

        # 检查是否有登录表单
        has_login = any(
            "password" in str(el.get("type", "")).lower()
            or "password" in str(el.get("name", "")).lower()
            for el in elements
        )
        if has_login:
            risks.append({"risk": "需要登录验证", "level": "high", "category": "authentication"})

        # 检查是否有验证码
        has_captcha = any(
            "captcha" in str(el).lower() or "验证码" in str(el)
            for el in elements
        )
        if has_captcha:
            risks.append({"risk": "包含验证码，可能影响自动化", "level": "medium", "category": "captcha"})

        # 上下文风险
        if context and context.notes:
            risks.append({"risk": f"用户标注注意事项: {context.notes[:100]}", "level": "medium", "category": "user_note"})

        if not risks:
            risks.append({"risk": "暂无明确风险", "level": "low", "category": "none"})

        return risks

    def _recommend_test_types(self, elements: List[Dict], urls: List[str], results: List[Dict]) -> List[str]:
        """推荐测试类型"""
        types = set()

        if elements or urls:
            types.add("web")

        # 检查是否有API文档
        for r in results:
            output = r.get("output", {})
            if output.get("type") == "document_analysis":
                for doc in output.get("results", []):
                    if doc.get("is_swagger") or doc.get("type") == "json":
                        types.add("api")

        # 检查是否有视频（移动端测试）
        for r in results:
            if r.get("agent_name") == "video_agent":
                types.add("android")

        if not types:
            types.add("web")

        return list(types)

    def _review_requirement(self, db: Session, session: RequirementSession, merge_result: Dict) -> Dict:
        """
        AI评审需求。

        检查：
        - 是否完整
        - 是否冲突
        - 是否缺失
        - 是否存在无法理解内容

        如果存在问题，生成补充问题。
        """
        completeness = 0.5
        conflicts = []
        missing = []
        questions = []
        suggestions = []

        # 完整性检查
        if not merge_result.get("page_elements"):
            completeness -= 0.1
            missing.append("页面元素")
            questions.append({
                "question": "是否需要提供页面截图或URL以便分析页面元素？",
                "type": "boolean",
                "category": "page",
                "required": False,
                "default_answer": "是",
            })

        if not merge_result.get("business_flows"):
            completeness -= 0.1
            missing.append("业务流程")
            questions.append({
                "question": "请描述主要业务流程步骤",
                "type": "text",
                "category": "flow",
                "required": False,
            })

        if not merge_result.get("test_goals"):
            completeness -= 0.1
            missing.append("测试目标")
            questions.append({
                "question": "本次测试的具体目标是什么？",
                "type": "text",
                "category": "goal",
                "required": False,
            })

        # 风险检查
        risk_points = merge_result.get("risk_points", [])
        for risk in risk_points:
            if risk.get("category") == "authentication":
                questions.append({
                    "question": "是否需要登录？如需要，请提供测试账号信息",
                    "type": "text",
                    "category": "login",
                    "required": True,
                })

            if risk.get("category") == "captcha":
                questions.append({
                    "question": "是否包含短信验证码或图形验证码？",
                    "type": "boolean",
                    "category": "sms",
                    "required": True,
                    "default_answer": "否",
                })

        # 完整性评分
        completeness = max(0.0, min(1.0, completeness + (0.5 if merge_result.get("page_elements") else 0)))

        needs_input = len(questions) > 0

        # 创建评审记录
        review = RequirementReview(
            session_id=session.id,
            review_round=1,
            status="completed" if not needs_input else "needs_input",
            completeness_score=completeness,
            conflict_score=0.0,
            missing_items=json.dumps(missing, ensure_ascii=False),
            conflicts=json.dumps(conflicts, ensure_ascii=False),
            suggestions=json.dumps(suggestions, ensure_ascii=False),
            review_summary=f"评审完成，完整性评分: {completeness:.1%}",
            needs_user_input=needs_input,
        )
        db.add(review)
        db.commit()
        db.refresh(review)

        # 创建问题记录并获取ID
        saved_questions = []
        for q in questions:
            question = RequirementQuestion(
                session_id=session.id,
                review_id=review.id,
                question_text=q["question"],
                question_type=q.get("type", "text"),
                category=q.get("category", "other"),
                options=json.dumps(q.get("options", []), ensure_ascii=False) if q.get("options") else None,
                default_answer=q.get("default_answer"),
                required=q.get("required", False),
            )
            db.add(question)
            db.flush()  # flush to get question.id
            saved_questions.append({
                "id": question.id,
                "question_text": question.question_text,
                "question_type": question.question_type,
                "category": question.category or "other",
                "options": json.loads(question.options) if question.options else [],
                "default_answer": question.default_answer,
                "required": question.required,
            })
        db.commit()

        return {
            "review_id": review.id,
            "completeness": completeness,
            "missing_items": missing,
            "conflicts": conflicts,
            "suggestions": suggestions,
            "review_summary": review.review_summary,
            "needs_user_input": needs_input,
            "questions": saved_questions,
        }

    def _save_summary(self, db: Session, session: RequirementSession, merge_result: Dict):
        """保存摘要到数据库"""
        # 删除旧摘要
        db.query(RequirementSummary).filter(RequirementSummary.session_id == session.id).delete()

        summary = RequirementSummary(
            session_id=session.id,
            requirement_text=merge_result.get("requirement_text", ""),
            page_description=json.dumps(merge_result.get("page_description", {}), ensure_ascii=False),
            page_elements=json.dumps(merge_result.get("page_elements", []), ensure_ascii=False, default=str),
            business_flows=json.dumps(merge_result.get("business_flows", []), ensure_ascii=False),
            test_goals=json.dumps(merge_result.get("test_goals", []), ensure_ascii=False),
            risk_points=json.dumps(merge_result.get("risk_points", []), ensure_ascii=False),
            recommended_test_types=json.dumps(merge_result.get("recommended_test_types", []), ensure_ascii=False),
            related_pages=json.dumps(merge_result.get("related_pages", []), ensure_ascii=False),
            recommended_strategy=json.dumps(merge_result.get("recommended_strategy", {}), ensure_ascii=False),
            confidence=merge_result.get("confidence", 0.0),
            source_agents=json.dumps(merge_result.get("source_agents", []), ensure_ascii=False),
            analysis_count=merge_result.get("analysis_count", 0),
        )
        db.add(summary)
        db.commit()

    # ================================================================
    # 评审回答 & 最终化
    # ================================================================

    def submit_review_answers(
        self,
        db: Session,
        session_id: int,
        answers: List[Dict],
        user_id: int,
    ) -> RequirementReview:
        """提交评审回答"""
        session = self.get_session(db, session_id, user_id)
        if not session:
            raise ValueError("Session not found")

        # 更新问题回答
        for answer in answers:
            question_id = answer.get("question_id")
            answer_text = answer.get("answer", "")

            question = db.query(RequirementQuestion).filter(
                RequirementQuestion.id == question_id,
                RequirementQuestion.session_id == session_id,
            ).first()

            if question:
                question.answer = answer_text
                question.answered = True
                question.answered_at = datetime.now()

        # 更新评审状态
        review = db.query(RequirementReview).filter(
            RequirementReview.session_id == session_id,
        ).order_by(RequirementReview.review_round.desc()).first()

        if review:
            review.status = "user_answered"
            review.user_answers = json.dumps(answers, ensure_ascii=False)

        session.status = "finalized"
        session.current_step = "finalized"
        db.commit()

        return review

    def finalize(
        self,
        db: Session,
        session_id: int,
        final_requirement: str,
        user_id: int,
    ) -> Dict:
        """最终化需求并创建Task"""
        session = self.get_session(db, session_id, user_id)
        if not session:
            raise ValueError("Session not found")

        # 更新最终需求
        session.final_requirement = final_requirement
        session.finalized = True
        session.status = "finalized"
        db.commit()

        # 获取摘要
        summary = db.query(RequirementSummary).filter(
            RequirementSummary.session_id == session_id,
        ).first()

        # 创建Task
        test_types = json.loads(summary.recommended_test_types) if summary else ["web"]
        task_type = "web"
        if "api" in test_types:
            task_type = "api"
        elif "android" in test_types:
            task_type = "android"

        target_url = ""
        if summary:
            page_desc = json.loads(summary.page_description) if summary.page_description else {}
            target_url = page_desc.get("target_url", "")

        task = Task(
            user_id=user_id,
            created_by=user_id,
            task_name=session.title,
            status=TaskStatus.PENDING,
            input_mode=InputMode.REQUIREMENT,
            page_url=target_url,
            task_type=TaskType(task_type),
            type_config=json.dumps({"requirement_session_id": session_id}, ensure_ascii=False),
        )
        db.add(task)
        db.commit()
        db.refresh(task)

        # 更新Session关联
        session.task_id = task.id
        db.commit()

        # 创建旧版RequirementTask（兼容）
        from app.models.requirement_task import RequirementTask
        req_task = RequirementTask(
            user_id=user_id,
            created_by=user_id,
            requirement=final_requirement,
            status="COMPLETED",
            task_id=task.id,
            task_type=task_type,
            additional_info=session.additional_context,
        )
        db.add(req_task)
        db.commit()
        db.refresh(req_task)

        session.requirement_task_id = req_task.id
        db.commit()

        log.info(f"Requirement finalized: session={session_id}, task={task.id}")

        return {
            "session_id": session_id,
            "task_id": task.id,
            "task_name": task.task_name,
            "requirement_task_id": req_task.id,
            "redirect": f"/requirement/to-task/{task.id}",
        }

    # ================================================================
    # 查询
    # ================================================================

    def get_full_session(self, db: Session, session_id: int, user_id: int) -> Optional[Dict]:
        """获取完整会话信息（含文件、分析、评审、摘要、问题）"""
        session = self.get_session(db, session_id, user_id)
        if not session:
            return None

        files = self.get_files(db, session_id)
        context = self.get_context(db, session_id)
        analyses = db.query(RequirementAnalysis).filter(
            RequirementAnalysis.session_id == session_id,
        ).order_by(RequirementAnalysis.created_at).all()
        reviews = db.query(RequirementReview).filter(
            RequirementReview.session_id == session_id,
        ).order_by(RequirementReview.review_round).all()
        summary = db.query(RequirementSummary).filter(
            RequirementSummary.session_id == session_id,
        ).first()
        questions = db.query(RequirementQuestion).filter(
            RequirementQuestion.session_id == session_id,
        ).order_by(RequirementQuestion.created_at).all()

        return {
            "session": self._session_to_dict(session),
            "files": [self._file_to_dict(f) for f in files],
            "context": self._context_to_dict(context) if context else None,
            "analyses": [self._analysis_to_dict(a) for a in analyses],
            "reviews": [self._review_to_dict(r) for r in reviews],
            "summary": self._summary_to_dict(summary) if summary else None,
            "questions": [self._question_to_dict(q) for q in questions],
            "steps": json.loads(session.steps_json) if session.steps_json else [],
        }

    # ================================================================
    # 工具方法
    # ================================================================

    def _agent_display_name(self, agent_name: str) -> str:
        names = {
            "image_agent": "图片解析Agent",
            "document_agent": "文档解析Agent",
            "video_agent": "视频解析Agent",
            "schema_agent": "Schema解析Agent",
            "requirement_agent": "需求解析Agent",
            "url_agent": "URL页面分析Agent",
            "merge_agent": "需求整合Agent",
            "review_agent": "AI评审Agent",
        }
        return names.get(agent_name, agent_name)

    def _build_input_summary(self, agent_name: str, files: List, text: str, context) -> str:
        parts = []
        if files:
            parts.append(f"Files: {', '.join(f.file_name for f in files)}")
        if text:
            parts.append(f"Text: {text[:200]}")
        if context and context.system_name:
            parts.append(f"System: {context.system_name}")
        return " | ".join(parts) if parts else "No input"

    def _save_steps(self, db: Session, session: RequirementSession, steps: List):
        """保存步骤到数据库"""
        session.steps_json = json.dumps(steps, ensure_ascii=False, default=str)
        db.commit()

    def _sse(self, event: str, data: Any) -> str:
        """构造SSE事件"""
        return json.dumps({
            "event": event,
            "data": data if isinstance(data, (dict, list, str, int, float, bool, type(None))) else str(data),
            "timestamp": datetime.now().isoformat(),
        }, ensure_ascii=False, default=str)

    def _session_to_dict(self, s: RequirementSession) -> dict:
        return {
            "id": s.id,
            "title": s.title,
            "status": s.status,
            "current_step": s.current_step,
            "input_text": s.input_text,
            "input_urls": s.input_urls,
            "additional_context": s.additional_context,
            "task_id": s.task_id,
            "final_requirement": s.final_requirement,
            "finalized": s.finalized,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }

    def _file_to_dict(self, f: RequirementFile) -> dict:
        return {
            "id": f.id,
            "file_name": f.file_name,
            "file_path": f.file_path,
            "file_type": f.file_type,
            "category": f.category,
            "file_ext": f.file_ext,
            "file_size": f.file_size,
            "mime_type": f.mime_type,
            "parse_status": f.parse_status,
            "sort_order": f.sort_order,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        }

    def _context_to_dict(self, c: RequirementContext) -> dict:
        cred = None
        if c.credentials:
            try:
                cred = json.loads(c.credentials)
            except Exception:
                cred = {"raw": c.credentials}
        return {
            "system_name": c.system_name,
            "business_background": c.business_background,
            "test_scope": c.test_scope,
            "credentials": cred,
            "notes": c.notes,
            "special_requirements": c.special_requirements,
        }

    def _analysis_to_dict(self, a: RequirementAnalysis) -> dict:
        return {
            "id": a.id,
            "agent_name": a.agent_name,
            "agent_display_name": a.agent_display_name,
            "intent_type": a.intent_type,
            "status": a.status,
            "duration": a.duration,
            "input_summary": a.input_summary,
            "output": json.loads(a.output_json) if a.output_json else None,
            "error_message": a.error_message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }

    def _review_to_dict(self, r: RequirementReview) -> dict:
        return {
            "id": r.id,
            "review_round": r.review_round,
            "status": r.status,
            "completeness_score": r.completeness_score,
            "missing_items": json.loads(r.missing_items) if r.missing_items else [],
            "conflicts": json.loads(r.conflicts) if r.conflicts else [],
            "suggestions": json.loads(r.suggestions) if r.suggestions else [],
            "review_summary": r.review_summary,
            "needs_user_input": r.needs_user_input,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }

    def _summary_to_dict(self, s: RequirementSummary) -> dict:
        return {
            "requirement_text": s.requirement_text,
            "page_description": json.loads(s.page_description) if s.page_description else {},
            "page_elements": json.loads(s.page_elements) if s.page_elements else [],
            "business_flows": json.loads(s.business_flows) if s.business_flows else [],
            "test_goals": json.loads(s.test_goals) if s.test_goals else [],
            "risk_points": json.loads(s.risk_points) if s.risk_points else [],
            "recommended_test_types": json.loads(s.recommended_test_types) if s.recommended_test_types else [],
            "related_pages": json.loads(s.related_pages) if s.related_pages else [],
            "recommended_strategy": json.loads(s.recommended_strategy) if s.recommended_strategy else {},
            "confidence": s.confidence,
            "source_agents": json.loads(s.source_agents) if s.source_agents else [],
            "analysis_count": s.analysis_count,
        }

    def _question_to_dict(self, q: RequirementQuestion) -> dict:
        return {
            "id": q.id,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "category": q.category,
            "options": json.loads(q.options) if q.options else [],
            "default_answer": q.default_answer,
            "required": q.required,
            "answer": q.answer,
            "answered": q.answered,
            "answered_at": q.answered_at.isoformat() if q.answered_at else None,
        }


# 单例
_requirement_center_service: Optional[RequirementCenterService] = None


def get_requirement_center_service() -> RequirementCenterService:
    """获取 RequirementCenterService 单例"""
    global _requirement_center_service
    if _requirement_center_service is None:
        _requirement_center_service = RequirementCenterService()
    return _requirement_center_service
