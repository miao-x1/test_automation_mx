"""
CaseGenerateService - RAG 增强用例生成服务

流程：requirement → knowledge.retrieve() → CaseAgent.generate_rag_cases

职责：
1. 解析需求为 RequirementContext
2. 从知识库检索相关内容
3. 调用 CaseAgent 生成用例
4. 保存结果到数据库
"""
import json
import time as _time
import asyncio
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.case_task import CaseTask, CaseTaskStatus
from app.models.case_content import CaseContent
from app.models.case_generation import CaseGeneration, CaseGenerationStatus
from app.agents.factory import AgentRegistry


class CaseGenerateService:
    """RAG 增强用例生成服务"""

    @staticmethod
    async def generate(
        project_id: str,
        title: str = "",
        source_type: str = "text",
        raw_text: str = "",
        url: str = "",
        file_path: str = "",
        knowledge_ids: Optional[List[int]] = None,
        use_rag: bool = True,
        case_types: Optional[List[str]] = None,
        max_cases: int = 20,
    ) -> Dict[str, Any]:
        """
        RAG 增强的用例生成

        流程：
        1. 解析输入 → RequirementContext
        2. RAG 检索 → RetrievedContext
        3. CaseAgent.generate_rag_cases 生成用例
        4. 保存到数据库

        Args:
            project_id: 项目ID
            title: 任务标题
            source_type: 输入类型
            raw_text: 原始文本
            url: URL
            file_path: 文件路径
            knowledge_ids: 指定参考的知识ID
            use_rag: 是否启用 RAG
            case_types: 用例类型列表
            max_cases: 最大用例数

        Returns:
            { task_id, generation_id, case_count, status }
        """
        _start = _time.time()

        if not case_types:
            case_types = ["functional", "boundary", "error"]

        # Step 1: 创建 CaseTask
        db = SessionLocal()
        try:
            task = CaseTask(
                title=title or f"用例生成-{source_type}",
                source_type=source_type,
                source_file=file_path,
                source_url=url,
                raw_input=raw_text,
                status=CaseTaskStatus.WAITING,
            )
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id
        finally:
            db.close()

        # Step 2: 创建 CaseGeneration
        db = SessionLocal()
        try:
            generation = CaseGeneration(
                project_id=project_id,
                case_task_id=task_id,
                status=CaseGenerationStatus.PENDING,
                config={
                    "source_type": source_type,
                    "use_rag": use_rag,
                    "case_types": case_types,
                    "max_cases": max_cases,
                    "knowledge_ids": knowledge_ids or [],
                },
            )
            db.add(generation)
            db.commit()
            db.refresh(generation)
            generation_id = generation.id
        finally:
            db.close()

        # Step 3: 异步执行 Pipeline
        asyncio.create_task(
            CaseGenerateService._run_pipeline(
                generation_id=generation_id,
                task_id=task_id,
                project_id=project_id,
                source_type=source_type,
                raw_text=raw_text,
                url=url,
                file_path=file_path,
                knowledge_ids=knowledge_ids,
                use_rag=use_rag,
                case_types=case_types,
                max_cases=max_cases,
            )
        )

        return {
            "task_id": task_id,
            "generation_id": generation_id,
            "status": "pending",
            "message": "任务已创建，正在后台生成",
        }

    @staticmethod
    async def _run_pipeline(
        generation_id: int,
        task_id: int,
        project_id: str,
        source_type: str,
        raw_text: str,
        url: str,
        file_path: str,
        knowledge_ids: Optional[List[int]],
        use_rag: bool,
        case_types: List[str],
        max_cases: int,
    ):
        """执行用例生成 Pipeline"""
        db = SessionLocal()
        try:
            generation = db.query(CaseGeneration).filter(CaseGeneration.id == generation_id).first()
            task = db.query(CaseTask).filter(CaseTask.id == task_id).first()

            if not generation or not task:
                return

            # === Phase 1: 解析 ===
            generation.status = CaseGenerationStatus.PARSING
            task.status = CaseTaskStatus.PARSING
            db.commit()

            from app.agent.case.agent_selector import AgentSelector
            selector = AgentSelector()
            parse_kwargs = {"file_path": file_path, "url": url, "raw_text": raw_text}
            parse_result = await asyncio.to_thread(
                selector.parse, source_type=source_type, task_id=task_id, **parse_kwargs
            )

            requirement_context = {
                "project_id": project_id,
                "task_id": str(task_id),
                "source_type": source_type,
                "raw_text": parse_result.get("requirement_context", raw_text),
                "structured_data": parse_result.get("structured_data", {}),
                "business_goal": "",
                "summary": parse_result.get("requirement_context", "")[:200],
            }
            task.requirement_context = requirement_context.get("raw_text", "")
            generation.requirement_context = requirement_context
            db.commit()

            # === Phase 2: RAG 检索 ===
            retrieved_context = None
            if use_rag and settings.is_r2r_enabled:
                generation.status = CaseGenerationStatus.RAG_QUERYING
                db.commit()

                retrieved_context = await asyncio.to_thread(
                    CaseGenerateService._retrieve,
                    project_id=project_id,
                    requirement_context=requirement_context,
                    knowledge_ids=knowledge_ids,
                )
                generation.retrieved_context = retrieved_context
                if retrieved_context and retrieved_context.get("all_chunks"):
                    generation.retrieved_chunk_ids = [c.get("chunk_id", 0) for c in retrieved_context["all_chunks"]]
                db.commit()
            elif use_rag:
                # 本地模式：尝试使用内置 Milvus
                try:
                    from app.agent.case.retriever_agent import RetrieverAgent
                    retriever = RetrieverAgent()
                    query_text = requirement_context.get("raw_text", "")[:500]
                    if query_text:
                        retrieved_context = await asyncio.to_thread(
                            retriever.retrieve,
                            project_id=project_id,
                            query_text=query_text,
                            top_k=10,
                        )
                        generation.retrieved_context = retrieved_context
                except Exception as e:
                    log.warning(f"本地 RAG 检索失败: {e}")

            # === Phase 3: 生成用例 ===
            generation.status = CaseGenerationStatus.GENERATING
            task.status = CaseTaskStatus.GENERATING
            db.commit()

            generator = AgentRegistry.create("case_agent")
            gen_result = await asyncio.to_thread(
                generator.generate_rag_cases,
                requirement_context=requirement_context,
                retrieved_context=retrieved_context,
                case_types=case_types,
                max_cases=max_cases,
            )

            cases = gen_result.get("cases", [])

            # === Phase 4: 保存用例 ===
            for case_data in cases:
                steps_str = case_data.get("steps_text", "")
                if not steps_str and case_data.get("steps"):
                    steps_list = case_data["steps"]
                    if isinstance(steps_list, list):
                        steps_str = "\n".join(
                            f"{i+1}. {s.get('action', s) if isinstance(s, dict) else s}"
                            for i, s in enumerate(steps_list)
                        )

                case_content = CaseContent(
                    case_task_id=task_id,
                    title=case_data.get("title", "未命名用例"),
                    case_type=case_data.get("case_type", "functional"),
                    precondition=case_data.get("precondition", ""),
                    steps=steps_str,
                    expected=case_data.get("expected", ""),
                    priority=case_data.get("priority", "medium"),
                    tags=",".join(case_data.get("tags", [])),
                    version=1,
                )
                db.add(case_content)

            # 更新统计
            task.case_set = json.dumps({"total": len(cases)}, ensure_ascii=False)
            task.status = CaseTaskStatus.COMPLETED
            generation.case_set = gen_result
            generation.case_count = len(cases)
            generation.status = CaseGenerationStatus.COMPLETED
            generation.latency_ms = int((_time.time() - _start) * 1000)
            db.commit()

            log.info(f"CaseGenerateService | Pipeline完成 | task_id={task_id}, cases={len(cases)}")

        except Exception as e:
            log.error(f"CaseGenerateService | Pipeline失败: {e}")
            try:
                generation = db.query(CaseGeneration).filter(CaseGeneration.id == generation_id).first()
                task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
                if generation:
                    generation.status = CaseGenerationStatus.FAILED
                    generation.error_message = str(e)
                if task:
                    task.status = CaseTaskStatus.FAILED
                    task.error_message = str(e)
                db.commit()
            except Exception:
                pass
        finally:
            db.close()

    @staticmethod
    def _retrieve(
        project_id: str,
        requirement_context: Dict[str, Any],
        knowledge_ids: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """从知识库检索"""
        try:
            from app.services.context_router import get_context_router, ContextType

            # 构建查询
            query_parts = []
            if requirement_context.get("business_goal"):
                query_parts.append(requirement_context["business_goal"])
            if requirement_context.get("summary"):
                query_parts.append(requirement_context["summary"])
            if requirement_context.get("raw_text"):
                query_parts.append(requirement_context["raw_text"][:500])

            # 添加结构化信息
            for api in requirement_context.get("apis", [])[:5]:
                query_parts.append(f"API: {api.get('method', '')} {api.get('path', '')}")
            for flow in requirement_context.get("flows", [])[:3]:
                query_parts.append(f"流程: {flow.get('flow_name', '')}")
            for c in requirement_context.get("constraints", [])[:3]:
                query_parts.append(f"约束: {c.get('description', '')}")

            query_text = "\n".join(query_parts)
            if not query_text.strip():
                return None

            # 通过 ContextRouter 检索（路由到 Milvus）
            router = get_context_router()
            result = router.retrieve_sync(
                query=query_text,
                context_type=ContextType.DOCUMENT,
                top_k=10,
                project_id=project_id,
            )

            log.info(f"CaseGenerateService | RAG检索 | results={len(result.get('results', []))}")
            return result

        except Exception as e:
            log.warning(f"CaseGenerateService | RAG检索失败（降级为无RAG生成）: {e}")
            return None

    @staticmethod
    def get_generation(generation_id: int) -> Dict[str, Any]:
        """获取生成任务详情"""
        db = SessionLocal()
        try:
            gen = db.query(CaseGeneration).filter(CaseGeneration.id == generation_id).first()
            if not gen:
                return {"error": "不存在"}

            case_count = db.query(CaseContent).filter(CaseContent.case_task_id == gen.case_task_id).count()

            return {
                "id": gen.id,
                "project_id": gen.project_id,
                "case_task_id": gen.case_task_id,
                "version": gen.version,
                "status": gen.status,
                "case_count": case_count,
                "error_message": gen.error_message,
                "config": gen.config,
                "latency_ms": gen.latency_ms,
                "created_at": str(gen.created_at) if gen.created_at else None,
                "completed_at": str(gen.completed_at) if gen.completed_at else None,
            }
        finally:
            db.close()
