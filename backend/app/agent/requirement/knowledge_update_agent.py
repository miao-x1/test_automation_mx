"""
KnowledgeUpdateAgent - 知识库自动更新Agent

执行完成后自动入库：
1. 需求 → Milvus（需求描述向量）+ Neo4j（TestCase节点）
2. 脚本 → Milvus（脚本向量）+ Neo4j（Script节点）
3. 执行结果 → Neo4j（执行结果属性）
4. 反馈 → Neo4j（反馈属性）
5. 图关系 → Neo4j（节点间关系）

架构：
- 旧：Agent → Milvus + Neo4j（直接调用 db 客户端）
- 新：Agent → StorageRouter → Milvus + Neo4j
  Agent 层禁止直接导入 app.db.milvus_client / app.db.neo4j_client，
  所有写入通过 StorageRouter 统一路由，实现数据层解耦。

能力：
- 自动Embedding（DashScope/本地）
- 自动写Milvus（增量，避免重复）
- 自动更新Neo4j（MERGE，幂等）
- 增量更新（按task_id去重）
"""
import json
from typing import Dict, Any, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.services.context_router import get_context_router, ContextType
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.agents.factory import AgentRegistry


# ===== 数据层常量（从统一常量文件导入）=====
from app.db.collection_constants import (
    CASE_COLLECTION as CASE_COLLECTION_NAME,
    SCRIPT_COLLECTION as SCRIPT_COLLECTION_NAME,
)
# Neo4j 节点标签
LABEL_PAGE = "Page"
LABEL_CASE = "TestCase"
LABEL_SCRIPT = "Script"
# Neo4j 关系类型
REL_TEST_ON = "TEST_ON"
REL_GENERATES = "GENERATES"
REL_EXECUTES = "EXECUTES"


class KnowledgeUpdateAgent(NewBaseAgent):
    """知识库自动更新Agent"""

    agent_name = "knowledge_update"
    display_name = "Knowledge Update Agent"
    description = "知识库自动更新Agent - 执行完成后自动入库需求、脚本、执行结果、反馈、图关系"
    capabilities = [AgentCapability.KNOWLEDGE_UPDATE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.agent_type = "knowledge_update"
        self.model = None
        self.system_prompt = None
        self._embed_agent = None
        self._storage = None  # StorageRouter 懒加载（见 storage property）

    @property
    def storage(self):
        """统一写入路由（StorageRouter），懒加载

        Agent 通过此属性访问 Milvus / Neo4j，禁止直接导入 db 客户端：
          - self.storage.milvus_ensure_collections()
          - self.storage.milvus_query(collection_name, filter_expr, output_fields)
          - self.storage.milvus_insert(collection_name, data_list)
          - self.storage.neo4j_available()
          - self.storage.neo4j_ensure_constraints()
          - self.storage.neo4j_write(cypher, **params)
        """
        if self._storage is None:
            from app.services.context_router.storage_router import get_storage_router
            self._storage = get_storage_router()
        return self._storage

    def _get_embed_agent(self):
        """懒加载EmbeddingAgent"""
        if self._embed_agent is None:
            self._embed_agent = AgentRegistry.create("embedding_agent")
        return self._embed_agent

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """生成向量"""
        agent = self._get_embed_agent()
        return agent._embed(texts)

    def update_after_execution(
        self,
        requirement_id: int,
        task_id: int,
        execution_id: Optional[int] = None,
        feedback_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        执行完成后自动更新知识库

        入库内容：需求、脚本、执行结果、反馈、图关系

        Args:
            requirement_id: 需求任务ID
            task_id: 测试任务ID
            execution_id: 执行记录ID
            feedback_id: 反馈ID

        Returns:
            更新统计
        """
        stats = {
            "milvus": {"cases": 0, "scripts": 0, "skipped": 0},
            "neo4j": {"nodes": 0, "relationships": 0, "skipped": 0},
            "success": True,
            "errors": [],
        }

        router = get_context_router()
        try:
            # 读取数据（通过 ContextRouter，不再直接使用 SessionLocal）
            req_task = router.query_by_id(ContextType.REQUIREMENT_TASK, record_id=requirement_id)
            if not req_task:
                stats["errors"].append(f"需求任务 {requirement_id} 不存在")
                stats["success"] = False
                return stats

            script_result = router.query("", ContextType.SCRIPT, top_k=10, filters={"task_id": task_id})
            script = script_result.get("results", [])[0] if script_result.get("results") else None
            exec_record = router.query_by_id(ContextType.EXECUTION_HISTORY, record_id=execution_id) if execution_id else None
            feedback = router.query_by_id(ContextType.FEEDBACK, record_id=feedback_id) if feedback_id else None

            requirement = req_task.get("requirement") or ""
            script_content = script.get("script_content", "") if script else ""
            case_data = None
            if req_task.get("generated_case"):
                try:
                    case_data = json.loads(req_task.get("generated_case"))
                except json.JSONDecodeError:
                    case_data = None

            # ===== 1. Milvus更新 =====
            milvus_result = self._update_milvus(
                task_id=task_id,
                requirement=requirement,
                case_data=case_data,
                script_content=script_content,
            )
            stats["milvus"] = milvus_result

            # ===== 2. Neo4j更新 =====
            # 从关联的Task获取page_url
            task = router.query_by_id(ContextType.TASK, record_id=task_id)
            page_url = task.get("page_url", "") if task and task.get("page_url") else ""

            neo4j_result = self._update_neo4j(
                task_id=task_id,
                requirement=requirement,
                case_data=case_data,
                script_content=script_content,
                script_model=script,
                exec_record=exec_record,
                feedback=feedback,
                page_url=page_url,
            )
            stats["neo4j"] = neo4j_result

            log.info(
                f"KnowledgeUpdate | 完成 | req={requirement_id} task={task_id} | "
                f"milvus: cases={milvus_result['cases']} scripts={milvus_result['scripts']} | "
                f"neo4j: nodes={neo4j_result['nodes']} rels={neo4j_result['relationships']}"
            )

        except Exception as e:
            log.error(f"KnowledgeUpdate | 异常: {e}", exc_info=True)
            stats["errors"].append(str(e))
            stats["success"] = False

        return stats

    def _update_milvus(
        self,
        task_id: int,
        requirement: str,
        case_data: Optional[Dict],
        script_content: str,
    ) -> Dict[str, Any]:
        """更新Milvus向量库（增量，避免重复）"""
        result = {"cases": 0, "scripts": 0, "skipped": 0}

        try:
            # 通过 StorageRouter 确保 Milvus 集合就绪（Agent 不再直接导入 milvus_client）
            client = self.storage.milvus_ensure_collections()
            if client is None:
                result["skipped"] = 2
                log.warning("KnowledgeUpdate | Milvus不可用，跳过向量更新")
                return result

            # 检查是否已索引（按task_id去重）
            indexed_case_task_ids = set()
            indexed_script_task_ids = set()

            # 通过 StorageRouter 查询已索引用例（集合不存在时返回空列表，等价于原 has_collection 守卫）
            rows = self.storage.milvus_query(CASE_COLLECTION_NAME, "id >= 0", ["task_id"])
            indexed_case_task_ids = {r["task_id"] for r in rows}

            # 通过 StorageRouter 查询已索引脚本
            rows = self.storage.milvus_query(SCRIPT_COLLECTION_NAME, "id >= 0", ["task_id"])
            indexed_script_task_ids = {r["task_id"] for r in rows}

            # 索引用例（增量）
            if case_data and task_id not in indexed_case_task_ids:
                try:
                    cn = case_data.get("case_name", "")
                    cd = case_data.get("description", "")
                    desc_parts = [f"用例: {cn}", f"描述: {cd}", f"需求: {requirement}"]
                    for s in case_data.get("steps", [])[:5]:
                        step_desc = s.get("step", s.get("description", "")) if isinstance(s, dict) else str(s)
                        if step_desc:
                            desc_parts.append(f"步骤: {step_desc}")
                    case_desc = " | ".join(desc_parts)

                    embeddings = self._embed([case_desc])
                    steps_json = json.dumps(case_data.get("steps", []), ensure_ascii=False)
                    if len(steps_json) > 4096:
                        steps_json = steps_json[:4096]

                    # 通过 StorageRouter 写入 Milvus（Agent 不直接持有 client）
                    self.storage.milvus_insert(CASE_COLLECTION_NAME, [{
                        "task_id": task_id,
                        "case_name": (cn or "")[:255],
                        "description": (cd or "")[:2048],
                        "steps": steps_json,
                        "embedding": embeddings[0],
                    }])
                    result["cases"] = 1
                    log.info(f"KnowledgeUpdate | Milvus用例已入库 | task_id={task_id}")
                except Exception as e:
                    log.warning(f"KnowledgeUpdate | Milvus用例入库失败: {e}")
            elif task_id in indexed_case_task_ids:
                log.info(f"KnowledgeUpdate | Milvus用例已存在 | task_id={task_id}，跳过")

            # 索引脚本（增量）
            if script_content and task_id not in indexed_script_task_ids:
                try:
                    script_desc = f"脚本类型: playwright | 需求: {requirement} | 内容预览: {script_content[:500]}"
                    embeddings = self._embed([script_desc])
                    sc = script_content[:8192] if len(script_content) > 8192 else script_content

                    # 通过 StorageRouter 写入 Milvus
                    self.storage.milvus_insert(SCRIPT_COLLECTION_NAME, [{
                        "task_id": task_id,
                        "script_name": f"task_{task_id}_script",
                        "script_content": sc,
                        "description": f"任务{task_id}的playwright脚本",
                        "embedding": embeddings[0],
                    }])
                    result["scripts"] = 1
                    log.info(f"KnowledgeUpdate | Milvus脚本已入库 | task_id={task_id}")
                except Exception as e:
                    log.warning(f"KnowledgeUpdate | Milvus脚本入库失败: {e}")
            elif task_id in indexed_script_task_ids:
                log.info(f"KnowledgeUpdate | Milvus脚本已存在 | task_id={task_id}，跳过")

        except Exception as e:
            log.warning(f"KnowledgeUpdate | Milvus更新异常: {e}")
            result["skipped"] += 1

        return result

    def _update_neo4j(
        self,
        task_id: int,
        requirement: str,
        case_data: Optional[Dict],
        script_content: str,
        script_model: Optional[Any],
        exec_record: Optional[Any],
        feedback: Optional[Any],
        page_url: str,
    ) -> Dict[str, Any]:
        """更新Neo4j图数据库（MERGE，幂等）"""
        result = {"nodes": 0, "relationships": 0, "skipped": 0}

        try:
            # 通过 StorageRouter 访问 Neo4j（Agent 不再直接导入 neo4j_client）
            # 标签/关系常量（LABEL_PAGE / LABEL_CASE / LABEL_SCRIPT / REL_TEST_ON 等）
            # 已提取为文件顶部模块级常量，写入操作统一走 self.storage。
            if not self.storage.neo4j_available():
                result["skipped"] = 1
                log.warning("KnowledgeUpdate | Neo4j不可用，跳过图更新")
                return result

            self.storage.neo4j_ensure_constraints()

            # 1. Page节点
            if page_url:
                # 通过 StorageRouter 写入 Neo4j（run_write(cypher, **params)）
                self.storage.neo4j_write(
                    f"MERGE (p:{LABEL_PAGE} {{id: $id}}) "
                    f"SET p.url = $url, p.title = $title, p.updated_at = datetime()",
                    **{"id": f"page_{task_id}", "url": page_url, "title": requirement[:100]},
                )
                result["nodes"] += 1

            # 2. TestCase节点
            if case_data:
                case_name = case_data.get("case_name", "")
                case_desc = case_data.get("description", "")
                steps = case_data.get("steps", [])
                steps_json = json.dumps(steps, ensure_ascii=False)
                if len(steps_json) > 4000:
                    steps_json = steps_json[:4000]

                # 通过 StorageRouter 写入 Neo4j
                self.storage.neo4j_write(
                    f"MERGE (c:{LABEL_CASE} {{id: $id}}) "
                    f"SET c.name = $name, c.description = $desc, "
                    f"c.requirement = $req, c.steps = $steps, "
                    f"c.task_id = $task_id, c.updated_at = datetime()",
                    **{
                        "id": f"case_{task_id}",
                        "name": case_name[:200],
                        "desc": case_desc[:1000],
                        "req": requirement[:2000],
                        "steps": steps_json,
                        "task_id": task_id,
                    },
                )
                result["nodes"] += 1

                # TEST_ON关系
                if page_url:
                    # 通过 StorageRouter 写入 Neo4j
                    self.storage.neo4j_write(
                        f"MATCH (c:{LABEL_CASE}), (p:{LABEL_PAGE}) "
                        f"WHERE c.id = $cid AND p.id = $pid "
                        f"MERGE (c)-[:{REL_TEST_ON}]->(p)",
                        **{"cid": f"case_{task_id}", "pid": f"page_{task_id}"},
                    )
                    result["relationships"] += 1

            # 3. Script节点
            if script_content:
                script_id = f"script_{script_model.get('id')}" if script_model else f"script_task_{task_id}"
                sc_preview = script_content[:2000]

                # 通过 StorageRouter 写入 Neo4j
                self.storage.neo4j_write(
                    f"MERGE (s:{LABEL_SCRIPT} {{id: $id}}) "
                    f"SET s.content_preview = $preview, s.task_id = $task_id, "
                    f"s.language = 'python', s.updated_at = datetime()",
                    **{"id": script_id, "preview": sc_preview, "task_id": task_id},
                )
                result["nodes"] += 1

                # GENERATES关系: TestCase -> Script
                if case_data:
                    # 通过 StorageRouter 写入 Neo4j
                    self.storage.neo4j_write(
                        f"MATCH (c:{LABEL_CASE}), (s:{LABEL_SCRIPT}) "
                        f"WHERE c.id = $cid AND s.id = $sid "
                        f"MERGE (c)-[:{REL_GENERATES}]->(s)",
                        **{"cid": f"case_{task_id}", "sid": script_id},
                    )
                    result["relationships"] += 1

                # EXECUTES关系: Script -> Page
                if page_url:
                    # 通过 StorageRouter 写入 Neo4j
                    self.storage.neo4j_write(
                        f"MATCH (s:{LABEL_SCRIPT}), (p:{LABEL_PAGE}) "
                        f"WHERE s.id = $sid AND p.id = $pid "
                        f"MERGE (s)-[:{REL_EXECUTES}]->(p)",
                        **{"sid": script_id, "pid": f"page_{task_id}"},
                    )
                    result["relationships"] += 1

            # 4. 执行结果属性（附加到Script节点）
            if exec_record and script_content:
                script_id = f"script_{script_model.get('id')}" if script_model else f"script_task_{task_id}"
                exec_props = {
                    "exec_status": exec_record.get("status") or "unknown",
                    "exec_duration": exec_record.get("duration") or 0,
                    "exec_success_count": exec_record.get("success_count") or 0,
                    "exec_failed_count": exec_record.get("failed_count") or 0,
                    "exec_error": (exec_record.get("error_message") or "")[:500],
                    "fail_step": "",
                    "root_cause": "",
                    "suggestion": "",
                }
                # 如果有分析结果，也写入
                if exec_record.get("analysis_result"):
                    try:
                        analysis = json.loads(exec_record.get("analysis_result"))
                        exec_props["fail_step"] = analysis.get("fail_step", "")
                        exec_props["root_cause"] = analysis.get("root_cause", "")[:500]
                        exec_props["suggestion"] = analysis.get("suggestion", "")[:500]
                    except json.JSONDecodeError:
                        pass

                # 通过 StorageRouter 写入 Neo4j（执行结果属性）
                self.storage.neo4j_write(
                    f"MATCH (s:{LABEL_SCRIPT} {{id: $id}}) "
                    f"SET s.exec_status = $exec_status, "
                    f"s.exec_duration = $exec_duration, "
                    f"s.exec_success_count = $exec_success_count, "
                    f"s.exec_failed_count = $exec_failed_count, "
                    f"s.exec_error = $exec_error, "
                    f"s.fail_step = $fail_step, "
                    f"s.root_cause = $root_cause, "
                    f"s.suggestion = $suggestion",
                    **{"id": script_id, **exec_props},
                )

            # 5. 反馈属性（附加到Script节点）
            if feedback and script_content:
                script_id = f"script_{script_model.get('id')}" if script_model else f"script_task_{task_id}"
                feedback_props = {
                    "feedback_score": feedback.get("score") or 0,
                    "feedback_comment": (feedback.get("comment") or "")[:500],
                    "feedback_accepted": "true" if feedback.get("accepted") else "false",
                    "feedback_failure_reasons": "",
                }
                if feedback.get("failure_analysis"):
                    try:
                        fa = json.loads(feedback.get("failure_analysis"))
                        feedback_props["feedback_failure_reasons"] = json.dumps(fa.get("failure_reasons", []), ensure_ascii=False)[:500]
                    except json.JSONDecodeError:
                        pass

                # 通过 StorageRouter 写入 Neo4j（反馈属性）
                self.storage.neo4j_write(
                    f"MATCH (s:{LABEL_SCRIPT} {{id: $id}}) "
                    f"SET s.feedback_score = $feedback_score, "
                    f"s.feedback_comment = $feedback_comment, "
                    f"s.feedback_accepted = $feedback_accepted, "
                    f"s.feedback_failure_reasons = $feedback_failure_reasons",
                    **{"id": script_id, **feedback_props},
                )

            log.info(f"KnowledgeUpdate | Neo4j更新完成 | nodes={result['nodes']} rels={result['relationships']}")

        except Exception as e:
            log.warning(f"KnowledgeUpdate | Neo4j更新异常: {e}")
            result["skipped"] += 1

        return result

    def incremental_update(self, task_ids: List[int] = None) -> Dict[str, Any]:
        """
        批量增量更新知识库

        扫描所有已完成的任务，将未入库的数据补充入库

        Args:
            task_ids: 指定任务ID列表，为None则扫描全部

        Returns:
            更新统计
        """
        stats = {
            "total": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
        }

        router = get_context_router()
        try:
            from app.models.requirement_task import RequirementStatus

            result = router.query(
                "",
                ContextType.REQUIREMENT_TASK,
                top_k=200,
                filters={"status": RequirementStatus.COMPLETED},
            )
            req_tasks = result.get("results", [])

            # 客户端过滤：task_id 不为 None
            req_tasks = [r for r in req_tasks if r.get("task_id") is not None]

            # 如果指定了 task_ids，进一步过滤
            if task_ids:
                req_tasks = [r for r in req_tasks if r.get("task_id") in task_ids]

            stats["total"] = len(req_tasks)

            for req_task in req_tasks:
                try:
                    update_result = self.update_after_execution(
                        requirement_id=int(req_task.get("id")),
                        task_id=req_task.get("task_id"),
                    )
                    if update_result["success"]:
                        stats["updated"] += 1
                    else:
                        stats["skipped"] += 1
                        stats["errors"].extend(update_result.get("errors", []))
                except Exception as e:
                    stats["skipped"] += 1
                    stats["errors"].append(f"task={req_task.get('task_id')}: {e}")

        except Exception as e:
            stats["errors"].append(str(e))

        log.info(f"KnowledgeUpdate | 批量增量更新 | total={stats['total']} updated={stats['updated']} skipped={stats['skipped']}")
        return stats
