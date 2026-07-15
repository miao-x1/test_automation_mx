"""
RequirementFlowService - 需求驱动测试流程编排服务

统一编排：
RequirementAgent → ScriptReuseAgent → RAGAgent → RelationAgent → GraphAgent → CaseAgent → 脚本生成 → ExecutionAgent

新流程：
需求 → 多模态解析(InputRouter+FusionAgent) → 需求解析 → 脚本复用检查 → RAG召回 → 页面关联 → Graph推理 → 用例生成 → 脚本生成 → 执行 → 报告

SSE实时输出每个阶段的进度
"""
import json
import queue
import threading
import time as _time
from typing import AsyncGenerator, Dict, Any, Optional
from app.core.logger import log
from app.core.config import settings
from app.db.database import SessionLocal
from app.models.requirement_task import RequirementTask, RequirementStatus
from app.models.task import Task, TaskStatus
from app.models.script import Script
from app.models.ui_element import UIElement
from app.models.page_relation import PageRelation
from app.models.execution_record import ExecutionRecord, ExecutionStatus
from app.agents.factory import AgentRegistry


class RequirementFlowService:
    """需求驱动测试流程编排服务"""

    @staticmethod
    def _create_requirement_task(db, requirement: str) -> RequirementTask:
        """创建需求任务记录"""
        task = RequirementTask(
            requirement=requirement,
            status=RequirementStatus.PENDING,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    def _update_requirement_task(db, task_id: int, **kwargs):
        """更新需求任务"""
        try:
            task = db.query(RequirementTask).filter(RequirementTask.id == task_id).first()
            if task:
                for key, value in kwargs.items():
                    setattr(task, key, value)
                db.commit()
        except Exception as e:
            db.rollback()
            log.warning(f"更新需求任务失败(已rollback): task_id={task_id}, error={e}")

    @staticmethod
    def _create_task_for_requirement(db, requirement: str, page_url: str = "", user_id: int = None) -> Task:
        """为需求自动创建一个Task"""
        task = Task(
            task_name=f"[需求] {requirement[:50]}",
            status=TaskStatus.SUCCESS,
            input_mode="requirement",
            page_url=page_url or None,
            user_id=user_id,
            created_by=user_id,
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        return task

    @staticmethod
    async def generate(
        requirement: str,
        execute: bool = False,
        requirement_id: Optional[int] = None,
        feedback_context: Optional[str] = None,
        additional_info: Optional[str] = None,
        image_paths: Optional[list] = None,
        script_format: str = "playwright",
    ) -> AsyncGenerator[str, None]:
        """
        需求驱动生成测试脚本（RAG增强版）

        新流程：
        需求解析 → 脚本复用检查 → RAG召回 → Graph推理 → 用例生成 → 脚本生成 → (执行)

        Args:
            requirement: 自然语言需求
            execute: 是否执行脚本
            requirement_id: 已有的需求任务ID
            feedback_context: 反馈上下文（来自用户反馈，用于指导重新生成）
            additional_info: 用户附加信息（URL、备注等）
            image_paths: 上传的图片路径列表
            script_format: 脚本格式 playwright/yaml

        Yields:
            SSE格式的进度信息
        """
        db = SessionLocal()
        req_task = None
        _generate_start = _time.time()

        # [DEBUG] Service编排入口 - 全链路唯一主断点

        try:
            # [DEBUG] 进入函数
            log.info(f"[DEBUG] 开始：RequirementFlowService.generate | 输入：requirement={requirement[:80]}, execute={execute}, requirement_id={requirement_id}, feedback_context={'有' if feedback_context else '无'}")

            # 创建或复用需求任务记录
            if requirement_id:
                req_task = db.query(RequirementTask).filter(RequirementTask.id == requirement_id).first()
                if not req_task:
                    yield json.dumps({"step": "错误", "progress": 100, "message": f"需求任务 {requirement_id} 不存在"}, ensure_ascii=False)
                    return
                req_task.status = RequirementStatus.PENDING
                req_task.error_message = None
                req_task.rag_result = None
                req_task.script_source = None
                req_task.reuse_similarity = None
                db.commit()
            else:
                req_task = RequirementFlowService._create_requirement_task(db, requirement)
            req_id = req_task.id

            # 保存附加信息、图片路径和脚本格式
            update_fields = {}
            if additional_info:
                update_fields["additional_info"] = additional_info
            if image_paths:
                update_fields["image_paths"] = json.dumps(image_paths, ensure_ascii=False)
            if script_format:
                update_fields["script_format"] = script_format
            if update_fields:
                RequirementFlowService._update_requirement_task(db, req_id, **update_fields)

            log.info(f"[DEBUG] 需求任务已创建/复用 | req_id={req_id}")

            # ===== 阶段0.5: 统一类型识别 (TestTypeClassifierAgent) =====
            from app.agent.requirement.test_type_classifier_agent import TestTypeClassifierAgent
            classifier = TestTypeClassifierAgent()
            # 优先用同步规则分类（快速）
            type_result = classifier.classify_sync(
                text=requirement,
                urls=[additional_info] if additional_info else [],
            )
            detected_type = type_result.get("test_type", "web")
            detected_platform = type_result.get("platform", "browser")
            detected_framework = type_result.get("framework", "playwright")
            detected_confidence = type_result.get("confidence", 0.5)

            # 更新需求任务的task_type
            req_task = db.query(RequirementTask).filter(RequirementTask.id == req_id).first()
            if req_task:
                req_task.task_type = detected_type
                db.commit()

            yield json.dumps({
                "step": "类型识别完成",
                "progress": 4,
                "message": f"自动识别为{detected_type}测试，置信度{detected_confidence:.0%}",
                "data": {
                    "task_type": detected_type,
                    "platform": detected_platform,
                    "framework": detected_framework,
                    "confidence": detected_confidence,
                    "reason": type_result.get("reason", ""),
                    "scores": type_result.get("scores", {}),
                }
            }, ensure_ascii=False)

            log.info(f"TypeClassifier | type={detected_type}, confidence={type_result.confidence:.2f}, reason={type_result.reason}")

            # [DEBUG] SSE推送前
            log.info(f"[DEBUG] SSE推送 | step=需求解析开始 | progress=5")
            yield json.dumps({
                "step": "需求解析开始",
                "progress": 5,
                "message": f"正在解析需求: {requirement}",
                "data": {"requirement_id": req_id}
            }, ensure_ascii=False)

            # ===== 阶段1: RequirementAgent 需求解析 =====
            RequirementFlowService._update_requirement_task(db, req_id, status=RequirementStatus.ANALYZING)

            # [DEBUG] 调用LLM前 - RequirementAgent
            _req_agent_start = _time.time()
            log.info(f"[DEBUG] 开始：RequirementAgent | 输入：requirement={requirement[:80]}")

            result_holder = {"done": False, "error": None, "result": None}

            def run_requirement_agent():
                try:
                    agent = AgentRegistry.create("requirement_agent")
                    # 使用标准 Agent 接口 analyze()：
                    # 内部已完成 prompt 构建、LLM 调用、结果解析、URL 提取，
                    # 返回结构化结果（intent/summary/target_url/steps/
                    # business_flow/test_points/risk_points）
                    result = agent.analyze(requirement)

                    # analyze() 不返回 keywords 字段，补充以保证下游兼容
                    if "keywords" not in result:
                        result["keywords"] = result.get("steps", [])[:5]

                    result_holder["result"] = result
                except Exception as e:
                    log.error(f"RequirementAgent异常: {e}", exc_info=True)
                    result_holder["error"] = str(e)
                finally:
                    result_holder["done"] = True

            agent_thread = threading.Thread(target=run_requirement_agent, daemon=True)
            agent_thread.start()
            agent_thread.join(timeout=120)

            if result_holder["error"]:
                # RequirementAgent失败时降级：从需求文本直接提取基本信息
                _req_agent_elapsed = _time.time() - _req_agent_start
                log.warning(f"RequirementAgent失败，降级为简单解析: {result_holder['error']}")
                yield json.dumps({
                    "step": "需求解析降级",
                    "progress": 10,
                    "message": "需求解析失败，使用简单解析模式（降级）",
                }, ensure_ascii=False)
                req_result = {
                    "intent": "unknown_test",
                    "steps": [requirement],
                    "keywords": requirement.split()[:5],
                    "summary": requirement,
                    "target_url": "",
                }
            else:
                req_result = result_holder["result"]
            _req_agent_elapsed = _time.time() - _req_agent_start
            # [DEBUG] LLM返回后 - RequirementAgent
            log.info(f"[DEBUG] 结束：RequirementAgent | 输出：intent={req_result.get('intent')}, steps={len(req_result.get('steps', []))}, target_url={req_result.get('target_url', '')} | 耗时：{_req_agent_elapsed:.2f}s")
            if not req_result:
                # 降级：使用需求文本作为基础
                req_result = {
                    "intent": "unknown_test",
                    "steps": [requirement],
                    "keywords": requirement.split()[:5],
                    "summary": requirement,
                    "target_url": "",
                }

            intent = req_result.get("intent", "unknown_test")
            steps = req_result.get("steps", [])
            keywords = req_result.get("keywords", [])
            summary = req_result.get("summary", "")
            target_url = req_result.get("target_url", "")

            # 多级URL提取：确保不遗漏用户提供的真实URL
            if not target_url:
                import re
                url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
                # 1. 从附加信息中提取
                if additional_info:
                    url_match = re.search(url_pattern, additional_info)
                    if url_match:
                        target_url = url_match.group(0)
                        log.info(f"从附加信息中提取URL: {target_url}")
                # 2. 从需求文本中直接提取
                if not target_url:
                    url_match = re.search(url_pattern, requirement)
                    if url_match:
                        target_url = url_match.group(0)
                        log.info(f"从需求文本中提取URL: {target_url}")
                # 3. 从需求文本中匹配常见网站名称
                if not target_url:
                    site_map = {
                        '京东': 'https://www.jd.com', '淘宝': 'https://www.taobao.com',
                        '天猫': 'https://www.tmall.com', '百度': 'https://www.baidu.com',
                        '微信': 'https://weixin.qq.com', '微博': 'https://weibo.com',
                        '抖音': 'https://www.douyin.com', 'bilibili': 'https://www.bilibili.com',
                        'B站': 'https://www.bilibili.com', '知乎': 'https://www.zhihu.com',
                        'github': 'https://github.com', 'google': 'https://www.google.com',
                    }
                    for name, url in site_map.items():
                        if name.lower() in requirement.lower():
                            target_url = url
                            log.info(f"从需求文本匹配网站名称: {name} -> {url}")
                            break

            RequirementFlowService._update_requirement_task(db, req_id, intent=intent)

            # 流式填充：保存页面概述
            page_overview = f"意图: {intent}"
            if summary:
                page_overview += f"\n{summary}"
            if target_url:
                page_overview += f"\n目标URL: {target_url}"
            RequirementFlowService._update_requirement_task(db, req_id, page_overview=page_overview)

            yield json.dumps({
                "step": "需求解析完成",
                "progress": 15,
                "message": f"意图: {intent} | 步骤: {len(steps)}个 | 关键词: {', '.join(keywords[:5])}",
                "data": {"intent": intent, "steps": steps, "keywords": keywords, "summary": summary, "target_url": target_url}
            }, ensure_ascii=False)

            # ===== 阶段2: ScriptReuseAgent 脚本复用检查（基于解析后的结构化需求）=====
            yield json.dumps({
                "step": "脚本复用检查",
                "progress": 20,
                "message": "基于解析结果检查是否有可复用的历史脚本..."
            }, ensure_ascii=False)

            reuse_result_holder = {"done": False, "result": None}

            def run_script_reuse():
                try:
                    from app.services.reuse_service import ReuseService
                    # 使用解析后的intent和steps做精确检索
                    result = ReuseService.check_reuse(
                        requirement=requirement,
                        intent=req_result.get("intent", ""),
                        steps=req_result.get("steps", []),
                    )
                    reuse_result_holder["result"] = result
                except Exception as e:
                    log.warning(f"ScriptReuseAgent异常: {e}")
                    reuse_result_holder["result"] = {"reuse": False, "similarity": 0}
                finally:
                    reuse_result_holder["done"] = True

            reuse_thread = threading.Thread(target=run_script_reuse, daemon=True)
            reuse_thread.start()
            reuse_thread.join(timeout=30)

            reuse_result = reuse_result_holder["result"]

            # 如果命中脚本复用
            if reuse_result.get("reuse"):
                similarity = reuse_result.get("similarity", 0)
                script_content = reuse_result.get("script_content", "")
                reused_script_name = reuse_result.get("script_name", "")
                reused_task_id = reuse_result.get("task_id")

                yield json.dumps({
                    "step": "命中历史脚本",
                    "progress": 60,
                    "message": f"已复用历史脚本「{reused_script_name}」| 相似度: {similarity}",
                    "data": {
                        "reuse": True,
                        "similarity": similarity,
                        "script_name": reused_script_name,
                        "task_id": reused_task_id,
                    }
                }, ensure_ascii=False)

                # 创建关联的Task
                task = RequirementFlowService._create_task_for_requirement(db, requirement, target_url, user_id=req_task.user_id)

                # 保存脚本（标记为reused）
                script = Script(
                    task_id=task.id,
                    script_type="playwright",
                    script_content=script_content,
                    script_language="python",
                    script_source="reused",
                )
                db.add(script)

                # 更新被复用脚本的reuse_count
                if reused_task_id:
                    try:
                        reused_script = db.query(Script).filter(Script.task_id == reused_task_id).first()
                        if reused_script:
                            reused_script.reuse_count = (reused_script.reuse_count or 0) + 1
                    except Exception as e:
                        log.warning(f"更新复用计数失败: {e}")

                # 更新需求任务
                req_task_db = db.query(RequirementTask).filter(RequirementTask.id == req_id).first()
                if req_task_db:
                    req_task_db.generated_script = script_content
                    req_task_db.task_id = task.id
                    req_task_db.script_source = "reused"
                    req_task_db.reuse_similarity = str(similarity)
                    db.commit()

                yield json.dumps({
                    "step": "脚本生成完成",
                    "progress": 80 if not execute else 82,
                    "message": f"已复用历史脚本 | 相似度: {similarity} | 无需重新生成",
                    "data": {
                        "task_id": task.id,
                        "script_preview": script_content,
                        "has_execution": execute,
                        "script_source": "reused",
                        "reuse_similarity": similarity,
                    }
                }, ensure_ascii=False)

            else:
                # ===== 未命中复用，委托给统一管道执行 =====
                # 第一代和管道现在走同一条路径，由 build_pipeline_steps + execute_pipeline_sse 驱动
                RequirementFlowService._update_requirement_task(db, req_id, status=RequirementStatus.RETRIEVING)

                yield json.dumps({
                    "step": "开始生成",
                    "progress": 25,
                    "message": "复用未命中，开始执行统一生成管道..."
                }, ensure_ascii=False)

                # 构建统一管道步骤（与管道入口走相同的步骤数组）
                from app.api.agent_runtime import build_pipeline_steps
                workflow_name = f"{detected_type}_test" if detected_type != "web" else "web_test"
                pipeline_steps = build_pipeline_steps(workflow_name, requirement)

                # 将第一代的解析结果注入管道上下文（避免重复解析需求）
                # 管道第1步是requirement_agent.analyze，但我们已经解析过了
                # 所以跳过第1步，直接从RAG开始
                if pipeline_steps and pipeline_steps[0].get("agent_type") == "requirement_agent":
                    pipeline_steps = pipeline_steps[1:]  # 跳过需求解析（已完成）

                # 构建管道上下文（注入已解析的结果）
                pipeline_context = {
                    "requirement_analysis": {
                        "intent": intent,
                        "steps": steps,
                        "keywords": keywords,
                        "target_url": target_url,
                        "summary": summary,
                    },
                }

                # 执行管道并转换SSE事件为第一代进度格式
                from app.runtime.task_runtime import TaskRuntime
                task_runtime = TaskRuntime()

                pipeline_result = None
                try:
                    async for event in task_runtime.execute_pipeline_sse(
                        steps=pipeline_steps,
                        session_id=f"req_{req_id}",
                        timeout=600,
                    ):
                        event_type = event.get("event", "")
                        event_data = event.get("data", {})

                        if event_type == "step_start":
                            step_idx = event_data.get("step", 0)
                            agent_type = event_data.get("agent_type", "")
                            # 映射步骤索引到进度百分比
                            progress_map = {0: 25, 1: 30, 2: 35, 3: 40, 4: 45, 5: 50, 6: 65, 7: 80}
                            progress = progress_map.get(step_idx, 50)
                            agent_labels = {
                                "rag_agent": "RAG检索",
                                "relation_agent": "页面关联",
                                "graph_agent": "图推理",
                                "flow_parser": "流程检测",
                                "case_agent": "用例生成",
                                "script_generation_agent": "脚本生成",
                                "execution_agent": "脚本执行",
                                "feedback_agent": "结果分析",
                            }
                            label = agent_labels.get(agent_type, agent_type)
                            yield json.dumps({
                                "step": label,
                                "progress": progress,
                                "message": f"正在执行{label}..."
                            }, ensure_ascii=False)

                        elif event_type == "step_completed":
                            step_idx = event_data.get("step", 0)
                            step_data = event_data.get("data", {})
                            # 检查是否有降级信息
                            if isinstance(step_data, dict) and "degradation_info" in step_data:
                                deg = step_data["degradation_info"]
                                yield json.dumps({
                                    "step": "脚本降级",
                                    "progress": 65,
                                    "message": deg.get("message", "脚本生成发生降级"),
                                    "data": {"degradation_info": deg},
                                }, ensure_ascii=False)

                        elif event_type == "step_failed":
                            error = event_data.get("error", "未知错误")
                            yield json.dumps({
                                "step": "执行失败",
                                "progress": 50,
                                "message": f"管道步骤失败: {error}",
                                "data": {"error": error},
                            }, ensure_ascii=False)

                        elif event_type == "pipeline_completed":
                            pipeline_result = event_data
                            final_data = event_data.get("final_data", {})
                            context = event_data.get("context", {})

                            # 提取脚本内容
                            script_content = ""
                            if "test_script" in context:
                                script_data = context["test_script"]
                                if isinstance(script_data, dict):
                                    script_content = script_data.get("script_content", "")
                                elif isinstance(script_data, str):
                                    script_content = script_data

                            # 提取用例
                            test_cases = context.get("test_cases", {})

                            # 提取降级信息
                            degradation_info = None
                            if isinstance(script_data, dict) and "degradation_info" in script_data:
                                degradation_info = script_data["degradation_info"]

                            yield json.dumps({
                                "step": "生成完成",
                                "progress": 80,
                                "message": "脚本生成完成",
                                "data": {
                                    "script_content": script_content,
                                    "test_cases": test_cases,
                                    "degradation_info": degradation_info,
                                    "script_source": "pipeline",
                                },
                            }, ensure_ascii=False)

                except Exception as e:
                    log.error(f"管道执行异常: {e}", exc_info=True)
                    yield json.dumps({
                        "step": "执行异常",
                        "progress": 50,
                        "message": f"管道执行异常: {str(e)}",
                        "data": {"error": str(e)},
                    }, ensure_ascii=False)

                # 提取最终脚本内容
                script_content = ""
                script_data = None
                if pipeline_result:
                    context = pipeline_result.get("context", {})
                    if "test_script" in context:
                        script_data = context["test_script"]
                        if isinstance(script_data, dict):
                            script_content = script_data.get("script_content", "")
                        elif isinstance(script_data, str):
                            script_content = script_data

                # 保存脚本到数据库
                if script_content:
                    try:
                        req_task = db.query(RequirementTask).filter(RequirementTask.id == req_id).first()
                        if req_task:
                            req_task.generated_script = script_content
                            req_task.status = RequirementStatus.GENERATED
                            db.commit()
                    except Exception as e:
                        log.error(f"保存脚本失败: {e}")

                # 阶段6: 执行脚本（可选）
                if execute and script_content:
                    # ===== 阶段6: 执行脚本 =====
                    RequirementFlowService._update_requirement_task(db, req_id, status=RequirementStatus.EXECUTING)

                    # 根据测试类型选择执行器
                    type_labels = {"web": "Playwright", "api": "API", "android": "Appium", "performance": "性能"}
                    executor_label = type_labels.get(detected_type, "Playwright")

                    yield json.dumps({
                        "step": "执行脚本",
                        "progress": 85,
                        "message": f"正在执行{executor_label}脚本..."
                    }, ensure_ascii=False)

                    try:
                        if detected_type in ("api", "android", "performance"):
                            from app.agent.execution.executor_factory import ExecutorFactory
                            executor = ExecutorFactory.create(detected_type)
                            exec_result = executor.execute(
                                script_content=script_content,
                                config={"timeout": 600 if detected_type in ("android", "performance") else 300},
                            )
                        else:
                            executor = AgentRegistry.create("execution_agent")
                            exec_result = executor.execute_script(script_content)

                        yield json.dumps({
                            "step": "执行完成",
                            "progress": 95,
                            "message": f"脚本执行完成 | 结果: {exec_result.get('status', 'unknown')}",
                            "data": exec_result,
                        }, ensure_ascii=False)
                    except Exception as e:
                        log.error(f"脚本执行失败: {e}", exc_info=True)
                        yield json.dumps({
                            "step": "执行失败",
                            "progress": 85,
                            "message": f"脚本执行失败: {str(e)}",
                            "data": {"error": str(e)},
                        }, ensure_ascii=False)

                # ===== Milvus自动索引（将新脚本向量化，供后续复用检查）=====
                if script_content:
                    try:
                        embed_agent = AgentRegistry.create("embedding_agent")
                        script_vector = embed_agent._embed([requirement[:500]])
                        if script_vector:
                            from app.db.milvus_client import ensure_all_collections, SCRIPT_COLLECTION_NAME
                            client = ensure_all_collections()
                            client.insert(
                                collection_name=SCRIPT_COLLECTION_NAME,
                                data=[{
                                    "id": hash(f"req_{req_id}_script") & 0x7FFFFFFF,
                                    "task_id": req_id,
                                    "script_name": f"req_{req_id}_script",
                                    "script_content": script_content[:8000],
                                    "description": requirement[:500],
                                    "vector": script_vector[0],
                                }],
                            )
                            log.info(f"[DEBUG] Milvus自动索引完成 | task_id={req_id}")
                    except Exception as e:
                        log.warning(f"Milvus自动索引失败: {e}")

                # ===== 阶段6: 执行脚本（可选）=====

            # ===== 阶段6: 执行脚本（可选） =====
            if execute:
                RequirementFlowService._update_requirement_task(db, req_id, status=RequirementStatus.EXECUTING)

                # [DEBUG] 执行脚本前 - ExecutionAgent
                _exec_start = _time.time()

                # 根据task_type选择执行器
                type_labels = {"web": "Playwright", "api": "API", "android": "Appium", "performance": "性能"}
                executor_label = type_labels.get(detected_type, "Playwright")
                log.info(f"[DEBUG] 开始：ExecutionAgent | 输入：task_id={task.id}, task_type={detected_type}, executor={executor_label}")

                # [DEBUG] SSE推送前
                log.info(f"[DEBUG] SSE推送 | step=开始执行 | progress=85")
                yield json.dumps({
                    "step": "开始执行",
                    "progress": 85,
                    "message": f"正在使用{executor_label}执行器运行脚本..."
                }, ensure_ascii=False)

                from app.services.execution import ExecutionService
                exec_record = ExecutionService.create_execution(db, task.id)
                exec_id = exec_record.id

                RequirementFlowService._update_requirement_task(db, req_id, execution_id=exec_id)

                exec_result_holder = {"done": False, "error": None, "result": None}
                exec_log_queue = queue.Queue()

                def on_exec_log(data: dict):
                    exec_log_queue.put(data)

                def run_execution():
                    try:
                        if detected_type in ("api", "android", "performance"):
                            # 非Web类型：使用ExecutorFactory
                            from app.agent.execution.executor_factory import ExecutorFactory
                            executor = ExecutorFactory.create(detected_type)
                            exec_result = executor.execute(
                                script_content=script_content,
                                config={"timeout": 600 if detected_type in ("android", "performance") else 300},
                            )
                            # 转换为统一格式
                            exec_result_holder["result"] = {
                                "status": "success" if exec_result["success"] else "failed",
                                "success_count": 1 if exec_result["success"] else 0,
                                "failed_count": 0 if exec_result["success"] else 1,
                                "error_message": exec_result.get("error", ""),
                                "log_content": exec_result.get("output", ""),
                                "duration": exec_result.get("duration", 0),
                                "executor": exec_result.get("executor", detected_type),
                            }
                        else:
                            # Web类型：使用原有ExecutionAgent（Playwright）
                            agent = AgentRegistry.create("execution_agent")
                            result = agent.execute_script(
                                script_content=script_content,
                                task_id=task.id,
                                execution_id=exec_id,
                                on_log=on_exec_log,
                            )
                            exec_result_holder["result"] = result
                    except Exception as e:
                        log.error(f"ExecutionAgent异常: {e}", exc_info=True)
                        exec_result_holder["error"] = str(e)
                    finally:
                        exec_result_holder["done"] = True
                        exec_log_queue.put({"__done__": True})

                exec_thread = threading.Thread(target=run_execution, daemon=True)
                exec_thread.start()

                while True:
                    try:
                        log_data = exec_log_queue.get(timeout=0.5)
                    except queue.Empty:
                        if exec_result_holder["done"] or not exec_thread.is_alive():
                            break
                        continue
                    if log_data.get("__done__"):
                        break
                    yield json.dumps({
                        "step": log_data.get("step", "执行中"),
                        "progress": 85 + int(log_data.get("progress", 0) * 0.1),
                        "message": log_data.get("message", ""),
                    }, ensure_ascii=False)

                exec_thread.join(timeout=10)

                # [DEBUG] 执行脚本后 - ExecutionAgent
                _exec_elapsed = _time.time() - _exec_start
                _exec_status = exec_result_holder["result"]["status"] if exec_result_holder["result"] else "error"
                log.info(f"[DEBUG] 结束：ExecutionAgent | 输出：status={_exec_status} | 耗时：{_exec_elapsed:.2f}s")
    
                # 更新执行记录
                update_db = SessionLocal()
                try:
                    exec_record_update = update_db.query(ExecutionRecord).filter(ExecutionRecord.id == exec_id).first()
                    if exec_result_holder["result"] and exec_record_update:
                        result = exec_result_holder["result"]
                        exec_record_update.status = ExecutionStatus.SUCCESS if result["status"] == "success" else ExecutionStatus.FAILED
                        exec_record_update.start_time = result.get("start_time")
                        exec_record_update.end_time = result.get("end_time")
                        exec_record_update.duration = result.get("duration")
                        exec_record_update.success_count = result.get("success_count", 0)
                        exec_record_update.failed_count = result.get("failed_count", 0)
                        exec_record_update.error_message = result.get("error_message")
                        exec_record_update.log_content = result.get("log_content")
                        exec_record_update.report_path = result.get("report_path")
                        exec_record_update.screenshot_path = result.get("screenshot_path")

                        # 执行失败时自动触发缺陷分析
                        if result["status"] != "success":
                            try:
                                script_obj = update_db.query(Script).filter(Script.task_id == task.id).first()
                                ea = AgentRegistry.create("execution_agent")
                                analysis = ea.analyze_failure(
                                    log_content=result.get("log_content", ""),
                                    error_message=result.get("error_message", ""),
                                    script_content=script_obj.script_content if script_obj else "",
                                    screenshot_path=result.get("screenshot_path", ""),
                                )
                                exec_record_update.analysis_result = json.dumps(analysis, ensure_ascii=False)
                            except Exception as ae:
                                log.warning(f"自动缺陷分析失败: {ae}")

                        update_db.commit()

                        yield json.dumps({
                            "step": "执行完成",
                            "progress": 95,
                            "message": f"执行{'成功' if result['status'] == 'success' else '失败'} | 通过: {result.get('success_count', 0)}, 失败: {result.get('failed_count', 0)}",
                            "data": {
                                "execution_id": exec_id,
                                "status": result["status"],
                                "success_count": result.get("success_count", 0),
                                "failed_count": result.get("failed_count", 0),
                                "screenshot_path": result.get("screenshot_path"),
                                "report_path": result.get("report_path"),
                            }
                        }, ensure_ascii=False)

                    elif exec_result_holder["error"] and exec_record_update:
                        exec_record_update.status = ExecutionStatus.FAILED
                        exec_record_update.error_message = exec_result_holder["error"]

                        # 执行失败时自动触发缺陷分析
                        try:
                            script_obj = update_db.query(Script).filter(Script.task_id == task.id).first()
                            ea = AgentRegistry.create("execution_agent")
                            analysis = ea.analyze_failure(
                                log_content=exec_record_update.log_content or "",
                                error_message=exec_result_holder["error"],
                                script_content=script_obj.script_content if script_obj else "",
                                screenshot_path=exec_record_update.screenshot_path or "",
                            )
                            exec_record_update.analysis_result = json.dumps(analysis, ensure_ascii=False)
                        except Exception as ae:
                            log.warning(f"自动缺陷分析失败: {ae}")

                        update_db.commit()

                        yield json.dumps({
                            "step": "执行失败",
                            "progress": 95,
                            "message": f"执行异常: {exec_result_holder['error']}"
                        }, ensure_ascii=False)
                finally:
                    update_db.close()

            # ===== 自动知识库更新 =====
            # [DEBUG] 数据入库前 - Neo4j
            _neo4j_start = _time.time()
            log.info(f"[DEBUG] 开始：Neo4j知识库更新 | 输入：req_id={req_id}, task_id={task.id}")
            try:
                from app.agent.requirement.knowledge_update_agent import KnowledgeUpdateAgent
                kb_agent = KnowledgeUpdateAgent()
                kb_result = kb_agent.update_after_execution(
                    requirement_id=req_id,
                    task_id=task.id,
                    execution_id=exec_id if execute else None,
                )
                milvus_count = kb_result.get("milvus", {}).get("cases", 0) + kb_result.get("milvus", {}).get("scripts", 0)
                neo4j_count = kb_result.get("neo4j", {}).get("nodes", 0) + kb_result.get("neo4j", {}).get("relationships", 0)
                if milvus_count > 0 or neo4j_count > 0:
                    yield json.dumps({
                        "step": "知识库更新",
                        "progress": 97,
                        "message": f"知识库已更新 | Milvus: {milvus_count}条 | Neo4j: {neo4j_count}个",
                    }, ensure_ascii=False)
                    log.info(f"知识库自动更新完成 | req={req_id} task={task.id} | {kb_result}")
            except Exception as e:
                log.warning(f"知识库自动更新失败（不影响主流程）: {e}")

            # [DEBUG] 数据入库后 - Neo4j
            _neo4j_elapsed = _time.time() - _neo4j_start
            log.info(f"[DEBUG] 结束：Neo4j知识库更新 | 耗时：{_neo4j_elapsed:.2f}s")

            # ===== 完成 =====
            RequirementFlowService._update_requirement_task(db, req_id, status=RequirementStatus.COMPLETED)

            # [DEBUG] SSE推送前 - 最终完成
            _generate_elapsed = _time.time() - _generate_start
            log.info(f"[DEBUG] 结束：RequirementFlowService.generate | 输出：completed | 总耗时：{_generate_elapsed:.2f}s")

            yield json.dumps({
                "step": "任务完成",
                "progress": 100,
                "message": f"需求驱动测试{'生成并执行' if execute else '脚本生成'}完成！",
                "data": {
                    "requirement_id": req_id,
                    "task_id": task.id,
                    "intent": intent,
                    "case_name": case_result.get("case_name", "") if not reuse_result.get("reuse") else "",
                    "executed": execute,
                    "script_source": "reused" if reuse_result.get("reuse") else "generated",
                    "reuse_similarity": reuse_result.get("similarity", 0),
                }
            }, ensure_ascii=False)

        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            # [DEBUG] 异常
            _generate_elapsed = _time.time() - _generate_start
            log.error(f"[DEBUG] 异常：RequirementFlowService.generate | 错误：{err_msg} | 总耗时：{_generate_elapsed:.2f}s")
            log.error(f"RequirementFlowService异常: {err_msg}", exc_info=True)

            if req_task:
                try:
                    RequirementFlowService._update_requirement_task(db, req_task.id, status=RequirementStatus.FAILED, error_message=err_msg)
                except Exception:
                    pass

            yield json.dumps({"step": "任务失败", "progress": 100, "message": err_msg}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    async def generate_multimodal(
        text: Optional[str] = None,
        images: Optional[list] = None,
        urls: Optional[list] = None,
        script_content: Optional[str] = None,
        script_language: str = "python",
        page_ids: Optional[list] = None,
        execute: bool = False,
        script_format: str = "playwright",
    ) -> AsyncGenerator[str, None]:
        """
        多模态需求驱动生成测试脚本

        流程：多模态解析(InputRouter) → 融合(FusionAgent) → 需求解析 → 后续标准流程

        Args:
            text: 文本需求
            images: 图片路径列表
            urls: URL列表
            script_content: 脚本内容
            script_language: 脚本语言
            page_ids: 关联页面ID列表
            execute: 是否执行脚本
            script_format: 脚本格式

        Yields:
            SSE格式的进度信息
        """
        from app.agent.requirement.input_router import InputRouter
        from app.agent.requirement.fusion_agent import FusionAgent
        from app.models.requirement_input import RequirementInput

        # ===== 阶段0: 多模态输入解析与融合 =====
        yield json.dumps({
            "step": "多模态解析开始",
            "progress": 1,
            "message": "正在解析多模态输入...",
        }, ensure_ascii=False)

        input_router = InputRouter()
        input_data = {
            "text": text or "",
            "images": images or [],
            "urls": urls or [],
            "script_content": script_content or "",
            "script_language": script_language,
            "page_ids": page_ids or [],
        }
        route_result = input_router.route(input_data)

        yield json.dumps({
            "step": "多模态解析完成",
            "progress": 3,
            "message": f"输入模式: {route_result['mode']}，推荐: {route_result['recommended_mode']}",
            "data": {
                "mode": route_result["mode"],
                "recommended_mode": route_result["recommended_mode"],
                "recommended_reason": route_result["recommended_reason"],
                "active_modes": route_result["active_modes"],
            }
        }, ensure_ascii=False)

        # 融合
        fusion_agent = FusionAgent()
        fused = fusion_agent.fuse(route_result["parse_results"], route_result["mode"])

        unified_requirement = fused.get("unified_requirement", "")
        if not unified_requirement:
            # 降级：使用原始文本
            unified_requirement = text or "多模态测试需求"

        yield json.dumps({
            "step": "多模态融合完成",
            "progress": 4,
            "message": f"融合置信度: {fused.get('confidence', 0):.1%}，来源: {fused.get('sources', [])}",
            "data": {
                "intent": fused.get("intent"),
                "target_url": fused.get("target_url"),
                "confidence": fused.get("confidence"),
                "sources": fused.get("sources"),
            }
        }, ensure_ascii=False)

        # 保存多模态输入记录
        db = SessionLocal()
        try:
            req_input = RequirementInput(
                mode=route_result["mode"],
                text=text,
                images=json.dumps(images or [], ensure_ascii=False) if images else None,
                urls=json.dumps(urls or [], ensure_ascii=False) if urls else None,
                script_content=script_content,
                script_language=script_language,
                page_ids=json.dumps(page_ids or [], ensure_ascii=False) if page_ids else None,
                recommended_mode=route_result["recommended_mode"],
                recommended_reason=route_result["recommended_reason"],
                parsed_result=json.dumps(route_result["parse_results"], ensure_ascii=False),
                fused_result=json.dumps(fused, ensure_ascii=False),
                unified_requirement=unified_requirement,
            )
            db.add(req_input)
            db.commit()
        finally:
            db.close()

        # 提取融合后的附加信息
        fused_target_url = fused.get("target_url", "")
        fused_additional_info = ""
        if urls:
            fused_additional_info = "\n".join(urls)
        if fused_target_url:
            fused_additional_info = fused_target_url

        # 融合后的图片路径
        fused_image_paths = images if images else None

        # ===== 进入标准流程 =====
        async for event in RequirementFlowService.generate(
            requirement=unified_requirement,
            execute=execute,
            additional_info=fused_additional_info if fused_additional_info else None,
            image_paths=fused_image_paths,
            script_format=script_format,
        ):
            yield event

    @staticmethod
    async def execute_only(requirement_id: int) -> AsyncGenerator[str, None]:
        """仅执行已生成的脚本"""
        db = SessionLocal()
        try:
            req_task = db.query(RequirementTask).filter(RequirementTask.id == requirement_id).first()
            if not req_task:
                yield json.dumps({"step": "任务失败", "progress": 100, "message": "需求任务不存在"}, ensure_ascii=False)
                return

            script_content = req_task.generated_script
            task_id = req_task.task_id

            if not script_content:
                yield json.dumps({"step": "任务失败", "progress": 100, "message": "尚未生成脚本"}, ensure_ascii=False)
                return

            if not task_id:
                yield json.dumps({"step": "任务失败", "progress": 100, "message": "未关联测试任务"}, ensure_ascii=False)
                return

            RequirementFlowService._update_requirement_task(db, requirement_id, status=RequirementStatus.EXECUTING)

            # 根据task_type选择执行器
            req_task_type = req_task.task_type or "web"
            type_labels = {"web": "Playwright", "api": "API", "android": "Appium", "performance": "性能"}
            executor_label = type_labels.get(req_task_type, "Playwright")

            yield json.dumps({"step": "开始执行", "progress": 10, "message": f"正在使用{executor_label}执行器运行脚本..."}, ensure_ascii=False)

            exec_record = ExecutionRecord(
                task_id=task_id,
                status=ExecutionStatus.PENDING,
            )
            db.add(exec_record)
            db.commit()
            db.refresh(exec_record)
            exec_id = exec_record.id

            RequirementFlowService._update_requirement_task(db, requirement_id, execution_id=exec_id)

            exec_result_holder = {"done": False, "error": None, "result": None}
            exec_log_queue = queue.Queue()

            def on_exec_log(data: dict):
                exec_log_queue.put(data)

            def run_execution():
                try:
                    if req_task_type in ("api", "android", "performance"):
                        # 非Web类型：使用ExecutorFactory
                        from app.agent.execution.executor_factory import ExecutorFactory
                        executor = ExecutorFactory.create(req_task_type)
                        exec_result = executor.execute(
                            script_content=script_content,
                            config={"timeout": 600 if req_task_type in ("android", "performance") else 300},
                        )
                        exec_result_holder["result"] = {
                            "status": "success" if exec_result["success"] else "failed",
                            "success_count": 1 if exec_result["success"] else 0,
                            "failed_count": 0 if exec_result["success"] else 1,
                            "error_message": exec_result.get("error", ""),
                            "log_content": exec_result.get("output", ""),
                            "duration": exec_result.get("duration", 0),
                            "executor": exec_result.get("executor", req_task_type),
                        }
                    else:
                        agent = AgentRegistry.create("execution_agent")
                        result = agent.execute_script(
                            script_content=script_content,
                            task_id=task_id,
                            execution_id=exec_id,
                            on_log=on_exec_log,
                        )
                        exec_result_holder["result"] = result
                except Exception as e:
                    log.error(f"ExecutionAgent异常: {e}", exc_info=True)
                    exec_result_holder["error"] = str(e)
                finally:
                    exec_result_holder["done"] = True
                    exec_log_queue.put({"__done__": True})

            exec_thread = threading.Thread(target=run_execution, daemon=True)
            exec_thread.start()

            while True:
                try:
                    log_data = exec_log_queue.get(timeout=0.5)
                except queue.Empty:
                    if exec_result_holder["done"] or not exec_thread.is_alive():
                        break
                    continue
                if log_data.get("__done__"):
                    break
                yield json.dumps({
                    "step": log_data.get("step", "执行中"),
                    "progress": 10 + int(log_data.get("progress", 0) * 0.8),
                    "message": log_data.get("message", ""),
                }, ensure_ascii=False)

            exec_thread.join(timeout=10)

            update_db = SessionLocal()
            try:
                exec_record_update = update_db.query(ExecutionRecord).filter(ExecutionRecord.id == exec_id).first()
                if exec_result_holder["result"] and exec_record_update:
                    result = exec_result_holder["result"]
                    exec_record_update.status = ExecutionStatus.SUCCESS if result["status"] == "success" else ExecutionStatus.FAILED
                    exec_record_update.start_time = result.get("start_time")
                    exec_record_update.end_time = result.get("end_time")
                    exec_record_update.duration = result.get("duration")
                    exec_record_update.success_count = result.get("success_count", 0)
                    exec_record_update.failed_count = result.get("failed_count", 0)
                    exec_record_update.error_message = result.get("error_message")
                    exec_record_update.log_content = result.get("log_content")
                    exec_record_update.report_path = result.get("report_path")
                    exec_record_update.screenshot_path = result.get("screenshot_path")

                    # 执行失败时自动触发缺陷分析
                    if result["status"] != "success":
                        try:
                            script_obj = update_db.query(Script).filter(Script.task_id == task_id).first()
                            ea = AgentRegistry.create("execution_agent")
                            analysis = ea.analyze_failure(
                                log_content=result.get("log_content", ""),
                                error_message=result.get("error_message", ""),
                                script_content=script_obj.script_content if script_obj else "",
                                screenshot_path=result.get("screenshot_path", ""),
                            )
                            exec_record_update.analysis_result = json.dumps(analysis, ensure_ascii=False)
                        except Exception as ae:
                            log.warning(f"自动缺陷分析失败: {ae}")

                    update_db.commit()

                    yield json.dumps({
                        "step": "执行完成",
                        "progress": 95,
                        "message": f"执行{'成功' if result['status'] == 'success' else '失败'} | 通过: {result.get('success_count', 0)}, 失败: {result.get('failed_count', 0)}",
                        "data": {
                            "execution_id": exec_id,
                            "status": result["status"],
                            "success_count": result.get("success_count", 0),
                            "failed_count": result.get("failed_count", 0),
                            "screenshot_path": result.get("screenshot_path"),
                            "report_path": result.get("report_path"),
                        }
                    }, ensure_ascii=False)

                elif exec_result_holder["error"] and exec_record_update:
                    exec_record_update.status = ExecutionStatus.FAILED
                    exec_record_update.error_message = exec_result_holder["error"]

                    # 执行失败时自动触发缺陷分析
                    try:
                        script_obj = update_db.query(Script).filter(Script.task_id == task_id).first()
                        ea = AgentRegistry.create("execution_agent")
                        analysis = ea.analyze_failure(
                            log_content=exec_record_update.log_content or "",
                            error_message=exec_result_holder["error"],
                            script_content=script_obj.script_content if script_obj else "",
                            screenshot_path=exec_record_update.screenshot_path or "",
                        )
                        exec_record_update.analysis_result = json.dumps(analysis, ensure_ascii=False)
                    except Exception as ae:
                        log.warning(f"自动缺陷分析失败: {ae}")

                    update_db.commit()

                    yield json.dumps({
                        "step": "执行失败",
                        "progress": 95,
                        "message": f"执行异常: {exec_result_holder['error']}"
                    }, ensure_ascii=False)
            finally:
                update_db.close()

            # ===== 自动知识库更新 =====
            # [DEBUG] 数据入库前 - Neo4j
            _neo4j_start = _time.time()
            log.info(f"[DEBUG] 开始：Neo4j知识库更新 | 输入：req_id={req_id}, task_id={task.id}")
            try:
                from app.agent.requirement.knowledge_update_agent import KnowledgeUpdateAgent
                kb_agent = KnowledgeUpdateAgent()
                kb_result = kb_agent.update_after_execution(
                    requirement_id=requirement_id,
                    task_id=task_id,
                    execution_id=exec_id,
                )
                milvus_count = kb_result.get("milvus", {}).get("cases", 0) + kb_result.get("milvus", {}).get("scripts", 0)
                neo4j_count = kb_result.get("neo4j", {}).get("nodes", 0) + kb_result.get("neo4j", {}).get("relationships", 0)
                if milvus_count > 0 or neo4j_count > 0:
                    yield json.dumps({
                        "step": "知识库更新",
                        "progress": 97,
                        "message": f"知识库已更新 | Milvus: {milvus_count}条 | Neo4j: {neo4j_count}个",
                    }, ensure_ascii=False)
            except Exception as e:
                log.warning(f"知识库自动更新失败（不影响主流程）: {e}")

            RequirementFlowService._update_requirement_task(db, requirement_id, status=RequirementStatus.COMPLETED)

            yield json.dumps({
                "step": "任务完成",
                "progress": 100,
                "message": "脚本执行完成！",
                "data": {"executed": True}
            }, ensure_ascii=False)

        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            log.error(f"execute_only异常: {err_msg}", exc_info=True)
            yield json.dumps({"step": "任务失败", "progress": 100, "message": err_msg}, ensure_ascii=False)
        finally:
            db.close()

    @staticmethod
    def get_requirement_tasks(db, limit: int = 20):
        """获取需求任务列表"""
        return db.query(RequirementTask).order_by(
            RequirementTask.created_at.desc()
        ).limit(limit).all()

    @staticmethod
    def get_requirement_task(db, task_id: int):
        """获取需求任务详情"""
        return db.query(RequirementTask).filter(RequirementTask.id == task_id).first()

    @staticmethod
    def get_reuse_stats(db) -> Dict[str, Any]:
        """获取脚本复用统计"""
        from sqlalchemy import func

        total_scripts = db.query(func.count(Script.id)).scalar() or 0
        reused_scripts = db.query(func.count(Script.id)).filter(Script.script_source == "reused").scalar() or 0
        generated_scripts = db.query(func.count(Script.id)).filter(Script.script_source == "generated").scalar() or 0
        total_reuse_count = db.query(func.sum(Script.reuse_count)).scalar() or 0

        # 估算节省的Token（每次复用约节省2000 tokens）
        estimated_saved_tokens = int(total_reuse_count) * 2000

        return {
            "total_scripts": total_scripts,
            "generated_scripts": generated_scripts,
            "reused_scripts": reused_scripts,
            "total_reuse_count": int(total_reuse_count),
            "estimated_saved_tokens": estimated_saved_tokens,
        }


# ===== 工具函数 =====

def _safe_name(name: str) -> str:
    """将用例名称转为安全的函数名"""
    import re
    name = re.sub(r'[^\w]', '_', name)
    name = re.sub(r'_+', '_', name)
    name = name.strip('_')
    return name.lower() or "test"


def _escape(s: str) -> str:
    """转义字符串"""
    if not s:
        return ""
    return s.replace('\\', '\\\\').replace('"', '\\"')


def _fix_locator(locator: str) -> str:
    """修复定位器"""
    if not locator:
        return locator
    stripped = locator.strip()
    if stripped.startswith("/") or stripped.startswith("./"):
        return "xpath=" + locator
    return locator
