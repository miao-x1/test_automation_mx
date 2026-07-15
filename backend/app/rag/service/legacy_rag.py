"""
LegacyRAGService - 旧版检索增强生成服务

协调EmbeddingAgent和RetrievalAgent，提供：
1. 索引：读取统一元素库 → 生成向量 → 写入Milvus
2. 检索：自然语言查询 → 向量检索 → 返回相关元素
3. SSE实时输出

从 app/services/rag_service.py 迁移。
"""
import json
import queue
import threading
from typing import AsyncGenerator, Dict, Any, List, Optional
from app.core.logger import log
from app.db.database import SessionLocal
from app.models.ui_element import UIElement
from app.models.task import Task
from app.agents.factory import AgentRegistry


class LegacyRAGService:
    """旧版RAG服务（Milvus索引/检索）"""

    @staticmethod
    def get_task_elements(db, task_id: int) -> List[Dict[str, Any]]:
        """获取任务的统一元素（只索引approved的）"""
        elements = db.query(UIElement).filter(
            UIElement.task_id == task_id,
            UIElement.kb_status == "approved",
        ).all()
        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "text": e.text,
                "source": e.source,
                "locator": e.locator,
                "xpath": e.xpath,
                "css_selector": e.css_selector,
                "element_id": e.element_id,
                "element_class": e.element_class,
                "element_name": e.element_name,
                "placeholder": e.placeholder,
                "href": e.href,
                "aria_label": e.aria_label,
                "role": e.role,
                "data_testid": e.data_testid,
                "page_url": e.page_url,
                "confidence": e.confidence,
            }
            for e in elements
        ]

    @staticmethod
    def get_all_elements(db) -> List[Dict[str, Any]]:
        """获取所有统一元素（只索引approved的）"""
        elements = db.query(UIElement).filter(UIElement.kb_status == "approved").all()
        return [
            {
                "id": e.id,
                "task_id": e.task_id,
                "name": e.name,
                "type": e.type,
                "text": e.text,
                "source": e.source,
                "locator": e.locator,
                "xpath": e.xpath,
                "css_selector": e.css_selector,
                "element_id": e.element_id,
                "element_class": e.element_class,
                "element_name": e.element_name,
                "placeholder": e.placeholder,
                "href": e.href,
                "aria_label": e.aria_label,
                "role": e.role,
                "data_testid": e.data_testid,
                "page_url": e.page_url,
                "confidence": e.confidence,
            }
            for e in elements
        ]

    @staticmethod
    async def index_task(task_id: int) -> AsyncGenerator[str, None]:
        """
        索引指定任务的元素到Milvus

        流程：读取元素 → 生成向量 → 写入Milvus
        SSE实时输出进度
        """
        db = SessionLocal()
        try:
            # 验证任务存在
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                yield json.dumps({"step": "错误", "progress": 0, "message": f"任务 {task_id} 不存在"}, ensure_ascii=False)
                return

            # 读取元素
            elements = LegacyRAGService.get_task_elements(db, task_id)
            if not elements:
                yield json.dumps({"step": "Embedding完成", "progress": 100, "message": f"任务 {task_id} 没有可索引的元素"}, ensure_ascii=False)
                return

            # 使用队列实现Agent → SSE通信
            log_queue = queue.Queue()
            result_holder = {"done": False, "error": None}

            def on_log(data: dict):
                log_queue.put(data)

            def run_embedding():
                try:
                    import asyncio
                    agent = AgentRegistry.create("embedding_agent")

                    # 在子线程中创建新的事件循环
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        async def _run():
                            async for log_data in agent.embed_elements(elements, task_id, on_log=on_log):
                                on_log(log_data)
                        loop.run_until_complete(_run())
                    finally:
                        loop.close()

                except Exception as e:
                    log.error(f"Embedding执行异常: {e}", exc_info=True)
                    result_holder["error"] = str(e)
                finally:
                    result_holder["done"] = True
                    log_queue.put({"__done__": True})

            # 启动子线程
            agent_thread = threading.Thread(target=run_embedding, daemon=True)
            agent_thread.start()

            # 实时从队列读取并推送SSE
            while True:
                try:
                    log_data = log_queue.get(timeout=0.5)
                except queue.Empty:
                    if result_holder["done"] or not agent_thread.is_alive():
                        break
                    continue

                if log_data.get("__done__"):
                    break

                yield json.dumps({
                    "step": log_data.get("step", "处理中"),
                    "progress": log_data.get("progress", 0),
                    "message": log_data.get("message", ""),
                }, ensure_ascii=False)

            # 检查是否有错误
            if result_holder["error"]:
                yield json.dumps({"step": "Embedding失败", "progress": 100, "message": result_holder["error"]}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    async def index_all() -> AsyncGenerator[str, None]:
        """
        索引所有任务的元素到Milvus

        流程：读取所有元素 → 生成向量 → 写入Milvus
        """
        db = SessionLocal()
        try:
            elements = LegacyRAGService.get_all_elements(db)
            if not elements:
                yield json.dumps({"step": "Embedding完成", "progress": 100, "message": "没有可索引的元素"}, ensure_ascii=False)
                return

            # 按task_id分组
            from collections import defaultdict
            task_groups = defaultdict(list)
            for elem in elements:
                task_groups[elem["task_id"]].append(elem)

            total_tasks = len(task_groups)
            yield json.dumps({"step": "开始索引", "progress": 5, "message": f"共 {total_tasks} 个任务，{len(elements)} 个元素"}, ensure_ascii=False)

            # 使用队列实现Agent → SSE通信
            log_queue = queue.Queue()
            result_holder = {"done": False, "error": None}

            def on_log(data: dict):
                log_queue.put(data)

            def run_embedding():
                try:
                    import asyncio
                    agent = AgentRegistry.create("embedding_agent")

                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        for i, (tid, elems) in enumerate(task_groups.items()):
                            progress_base = int((i / total_tasks) * 100)

                            async def _run():
                                async for log_data in agent.embed_elements(elems, tid, on_log=on_log):
                                    # 调整进度：在整体进度范围内
                                    adjusted = log_data.copy()
                                    if "progress" in adjusted:
                                        adjusted["progress"] = progress_base + int(adjusted["progress"] * (100 - progress_base) / 100)
                                    on_log(adjusted)
                            loop.run_until_complete(_run())
                    finally:
                        loop.close()

                except Exception as e:
                    log.error(f"Embedding执行异常: {e}", exc_info=True)
                    result_holder["error"] = str(e)
                finally:
                    result_holder["done"] = True
                    log_queue.put({"__done__": True})

            agent_thread = threading.Thread(target=run_embedding, daemon=True)
            agent_thread.start()

            while True:
                try:
                    log_data = log_queue.get(timeout=0.5)
                except queue.Empty:
                    if result_holder["done"] or not agent_thread.is_alive():
                        break
                    continue

                if log_data.get("__done__"):
                    break

                yield json.dumps({
                    "step": log_data.get("step", "处理中"),
                    "progress": log_data.get("progress", 0),
                    "message": log_data.get("message", ""),
                }, ensure_ascii=False)

            if result_holder["error"]:
                yield json.dumps({"step": "Embedding失败", "progress": 100, "message": result_holder["error"]}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    async def index_all_incremental() -> AsyncGenerator[str, None]:
        """
        增量索引所有集合（元素、用例、脚本）

        旧的保留不动，只添加新的
        """
        from app.db.milvus_client import (
            ensure_all_collections, COLLECTION_NAME,
            CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME,
        )

        client = ensure_all_collections()
        embed_agent = AgentRegistry.create("embedding_agent")

        total_indexed = 0

        # ===== 阶段1: 增量索引元素 =====
        yield json.dumps({"step": "索引元素", "progress": 5, "message": "正在检查元素集合..."}, ensure_ascii=False)
        try:
            db = SessionLocal()
            try:
                all_elements = LegacyRAGService.get_all_elements(db)
                # 获取已索引的task_id列表
                indexed_task_ids = set()
                if client.has_collection(COLLECTION_NAME):
                    try:
                        client.load_collection(COLLECTION_NAME)
                        result = client.query(COLLECTION_NAME, filter="id >= 0", output_fields=["task_id"], limit=10000)
                        indexed_task_ids = {r["task_id"] for r in result}
                    except Exception:
                        pass

                # 过滤出未索引的元素
                new_elements = [e for e in all_elements if e["task_id"] not in indexed_task_ids]

                if new_elements:
                    yield json.dumps({"step": "索引元素", "progress": 10, "message": f"元素: 已索引{len(all_elements) - len(new_elements)}个, 新增{len(new_elements)}个"}, ensure_ascii=False)

                    # 按task_id分组索引
                    from collections import defaultdict
                    task_groups = defaultdict(list)
                    for elem in new_elements:
                        task_groups[elem["task_id"]].append(elem)

                    for tid, elems in task_groups.items():
                        descriptions = []
                        valid_data = []
                        for elem in elems:
                            name = elem.get("name", "")
                            etype = elem.get("type", "")
                            locator = elem.get("locator", "")
                            page = elem.get("page_name", "")
                            desc = f"页面: {page} | 元素: {name} | 类型: {etype} | 定位器: {locator}"
                            if desc.strip():
                                descriptions.append(desc)
                                valid_data.append({
                                    "task_id": tid,
                                    "page_name": (page or "")[:255],
                                    "element_name": (name or "")[:255],
                                    "element_type": (etype or "")[:50],
                                    "locator": (locator or "")[:1024],
                                    "description": desc[:2048],
                                })

                        if valid_data:
                            embeddings = embed_agent._embed(descriptions)
                            data = []
                            for d, emb in zip(valid_data, embeddings):
                                data.append({**d, "embedding": emb})
                            client.insert(collection_name=COLLECTION_NAME, data=data)
                            total_indexed += len(data)

                    yield json.dumps({"step": "元素索引完成", "progress": 30, "message": f"元素索引完成, 新增{len(new_elements)}个"}, ensure_ascii=False)
                else:
                    yield json.dumps({"step": "元素索引完成", "progress": 30, "message": f"元素: 无新增, 已全部索引"}, ensure_ascii=False)
            finally:
                db.close()
        except Exception as e:
            log.warning(f"增量索引元素失败: {e}")
            yield json.dumps({"step": "元素索引失败", "progress": 30, "message": f"元素索引失败: {e}"}, ensure_ascii=False)

        # ===== 阶段2: 增量索引用例 =====
        yield json.dumps({"step": "索引用例", "progress": 35, "message": "正在检查用例集合..."}, ensure_ascii=False)
        try:
            db = SessionLocal()
            try:
                from app.models.requirement_task import RequirementTask
                req_tasks = db.query(RequirementTask).filter(
                    RequirementTask.generated_case.isnot(None),
                    RequirementTask.kb_status == "approved",
                ).all()

                # 获取已索引的task_id列表
                indexed_case_task_ids = set()
                if client.has_collection(CASE_COLLECTION_NAME):
                    try:
                        client.load_collection(CASE_COLLECTION_NAME)
                        result = client.query(CASE_COLLECTION_NAME, filter="id >= 0", output_fields=["task_id"], limit=10000)
                        indexed_case_task_ids = {r["task_id"] for r in result}
                    except Exception:
                        pass

                # 过滤出未索引的
                new_req_tasks = [rt for rt in req_tasks if (rt.task_id or 0) not in indexed_case_task_ids]

                if new_req_tasks:
                    descriptions = []
                    valid_data = []
                    for rt in new_req_tasks:
                        try:
                            case = json.loads(rt.generated_case) if rt.generated_case else {}
                        except json.JSONDecodeError:
                            case = {}
                        case_name = case.get("case_name", "")
                        description = case.get("description", "")
                        steps = case.get("steps", [])
                        desc_parts = []
                        if case_name:
                            desc_parts.append(f"用例: {case_name}")
                        if description:
                            desc_parts.append(f"描述: {description}")
                        if rt.requirement:
                            desc_parts.append(f"需求: {rt.requirement}")
                        for s in steps[:5]:
                            step_desc = s.get("step", s.get("description", "")) if isinstance(s, dict) else str(s)
                            if step_desc:
                                desc_parts.append(f"步骤: {step_desc}")
                        desc = " | ".join(desc_parts)
                        if desc.strip():
                            descriptions.append(desc)
                            steps_json = json.dumps(steps, ensure_ascii=False)
                            if len(steps_json) > 4096:
                                steps_json = steps_json[:4096]
                            valid_data.append({
                                "task_id": rt.task_id or 0,
                                "case_name": (case_name or "")[:255],
                                "description": (description or "")[:2048],
                                "steps": steps_json,
                            })

                    if valid_data:
                        yield json.dumps({"step": "索引用例", "progress": 45, "message": f"用例: 已索引{len(req_tasks) - len(new_req_tasks)}个, 新增{len(valid_data)}个"}, ensure_ascii=False)
                        embeddings = embed_agent._embed(descriptions)
                        data = []
                        for d, emb in zip(valid_data, embeddings):
                            data.append({**d, "embedding": emb})
                        client.insert(collection_name=CASE_COLLECTION_NAME, data=data)
                        total_indexed += len(data)

                    yield json.dumps({"step": "用例索引完成", "progress": 60, "message": f"用例索引完成, 新增{len(valid_data)}个"}, ensure_ascii=False)
                else:
                    yield json.dumps({"step": "用例索引完成", "progress": 60, "message": f"用例: 无新增, 已全部索引"}, ensure_ascii=False)
            finally:
                db.close()
        except Exception as e:
            log.warning(f"增量索引用例失败: {e}")
            yield json.dumps({"step": "用例索引失败", "progress": 60, "message": f"用例索引失败: {e}"}, ensure_ascii=False)

        # ===== 阶段3: 增量索引脚本 =====
        yield json.dumps({"step": "索引脚本", "progress": 65, "message": "正在检查脚本集合..."}, ensure_ascii=False)
        try:
            db = SessionLocal()
            try:
                from app.models.script import Script as ScriptModel
                scripts = db.query(ScriptModel).filter(ScriptModel.kb_status == "approved").all()

                # 获取已索引的task_id列表
                indexed_script_task_ids = set()
                if client.has_collection(SCRIPT_COLLECTION_NAME):
                    try:
                        client.load_collection(SCRIPT_COLLECTION_NAME)
                        result = client.query(SCRIPT_COLLECTION_NAME, filter="id >= 0", output_fields=["task_id"], limit=10000)
                        indexed_script_task_ids = {r["task_id"] for r in result}
                    except Exception:
                        pass

                # 过滤出未索引的
                new_scripts = [s for s in scripts if s.task_id not in indexed_script_task_ids]

                if new_scripts:
                    descriptions = []
                    valid_data = []
                    for s in new_scripts:
                        content = s.script_content or ""
                        desc = f"脚本类型: {s.script_type} | 语言: {s.script_language} | 内容预览: {content[:500]}"
                        if desc.strip():
                            descriptions.append(desc)
                            sc = content[:8192] if len(content) > 8192 else content
                            valid_data.append({
                                "task_id": s.task_id,
                                "script_name": f"task_{s.task_id}_script",
                                "script_content": sc,
                                "description": f"任务{s.task_id}的{s.script_type}脚本",
                            })

                    if valid_data:
                        yield json.dumps({"step": "索引脚本", "progress": 75, "message": f"脚本: 已索引{len(scripts) - len(new_scripts)}个, 新增{len(valid_data)}个"}, ensure_ascii=False)
                        embeddings = embed_agent._embed(descriptions)
                        data = []
                        for d, emb in zip(valid_data, embeddings):
                            data.append({**d, "embedding": emb})
                        client.insert(collection_name=SCRIPT_COLLECTION_NAME, data=data)
                        total_indexed += len(data)

                    yield json.dumps({"step": "脚本索引完成", "progress": 90, "message": f"脚本索引完成, 新增{len(valid_data)}个"}, ensure_ascii=False)
                else:
                    yield json.dumps({"step": "脚本索引完成", "progress": 90, "message": f"脚本: 无新增, 已全部索引"}, ensure_ascii=False)
            finally:
                db.close()
        except Exception as e:
            log.warning(f"增量索引脚本失败: {e}")
            yield json.dumps({"step": "脚本索引失败", "progress": 90, "message": f"脚本索引失败: {e}"}, ensure_ascii=False)

        yield json.dumps({"step": "全部索引完成", "progress": 100, "message": f"增量索引完成, 共新增{total_indexed}条向量"}, ensure_ascii=False)

    @staticmethod
    async def search(query: str, top_k: int = 10, task_id: Optional[int] = None) -> AsyncGenerator[str, None]:
        """
        自然语言检索相关元素

        流程：查询文本 → 生成向量 → Milvus检索 → 返回结果
        SSE实时输出进度
        """
        log_queue = queue.Queue()
        result_holder = {"done": False, "error": None, "final_data": None}

        def on_log(data: dict):
            log_queue.put(data)

        def run_search():
            try:
                import asyncio
                agent = AgentRegistry.create("retrieval_agent")

                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    async def _run():
                        async for log_data in agent.search(query, top_k=top_k, task_id=task_id, on_log=on_log):
                            on_log(log_data)
                            if "data" in log_data:
                                result_holder["final_data"] = log_data["data"]
                    loop.run_until_complete(_run())
                finally:
                    loop.close()

            except Exception as e:
                log.error(f"检索执行异常: {e}", exc_info=True)
                result_holder["error"] = str(e)
            finally:
                result_holder["done"] = True
                log_queue.put({"__done__": True})

        agent_thread = threading.Thread(target=run_search, daemon=True)
        agent_thread.start()

        while True:
            try:
                log_data = log_queue.get(timeout=0.5)
            except queue.Empty:
                if result_holder["done"] or not agent_thread.is_alive():
                    break
                continue

            if log_data.get("__done__"):
                break

            output = {
                "step": log_data.get("step", "检索中"),
                "progress": log_data.get("progress", 0),
                "message": log_data.get("message", ""),
            }
            if "data" in log_data:
                output["data"] = log_data["data"]
            yield json.dumps(output, ensure_ascii=False)

        if result_holder["error"]:
            yield json.dumps({"step": "检索失败", "progress": 100, "message": result_holder["error"]}, ensure_ascii=False)

    @staticmethod
    def get_collection_stats() -> Dict[str, Any]:
        """获取Milvus所有集合统计信息"""
        try:
            from app.db.milvus_client import ensure_all_collections, COLLECTION_NAME, CASE_COLLECTION_NAME, SCRIPT_COLLECTION_NAME
            client = ensure_all_collections()

            if client is None:
                return {
                    "collections": [
                        {"name": COLLECTION_NAME, "row_count": 0, "type": "元素"},
                        {"name": CASE_COLLECTION_NAME, "row_count": 0, "type": "用例"},
                        {"name": SCRIPT_COLLECTION_NAME, "row_count": 0, "type": "脚本"},
                    ],
                    "total_count": 0,
                    "status": "unavailable",
                }

            # 元素集合
            elem_stats = client.get_collection_stats(COLLECTION_NAME)
            elem_count = elem_stats.get("row_count", 0)

            # 用例集合
            case_count = 0
            if client.has_collection(CASE_COLLECTION_NAME):
                case_stats = client.get_collection_stats(CASE_COLLECTION_NAME)
                case_count = case_stats.get("row_count", 0)

            # 脚本集合
            script_count = 0
            if client.has_collection(SCRIPT_COLLECTION_NAME):
                script_stats = client.get_collection_stats(SCRIPT_COLLECTION_NAME)
                script_count = script_stats.get("row_count", 0)

            return {
                "collections": [
                    {"name": COLLECTION_NAME, "row_count": elem_count, "type": "元素"},
                    {"name": CASE_COLLECTION_NAME, "row_count": case_count, "type": "用例"},
                    {"name": SCRIPT_COLLECTION_NAME, "row_count": script_count, "type": "脚本"},
                ],
                "total_count": elem_count + case_count + script_count,
                "status": "ok",
            }
        except Exception as e:
            return {
                "collections": [],
                "total_count": 0,
                "status": f"error: {str(e)}",
            }

    @staticmethod
    async def index_cases() -> AsyncGenerator[str, None]:
        """
        索引历史测试用例到Milvus

        从数据库读取需求任务中的generated_case，生成向量写入test_case_vector
        """
        db = SessionLocal()
        try:
            from app.models.requirement_task import RequirementTask
            from app.db.milvus_client import ensure_all_collections, CASE_COLLECTION_NAME
            from app.core.config import settings

            # 读取有生成用例的需求任务
            req_tasks = db.query(RequirementTask).filter(
                RequirementTask.generated_case.isnot(None)
            ).all()

            if not req_tasks:
                yield json.dumps({"step": "索引完成", "progress": 100, "message": "没有可索引的测试用例"}, ensure_ascii=False)
                return

            yield json.dumps({"step": "开始索引用例", "progress": 10, "message": f"共 {len(req_tasks)} 个测试用例"}, ensure_ascii=False)

            # 构建描述文本
            descriptions = []
            valid_data = []
            for rt in req_tasks:
                try:
                    case = json.loads(rt.generated_case) if rt.generated_case else {}
                except json.JSONDecodeError:
                    case = {}

                case_name = case.get("case_name", "")
                description = case.get("description", "")
                steps = case.get("steps", [])

                # 构建描述文本
                desc_parts = []
                if case_name:
                    desc_parts.append(f"用例: {case_name}")
                if description:
                    desc_parts.append(f"描述: {description}")
                if rt.requirement:
                    desc_parts.append(f"需求: {rt.requirement}")
                for s in steps[:5]:
                    step_desc = s.get("step", s.get("description", "")) if isinstance(s, dict) else str(s)
                    if step_desc:
                        desc_parts.append(f"步骤: {step_desc}")

                desc = " | ".join(desc_parts)
                if desc.strip():
                    descriptions.append(desc)
                    steps_json = json.dumps(steps, ensure_ascii=False)
                    if len(steps_json) > 4096:
                        steps_json = steps_json[:4096]
                    if len(case_name) > 255:
                        case_name = case_name[:255]
                    if len(description) > 2048:
                        description = description[:2048]
                    valid_data.append({
                        "task_id": rt.task_id or 0,
                        "case_name": case_name,
                        "description": description,
                        "steps": steps_json,
                    })

            if not valid_data:
                yield json.dumps({"step": "索引完成", "progress": 100, "message": "没有有效的用例描述"}, ensure_ascii=False)
                return

            # 生成向量
            yield json.dumps({"step": "生成向量", "progress": 40, "message": f"正在为 {len(descriptions)} 个用例生成向量..."}, ensure_ascii=False)

            # 使用EmbeddingAgent的embed方法
            embed_agent = AgentRegistry.create("embedding_agent")
            embeddings = embed_agent._embed(descriptions)

            yield json.dumps({"step": "向量生成完成", "progress": 70, "message": f"已生成 {len(embeddings)} 个向量"}, ensure_ascii=False)

            # 写入Milvus
            client = ensure_all_collections()
            data = []
            for i, (d, emb) in enumerate(zip(valid_data, embeddings)):
                data.append({
                    "task_id": d["task_id"],
                    "case_name": d["case_name"],
                    "description": d["description"],
                    "steps": d["steps"],
                    "embedding": emb,
                })

            yield json.dumps({"step": "写入Milvus", "progress": 85, "message": f"正在写入 {len(data)} 条用例向量..."}, ensure_ascii=False)
            client.insert(collection_name=CASE_COLLECTION_NAME, data=data)

            yield json.dumps({"step": "索引完成", "progress": 100, "message": f"成功索引 {len(data)} 个测试用例"}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    async def index_scripts() -> AsyncGenerator[str, None]:
        """
        索引历史脚本到Milvus

        从数据库读取Script，生成向量写入script_vector
        """
        db = SessionLocal()
        try:
            from app.models.script import Script as ScriptModel
            from app.db.milvus_client import ensure_all_collections, SCRIPT_COLLECTION_NAME

            scripts = db.query(ScriptModel).all()
            if not scripts:
                yield json.dumps({"step": "索引完成", "progress": 100, "message": "没有可索引的脚本"}, ensure_ascii=False)
                return

            yield json.dumps({"step": "开始索引脚本", "progress": 10, "message": f"共 {len(scripts)} 个脚本"}, ensure_ascii=False)

            # 构建描述文本
            descriptions = []
            valid_data = []
            for s in scripts:
                content = s.script_content or ""
                # 截取脚本前500字符作为描述
                desc = f"脚本类型: {s.script_type} | 语言: {s.script_language} | 内容预览: {content[:500]}"
                if desc.strip():
                    descriptions.append(desc)
                    script_content = content[:8192] if len(content) > 8192 else content
                    valid_data.append({
                        "task_id": s.task_id,
                        "script_name": f"task_{s.task_id}_script",
                        "script_content": script_content,
                        "description": f"任务{s.task_id}的{s.script_type}脚本",
                    })

            if not valid_data:
                yield json.dumps({"step": "索引完成", "progress": 100, "message": "没有有效的脚本描述"}, ensure_ascii=False)
                return

            # 生成向量
            yield json.dumps({"step": "生成向量", "progress": 40, "message": f"正在为 {len(descriptions)} 个脚本生成向量..."}, ensure_ascii=False)

            embed_agent = AgentRegistry.create("embedding_agent")
            embeddings = embed_agent._embed(descriptions)

            yield json.dumps({"step": "向量生成完成", "progress": 70, "message": f"已生成 {len(embeddings)} 个向量"}, ensure_ascii=False)

            # 写入Milvus
            client = ensure_all_collections()
            data = []
            for i, (d, emb) in enumerate(zip(valid_data, embeddings)):
                data.append({
                    "task_id": d["task_id"],
                    "script_name": d["script_name"],
                    "script_content": d["script_content"],
                    "description": d["description"],
                    "embedding": emb,
                })

            yield json.dumps({"step": "写入Milvus", "progress": 85, "message": f"正在写入 {len(data)} 条脚本向量..."}, ensure_ascii=False)
            client.insert(collection_name=SCRIPT_COLLECTION_NAME, data=data)

            yield json.dumps({"step": "索引完成", "progress": 100, "message": f"成功索引 {len(data)} 个脚本"}, ensure_ascii=False)

        finally:
            db.close()
