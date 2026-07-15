"""
Case Pipeline - 三层用例编译流水线

从 compiler.py 拆分而来，包含：
  - run_pipeline（运行三层流水线）
  - _run_pipeline_async（异步执行三层流水线）
  - run_l3_compilation（L3独立执行）
  - compile_for_execution（L3延迟编译）
  - SSE 事件类型常量

三层定义：
  L1（需求理解）→ 结构化测试意图 → case_set.L1
  L2（用例编译）→ 执行级结构化用例 → case_set.L2 + CaseContent逐条入库
  L3（执行编译）→ Execution Ready格式 → case_set.L3（独立执行，可重试）
"""
import json
import time as _time
import asyncio
from typing import Any, Dict, List, Optional

from app.core.logger import log
from app.db.database import SessionLocal
from app.models.case_task import CaseTask, CaseTaskStatus
from app.models.case_content import CaseContent
from app.services.cache.pipeline_cache import get_pipeline_cache

from app.services.case.compiler_utils import (
    push_progress,
    check_rag_available,
    get_default_business_rules,
    limit_rag_result,
)
from app.services.case.case_set_store import CaseSetStore
from app.agents.factory import AgentRegistry


class CasePipeline:
    """三层用例编译流水线（分层存储版）"""

    # SSE进度事件类型
    EVT_PDF_PARSED = "pdf_parsed"
    EVT_RAG_READY = "rag_ready"
    EVT_L1_DONE = "l1_done"
    EVT_CASE_GENERATED = "case_generated"
    EVT_CASE_SAVED = "case_saved"
    EVT_L3_DONE = "l3_done"
    EVT_COMPLETED = "completed"
    EVT_ERROR = "error"

    @staticmethod
    def _emit_pipeline_event(topic: str, task_id: int, data: Any = None) -> None:
        """通过 MessageBus 发布 Pipeline 事件（事件驱动模式）

        Args:
            topic: 事件主题（如 "case.generated"）
            task_id: 关联的任务ID
            data: 事件数据
        """
        try:
            from app.agent.core.message_bus import MessageBus
            bus = MessageBus()
            bus.publish(
                topic=topic,
                source="case_pipeline",
                data=data,
                task_id=task_id,
                status="completed",
            )
        except Exception as e:
            log.debug(f"Pipeline | emit event failed: {topic} - {e}")

    @staticmethod
    def register_pipeline_events() -> None:
        """注册 Pipeline 事件监听器（应用启动时调用）

        使 Pipeline 能够响应 Agent 发出的事件：
        - requirement.parsed → 记录需求解析完成
        - rag.retrieved → 记录RAG检索完成
        - case.generated → 触发用例保存
        - case.reviewed → 触发用例发布
        """
        try:
            from app.agent.core.event_router import register_event_listener

            def _on_requirement_parsed(msg):
                log.info(
                    f"Pipeline | EVENT | requirement.parsed | "
                    f"task_id={msg.task_id} | source={msg.source}"
                )

            def _on_rag_retrieved(msg):
                log.info(
                    f"Pipeline | EVENT | rag.retrieved | "
                    f"task_id={msg.task_id} | source={msg.source}"
                )

            def _on_case_generated(msg):
                log.info(
                    f"Pipeline | EVENT | case.generated | "
                    f"task_id={msg.task_id} | source={msg.source}"
                )

            register_event_listener("requirement.parsed", _on_requirement_parsed)
            register_event_listener("rag.retrieved", _on_rag_retrieved)
            register_event_listener("case.generated", _on_case_generated)
            log.info("Pipeline | 事件监听器注册完成")
        except Exception as e:
            log.warning(f"Pipeline | 事件监听器注册失败: {e}")

    # ===== Pipeline入口 =====

    @staticmethod
    async def run_pipeline(
        project_id: str,
        title: str = "",
        source_type: str = "text",
        raw_text: str = "",
        url: str = "",
        file_path: str = "",
        use_rag: bool = True,
        case_types: Optional[List[str]] = None,
        max_cases: int = 20,
        compile_level: str = "l2",
        framework: str = "pytest",
        base_url: str = "http://localhost:8080",
        user_id: Optional[int] = None,
        progress_queue: Optional[asyncio.Queue] = None,
    ) -> Dict[str, Any]:
        """运行三层流水线"""
        _start = _time.time()
        cache = get_pipeline_cache()

        # 创建 CaseTask
        db = SessionLocal()
        try:
            task = CaseTask(
                title=title or f"三层编译-{source_type}",
                source_type=source_type,
                source_file=file_path,
                source_url=url,
                raw_input=raw_text,
                status=CaseTaskStatus.WAITING,
                user_id=user_id,
                created_by=user_id,
            )
            # 初始化分层case_set
            task.case_set = json.dumps({
                "L1": {}, "L2": {}, "L3": {},
                "state": "init",
                "config": {
                    "compile_level": compile_level,
                    "base_url": base_url,
                    "framework": framework,
                    "max_cases": max_cases,
                },
            }, ensure_ascii=False)
            db.add(task)
            db.commit()
            db.refresh(task)
            task_id = task.id
        finally:
            db.close()

        # 执行pipeline
        try:
            await CasePipeline._run_pipeline_async(
                task_id=task_id,
                project_id=project_id,
                source_type=source_type,
                raw_text=raw_text,
                url=url,
                file_path=file_path,
                use_rag=use_rag,
                case_types=case_types,
                max_cases=max_cases,
                compile_level=compile_level,
                framework=framework,
                base_url=base_url,
                user_id=user_id,
                progress_queue=progress_queue,
                cache=cache,
            )
        except Exception as e:
            log.error(f"CasePipeline | Pipeline执行异常: {e}")

        # 查询最终结果
        db = SessionLocal()
        try:
            task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
            case_set = CaseSetStore.read_case_set(db, task_id)
            state = case_set.get("state", "init")
            config = case_set.get("config", {})

            result = {
                "task_id": task_id,
                "status": task.status if task else "failed",
                "state": state,
                "compile_level": config.get("compile_level", compile_level),
                "elapsed_ms": int((_time.time() - _start) * 1000),
            }

            if task and task.error_message:
                result["error"] = task.error_message

            # L1结果（始终返回）
            l1 = case_set.get("L1", {})
            result["features"] = l1.get("features", [])
            result["entities"] = l1.get("entities", [])
            result["api_candidates"] = l1.get("api_candidates", [])
            result["test_strategy"] = l1.get("test_strategy", {})

            # L2结果
            if state in ("l2_done", "l3_done"):
                result["cases"] = CaseSetStore.load_cases_from_db(db, task_id)
                l2 = case_set.get("L2", {})
                result["case_count"] = l2.get("content_count", len(result["cases"]))

            # L3结果
            if state == "l3_done":
                l3 = case_set.get("L3", {})
                result["l3"] = l3

            return result
        finally:
            db.close()

    # ===== L3独立执行 =====

    @staticmethod
    async def run_l3_compilation(
        task_id: int,
        base_url: str = "http://localhost:8080",
        env: str = "test",
        user_id: Optional[int] = None,
        progress_queue: Optional[asyncio.Queue] = None,
    ) -> Dict[str, Any]:
        """
        L3独立执行：从L2结果编译为Execution Ready格式

        不依赖L2回写，独立worker执行，失败可重试
        """
        db = SessionLocal()
        try:
            task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
            if not task:
                return {"error": f"任务不存在: {task_id}"}

            case_set = CaseSetStore.read_case_set(db, task_id)
            state = case_set.get("state", "")

            if state not in ("l2_done", "l3_done"):
                return {"error": f"L3需要L2先完成，当前状态: {state}"}

            task.status = "l3_compiling"
            db.commit()
            push_progress(progress_queue, "l3", "L3执行编译中...")

            # 从CaseContent读取L2结果
            contents = db.query(CaseContent).filter(
                CaseContent.case_task_id == task_id,
                CaseContent.is_deleted == False,
            ).all()

            l3_results = []
            compiled_ids = []

            for c in contents:
                steps = json.loads(c.steps) if c.steps else []
                first_step = steps[0] if steps else {}

                if isinstance(first_step, dict):
                    action = first_step.get("action", "")
                    if action.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        request_obj = {
                            "method": action.upper(),
                            "url": first_step.get("url", ""),
                            "headers": first_step.get("headers", {}),
                            "body": first_step.get("body", {}),
                            "timeout": first_step.get("timeout", 5000),
                        }

                        # URL补全
                        if request_obj["url"] and not request_obj["url"].startswith("http"):
                            request_obj["url"] = base_url.rstrip("/") + "/" + request_obj["url"].lstrip("/")

                        # Pre-steps URL补全
                        pre_steps = json.loads(c.precondition) if c.precondition else []
                        for ps in pre_steps:
                            ps_req = ps.get("request", {})
                            ps_url = ps_req.get("url", "")
                            if ps_url and not ps_url.startswith("http"):
                                ps_req["url"] = base_url.rstrip("/") + "/" + ps_url.lstrip("/")

                        assertions = json.loads(c.expected) if c.expected else []
                        if isinstance(assertions, dict):
                            assertions = [assertions]

                        l3_case = {
                            "execution_case_id": f"EX_{c.id}",
                            "content_id": c.id,
                            "title": c.title,
                            "request": request_obj,
                            "pre_steps": pre_steps,
                            "assertions": assertions,
                            "variables": {},
                            "runtime": {"retry": 0, "env": env},
                        }
                        l3_results.append(l3_case)
                        compiled_ids.append(c.id)

            # merge写入L3层（不覆盖L1/L2）
            CaseSetStore.merge_case_set(db, task_id, "L3", {
                "case_count": len(l3_results),
                "compiled_ids": compiled_ids,
                "base_url": base_url,
                "env": env,
            }, state="l3_done")

            task.status = CaseTaskStatus.COMPLETED
            db.commit()

            push_progress(progress_queue, CasePipeline.EVT_L3_DONE, {
                "case_count": len(l3_results),
            })
            CasePipeline._emit_pipeline_event("case.compiled", task_id, {"count": len(l3_results)})
            push_progress(progress_queue, CasePipeline.EVT_COMPLETED, {
                "level": "l3",
                "case_count": len(l3_results),
            })
            CasePipeline._emit_pipeline_event("pipeline.completed", task_id, {"level": "l3"})

            log.info(f"CasePipeline | L3独立编译完成 | task_id={task_id}, compiled={len(l3_results)}条")
            return {"task_id": task_id, "l3_count": len(l3_results), "state": "l3_done"}

        except Exception as e:
            log.error(f"CasePipeline | L3编译失败: {e}")
            push_progress(progress_queue, CasePipeline.EVT_ERROR, str(e))
            try:
                task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
                if task:
                    task.status = CaseTaskStatus.FAILED
                    task.error_message = str(e)
                    db.commit()
            except Exception:
                pass
            return {"error": str(e)}
        finally:
            db.close()

    # ===== Pipeline核心 =====

    @staticmethod
    async def _run_pipeline_async(
        task_id: int,
        project_id: str,
        source_type: str,
        raw_text: str,
        url: str,
        file_path: str,
        use_rag: bool,
        case_types: List[str],
        max_cases: int,
        compile_level: str,
        framework: str,
        base_url: str,
        user_id: Optional[int],
        progress_queue: Optional[asyncio.Queue],
        cache: "PipelineCache",
    ):
        """异步执行三层流水线（分层存储版）"""
        db = SessionLocal()
        try:
            task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
            if not task:
                return

            # === Phase 0: 解析输入（带缓存） ===
            task.status = CaseTaskStatus.PARSING
            CaseSetStore.merge_case_set(db, task_id, "config", {
                "compile_level": compile_level,
                "base_url": base_url,
                "framework": framework,
                "max_cases": max_cases,
                "case_types": case_types,
            })
            db.commit()
            push_progress(progress_queue, "parsing", "解析输入中...")

            requirement_context = None
            structured_data = {}
            if file_path:
                cached_content = cache.get_parsed_content(file_path)
                if cached_content:
                    requirement_context = cached_content
                    log.info(f"CasePipeline | PDF解析命中缓存 | file={file_path}")
                    push_progress(progress_queue, CasePipeline.EVT_PDF_PARSED, "PDF解析（缓存命中）")
                else:
                    from app.agent.case.agent_selector import AgentSelector
                    selector = AgentSelector()
                    parse_kwargs = {"file_path": file_path, "url": url, "raw_text": raw_text}
                    parse_result = await asyncio.to_thread(
                        selector.parse, source_type=source_type, task_id=task_id, **parse_kwargs
                    )
                    requirement_context = parse_result.get("requirement_context", raw_text)
                    structured_data = parse_result.get("structured_data", {})
                    cache.set_parsed_content(file_path, requirement_context)
                    push_progress(progress_queue, CasePipeline.EVT_PDF_PARSED, "PDF解析完成")
            else:
                from app.agent.case.agent_selector import AgentSelector
                selector = AgentSelector()
                parse_kwargs = {"file_path": file_path, "url": url, "raw_text": raw_text}
                parse_result = await asyncio.to_thread(
                    selector.parse, source_type=source_type, task_id=task_id, **parse_kwargs
                )
                requirement_context = parse_result.get("requirement_context", raw_text)
                structured_data = parse_result.get("structured_data", {})

            if not requirement_context:
                requirement_context = raw_text
            task.requirement_context = requirement_context
            db.commit()

            # === RAG预检索 ===
            rag_context = None
            if use_rag:
                cached_rag = cache.get_rag_context(requirement_context, project_id)
                if cached_rag:
                    rag_context = cached_rag
                    log.info("CasePipeline | RAG命中缓存")
                    push_progress(progress_queue, CasePipeline.EVT_RAG_READY, "RAG检索（缓存命中）")
                else:
                    rag_available = check_rag_available()
                    if rag_available:
                        try:
                            from app.agent.case.rag_context_agent import RAGContextAgent
                            rag_agent = RAGContextAgent()
                            rag_context = await asyncio.to_thread(
                                rag_agent.retrieve_for_l1,
                                requirement_context=requirement_context,
                                source_type=source_type,
                                project_id=project_id,
                            )
                            rag_context = limit_rag_result(rag_context)
                            cache.set_rag_context(requirement_context, project_id, rag_context)
                        except Exception as e:
                            log.warning(f"RAG检索失败: {e}")

                    if not rag_context or rag_context.get("total", 0) == 0:
                        log.warning("RAG上下文为空，注入默认业务规则")
                        rag_context = get_default_business_rules()

                    push_progress(progress_queue, CasePipeline.EVT_RAG_READY, "RAG检索完成")

            # === Phase 1: L1 测试设计 ===
            task.status = "l1_designing"
            db.commit()
            push_progress(progress_queue, "l1", "L1需求理解中...")

            from app.agent.case.requirement_understanding_agent import RequirementUnderstandingAgent
            l1_agent = RequirementUnderstandingAgent()
            l1_result = await asyncio.to_thread(
                l1_agent.understand,
                requirement_context=requirement_context,
                source_type=source_type,
                structured_data=structured_data,
                rag_context=rag_context,
            )
            features = l1_result.get("features", [])
            entities = l1_result.get("entities", [])
            api_candidates = l1_result.get("api_candidates", [])
            test_strategy = l1_result.get("test_strategy", {})

            cache.set_l1_result(task_id, l1_result)

            # L1结果写入 case_set.L1（merge，不覆盖L2/L3）
            CaseSetStore.merge_case_set(db, task_id, "L1", {
                "features": features,
                "entities": entities,
                "api_candidates": api_candidates,
                "test_strategy": test_strategy,
                "feature_count": len(features),
                "feature_titles": [f.get("name", f.get("title", "")) for f in features],
            }, state="l1_done")

            push_progress(progress_queue, CasePipeline.EVT_L1_DONE, {
                "feature_count": len(features),
                "entities": entities,
                "api_candidates": api_candidates,
            })

            if compile_level == "l1":
                task.status = CaseTaskStatus.COMPLETED
                db.commit()
                push_progress(progress_queue, CasePipeline.EVT_COMPLETED, {"level": "l1", "state": "l1_done"})
                return

            # === Phase 2: L2 逐条流式编译 ===
            task.status = "l2_compiling"
            db.commit()
            push_progress(progress_queue, "l2", {
                "message": "L2用例编译中...",
                "feature_count": len(features),
            })

            requirement_summary = requirement_context[:500] if requirement_context else ""

            compiler = AgentRegistry.create("case_agent")

            saved_content_ids = []
            case_idx = 0

            def _stream_generate():
                return compiler.compile_stream(
                    features=features,
                    rag_context=rag_context,
                    requirement_context=requirement_summary,
                )

            gen = await asyncio.to_thread(_stream_generate)

            # 安全的next包装：StopIteration不能在asyncio Future中传播
            _SENTINEL = object()

            def _next_or_sentinel(g):
                try:
                    return next(g)
                except StopIteration:
                    return _SENTINEL

            while True:
                case_data = await asyncio.to_thread(_next_or_sentinel, gen)
                if case_data is _SENTINEL:
                    break

                case_idx += 1

                content_id = await asyncio.to_thread(
                    CaseSetStore.save_single_case,
                    db, task_id, case_data, user_id, base_url,
                )

                if content_id:
                    saved_content_ids.append(content_id)
                    db.commit()

                push_progress(progress_queue, CasePipeline.EVT_CASE_GENERATED, {
                    "index": case_idx,
                    "content_id": content_id,
                    "case_id": case_data.get("case_id", ""),
                    "title": case_data.get("title", ""),
                    "method": case_data.get("method", ""),
                    "url": case_data.get("url", ""),
                    "priority": case_data.get("priority", "P1"),
                    "status": "draft",
                })

            log.info(f"CasePipeline | L2流式编译完成 | task_id={task_id}, saved={len(saved_content_ids)}条")

            # L2结果写入 case_set.L2（merge，不覆盖L1/L3）
            CaseSetStore.merge_case_set(db, task_id, "L2", {
                "content_count": len(saved_content_ids),
                "saved_content_ids": saved_content_ids,
                "draft_count": len(saved_content_ids),
                "published_count": 0,
            }, state="l2_done")

            task.status = CaseTaskStatus.COMPLETED
            db.commit()

            push_progress(progress_queue, CasePipeline.EVT_COMPLETED, {
                "level": "l2",
                "state": "l2_done",
                "case_count": len(saved_content_ids),
            })
            CasePipeline._emit_pipeline_event("case.generated", task_id, {"count": len(saved_content_ids)})
            CasePipeline._emit_pipeline_event("pipeline.completed", task_id, {"level": "l2"})

            log.info(f"CasePipeline | Pipeline完成 | task_id={task_id}, state=l2_done, saved={len(saved_content_ids)}条")

        except Exception as e:
            log.error(f"CasePipeline | Pipeline失败: {e}")
            push_progress(progress_queue, CasePipeline.EVT_ERROR, str(e))
            CasePipeline._emit_pipeline_event("pipeline.failed", task_id, {"error": str(e)})
            try:
                task = db.query(CaseTask).filter(CaseTask.id == task_id).first()
                if task:
                    task.status = CaseTaskStatus.FAILED
                    task.error_message = str(e)
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()

    @staticmethod
    async def compile_for_execution(
        case_id: int,
        base_url: str = "http://localhost:8080",
        env: str = "test",
    ) -> Dict[str, Any]:
        """L3延迟编译：仅在execution时触发"""
        from app.models.api_case import ApiCase
        db = SessionLocal()
        try:
            case = db.query(ApiCase).filter(ApiCase.id == case_id, ApiCase.is_deleted == False).first()
            if not case:
                return {"error": f"用例不存在: {case_id}"}

            if case.method:
                steps = json.loads(case.steps) if case.steps else []
                first_step = steps[0] if steps else {}
                request_obj = {
                    "method": case.method,
                    "url": case.url or "",
                    "headers": first_step.get("headers", {}),
                    "body": first_step.get("body", {}),
                    "timeout": first_step.get("timeout", 5000),
                }

                if request_obj["url"] and not request_obj["url"].startswith("http"):
                    request_obj["url"] = base_url.rstrip("/") + "/" + request_obj["url"].lstrip("/")

                pre_steps = json.loads(case.pre_steps) if case.pre_steps else []
                for ps in pre_steps:
                    ps_req = ps.get("request", {})
                    ps_url = ps_req.get("url", "")
                    if ps_url and not ps_url.startswith("http"):
                        ps_req["url"] = base_url.rstrip("/") + "/" + ps_url.lstrip("/")

                return {
                    "execution_case_id": f"EX_{case.case_id or case.id}",
                    "title": case.title,
                    "case_id": case.case_id or f"C{case.id}",
                    "request": request_obj,
                    "pre_steps": pre_steps,
                    "assertions": json.loads(case.assertions) if case.assertions else [],
                    "variables": json.loads(case.variables) if case.variables else {},
                    "runtime": {"retry": 0, "env": env},
                }
            else:
                steps = json.loads(case.steps) if case.steps else []
                from app.agent.case.test_normalization_agent import TestNormalizationAgent
                normalizer = TestNormalizationAgent()
                case_dict = {
                    "title": case.title,
                    "case_id": case.case_id or f"C{case.id}",
                    "steps": steps,
                    "assertions": json.loads(case.assertions) if case.assertions else [],
                    "priority": case.priority,
                    "tags": case.tags.split(",") if case.tags else [],
                }
                result = normalizer.normalize([case_dict], base_url=base_url, env=env)
                compiled = result.get("cases", [])
                return compiled[0] if compiled else {"error": "编译失败"}

        finally:
            db.close()
