"""
PageKnowledgeService - 页面知识库服务

上传页面截图后自动完成：
  OCR → 页面描述 → 页面元素（按钮/输入框/菜单）→ 页面关系
  → MySQL + Milvus + Neo4j

核心能力：
  1. upload_screenshot: 上传截图 → OCR → LLM分析 → 三库存储
  2. get_page_elements: 按页面名称查询所有元素（不需要再次OCR）
  3. search_pages: 按关键词/向量搜索页面
  4. get_page_relations: 查询页面间关系
"""
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.models.page_knowledge import (
    PageKnowledge,
    PageKnowledgeElement,
    PageKnowledgeStatus,
)
from app.rag.service.tri_store_coordinator import get_tri_store_coordinator

logger = logging.getLogger(__name__)


class PageKnowledgeService:
    """页面知识库服务

    管理页面知识的完整生命周期：
      上传 → OCR → LLM分析 → 元素提取 → 关系建模 → 三库存储
    """

    def __init__(self):
        self._tri_store = get_tri_store_coordinator()

    # ------------------------------------------------------------------
    # 上传截图 → 完整处理管道
    # ------------------------------------------------------------------

    async def upload_screenshot(
        self,
        screenshot_path: str,
        page_name: str = "",
        page_url: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """上传截图并自动完成完整处理管道

        流程：OCR → 页面描述 → 元素提取 → 关系建模 → MySQL + Milvus + Neo4j

        Returns:
            包含 page_knowledge_id, elements, status 等信息的字典
        """
        start_time = time.time()
        errors: List[str] = []

        if not page_name:
            page_name = os.path.splitext(os.path.basename(screenshot_path))[0]

        logger.info(f"[PageKnowledge] 开始处理截图: {page_name} path={screenshot_path}")

        # 1. 创建 MySQL 记录
        db = SessionLocal()
        try:
            pk = PageKnowledge(
                page_name=page_name,
                page_url=page_url,
                screenshot_path=screenshot_path,
                status=PageKnowledgeStatus.OCR_PROCESSING,
                project_id=project_id,
                created_by=str(user_id) if user_id else None,
            )
            db.add(pk)
            db.flush()
            pk_id = pk.id
            db.commit()
            db.refresh(pk)
            db.expunge(pk)
        except Exception as e:
            db.rollback()
            logger.error(f"[PageKnowledge] 创建记录失败: {e}")
            return {"status": "failed", "error": str(e)}
        finally:
            db.close()

        # 2. OCR 识别
        try:
            ocr_result = await self._do_ocr(screenshot_path)
            ocr_text = ocr_result.get("text", "")
            ocr_confidence = ocr_result.get("confidence", 0.0)
            self._update_status(pk_id, PageKnowledgeStatus.OCR_DONE,
                               ocr_text=ocr_text, ocr_confidence=ocr_confidence)
            logger.info(f"[PageKnowledge] OCR完成: {page_name} text_len={len(ocr_text)}")
        except Exception as e:
            errors.append(f"OCR失败: {e}")
            self._update_status(pk_id, PageKnowledgeStatus.FAILED,
                               error_message=f"OCR失败: {e}")
            return {"page_knowledge_id": pk_id, "status": "failed", "errors": errors}

        # 3. LLM 分析（页面描述 + 元素提取 + 关系建模）
        try:
            self._update_status(pk_id, PageKnowledgeStatus.ANALYZING)
            analysis = await self._analyze_page(page_name, page_url, ocr_text)
            self._update_status(pk_id, PageKnowledgeStatus.ANALYZED,
                               page_description=analysis.get("page_description", ""),
                               page_type=analysis.get("page_type", ""),
                               module=analysis.get("module", ""),
                               elements_json=json.dumps(analysis.get("elements", []), ensure_ascii=False),
                               buttons_json=json.dumps(analysis.get("buttons", []), ensure_ascii=False),
                               inputs_json=json.dumps(analysis.get("inputs", []), ensure_ascii=False),
                               menus_json=json.dumps(analysis.get("menus", []), ensure_ascii=False),
                               relations_json=json.dumps(analysis.get("relations", []), ensure_ascii=False))
            logger.info(
                f"[PageKnowledge] LLM分析完成: {page_name} "
                f"elements={len(analysis.get('elements', []))} "
                f"buttons={len(analysis.get('buttons', []))} "
                f"inputs={len(analysis.get('inputs', []))} "
                f"menus={len(analysis.get('menus', []))} "
                f"relations={len(analysis.get('relations', []))}"
            )
        except Exception as e:
            errors.append(f"LLM分析失败: {e}")
            self._update_status(pk_id, PageKnowledgeStatus.FAILED,
                               error_message=f"LLM分析失败: {e}")
            return {"page_knowledge_id": pk_id, "status": "failed", "errors": errors}

        # 4. 展开元素到独立行（便于查询）
        try:
            self._save_elements(pk_id, analysis.get("elements", []))
        except Exception as e:
            errors.append(f"元素保存失败: {e}")

        # 5. 三库存储（Milvus 向量 + Neo4j 图谱）
        try:
            self._update_status(pk_id, PageKnowledgeStatus.STORING)
            await self._store_to_vector_graph(pk_id, page_name, page_url, analysis)
            self._update_status(pk_id, PageKnowledgeStatus.STORED,
                               neo4j_synced=True)
            logger.info(f"[PageKnowledge] 三库存储完成: {page_name}")
        except Exception as e:
            errors.append(f"三库存储失败: {e}")

        # 6. 更新最终状态
        final_status = PageKnowledgeStatus.STORED if not errors else PageKnowledgeStatus.FAILED
        self._update_status(pk_id, final_status)

        duration = time.time() - start_time
        result = {
            "page_knowledge_id": pk_id,
            "page_name": page_name,
            "page_url": page_url,
            "page_type": analysis.get("page_type", ""),
            "module": analysis.get("module", ""),
            "ocr_text_length": len(ocr_text),
            "elements_count": len(analysis.get("elements", [])),
            "buttons_count": len(analysis.get("buttons", [])),
            "inputs_count": len(analysis.get("inputs", [])),
            "menus_count": len(analysis.get("menus", [])),
            "relations_count": len(analysis.get("relations", [])),
            "status": final_status.value if hasattr(final_status, "value") else str(final_status),
            "duration": round(duration, 2),
            "errors": errors,
        }
        logger.info(f"[PageKnowledge] 处理完成: {result}")
        return result

    # ------------------------------------------------------------------
    # OCR 识别
    # ------------------------------------------------------------------

    async def _do_ocr(self, image_path: str) -> Dict[str, Any]:
        """执行 OCR 识别

        优先使用 dashscope 多模态模型（视觉理解），
        降级使用本地 OCR（如 paddleocr/tesseract，如果可用）。
        """
        try:
            return await self._ocr_with_llm(image_path)
        except Exception as e:
            logger.warning(f"[PageKnowledge] LLM OCR 失败，降级: {e}")
            return await self._ocr_fallback(image_path)

    async def _ocr_with_llm(self, image_path: str) -> Dict[str, Any]:
        """使用 LLM 多模态能力进行 OCR + 页面理解"""
        import base64
        import httpx
        from app.core.config import settings

        # 读取图片并转 base64
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")

        api_key = os.getenv("QWEN_API_KEY") or os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise RuntimeError("未配置 QWEN_API_KEY，无法使用LLM OCR")

        # 使用通义千问 VL 模型
        url = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "qwen-vl-plus",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{image_b64}"},
                        },
                        {
                            "type": "text",
                            "text": (
                                "请分析这个页面截图，完成以下任务：\n"
                                "1. 识别页面中所有可见文本（OCR）\n"
                                "2. 描述这个页面的功能和用途\n"
                                "3. 识别页面类型（login/list/detail/form/dashboard/error/other）\n"
                                "4. 识别所属模块（auth/user/order/admin等）\n"
                                "5. 提取所有可交互元素，分类为：\n"
                                "   - buttons: 按钮列表[{name, text, locator}]\n"
                                "   - inputs: 输入框列表[{name, type, placeholder, locator, is_required}]\n"
                                "   - menus: 菜单项[{name, text, locator}]\n"
                                "   - links: 链接[{name, text, locator}]\n"
                                "   - other: 其他元素[{name, type, locator}]\n"
                                "6. 分析页面可能跳转到哪些页面（页面关系）\n"
                                "   relations: [{target_page, relation_type, trigger}]\n\n"
                                "返回JSON格式:\n"
                                '{"ocr_text": "页面所有可见文本", '
                                '"page_description": "页面功能描述", '
                                '"page_type": "login|list|detail|form|dashboard|error|other", '
                                '"module": "auth|user|order|admin|...", '
                                '"elements": [{"name":"登录按钮","type":"button","text":"登录","locator":"button[type=submit]"}], '
                                '"buttons": [{"name":"登录按钮","text":"登录","locator":"button[type=submit]"}], '
                                '"inputs": [{"name":"用户名","type":"text","placeholder":"请输入用户名","locator":"input[name=username]","is_required":true}], '
                                '"menus": [{"name":"用户管理","text":"用户管理","locator":"a[href=/user]"}], '
                                '"relations": [{"target_page":"首页","relation_type":"navigate","trigger":"登录成功"}]}'
                            ),
                        }
                    ],
                }
            ],
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            # 尝试解析 JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # 尝试提取 JSON 块
                import re
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    result = {"ocr_text": content, "page_description": content[:200]}

            result["confidence"] = 0.9
            return result

    async def _ocr_fallback(self, image_path: str) -> Dict[str, Any]:
        """降级 OCR（无API key时）"""
        return {
            "text": "",
            "confidence": 0.0,
            "ocr_text": "",
            "page_description": "无法执行OCR（未配置API Key）",
            "page_type": "unknown",
            "module": "unknown",
            "elements": [],
            "buttons": [],
            "inputs": [],
            "menus": [],
            "relations": [],
        }

    # ------------------------------------------------------------------
    # LLM 页面分析
    # ------------------------------------------------------------------

    async def _analyze_page(
        self,
        page_name: str,
        page_url: str,
        ocr_text: str,
    ) -> Dict[str, Any]:
        """使用 LLM 分析页面（如果 OCR 已通过 LLM 完成，直接返回结果）"""
        # 如果 ocr_text 已包含完整分析结果（来自 LLM VL 模型），直接使用
        if ocr_text and isinstance(ocr_text, dict):
            return ocr_text

        # 否则用文本 LLM 分析
        from app.runtime.base_agent import BaseRoutedAgent

        system_prompt = (
            "你是一个前端页面分析专家。请根据OCR文本分析页面结构和元素。\n"
            "返回JSON格式:\n"
            '{"page_description": "", "page_type": "", "module": "", '
            '"elements": [], "buttons": [], "inputs": [], "menus": [], "relations": []}'
        )
        user_prompt = f"页面名称: {page_name}\n页面URL: {page_url}\nOCR文本:\n{ocr_text}"

        # 使用静态方法调用 LLM
        agent = BaseRoutedAgent.__new__(BaseRoutedAgent)
        agent.__init__(description="page_analysis", display_name="PageAnalysis")
        result = await agent.call_llm_json(system_prompt, user_prompt)
        return result

    # ------------------------------------------------------------------
    # 元素保存
    # ------------------------------------------------------------------

    def _save_elements(self, pk_id: int, elements: List[Dict]):
        """将元素展开到独立行"""
        db = SessionLocal()
        try:
            # 先删除旧元素
            db.query(PageKnowledgeElement).filter_by(page_knowledge_id=pk_id).delete(
                synchronize_session=False
            )
            # 插入新元素
            for elem in elements:
                pe = PageKnowledgeElement(
                    page_knowledge_id=pk_id,
                    name=elem.get("name", ""),
                    element_type=elem.get("type", "other"),
                    text=elem.get("text", ""),
                    locator=elem.get("locator", ""),
                    locator_strategy=elem.get("locator_strategy", ""),
                    placeholder=elem.get("placeholder", ""),
                    is_required=elem.get("is_required", False),
                )
                db.add(pe)
            db.commit()
            logger.info(f"[PageKnowledge] 元素保存完成: pk_id={pk_id} count={len(elements)}")
        except Exception as e:
            db.rollback()
            logger.error(f"[PageKnowledge] 元素保存失败: {e}")
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 三库存储
    # ------------------------------------------------------------------

    async def _store_to_vector_graph(
        self,
        pk_id: int,
        page_name: str,
        page_url: str,
        analysis: Dict[str, Any],
    ):
        """存储到 Milvus + Neo4j

        MySQL: 已在 upload_screenshot 中完成
        Milvus: 页面描述向量
        Neo4j: Page 节点 + Element 节点 + 关系
        """
        # 1. Milvus: 页面向量
        try:
            from app.rag.graph_store.extended_store import get_extended_graph_store

            page_desc = analysis.get("page_description", "")
            if page_desc:
                result = await self._tri_store.sync_write(
                    entity_type="page",
                    entity_id=str(pk_id),
                    text=page_desc,
                    metadata={
                        "page_name": page_name,
                        "page_url": page_url,
                        "page_type": analysis.get("page_type", ""),
                        "module": analysis.get("module", ""),
                    },
                    neo4j_label="Page",
                    neo4j_properties={
                        "url": page_url,
                        "title": page_name,
                        "page_type": analysis.get("page_type", ""),
                    },
                )
                milvus_id = result.get("milvus", "")
                if "inserted" in str(milvus_id):
                    self._update_status(pk_id, None, milvus_id=1)
        except Exception as e:
            logger.warning(f"[PageKnowledge] Milvus 存储失败: {e}")

        # 2. Neo4j: Page → Element 节点 + 关系
        try:
            ext_graph = get_extended_graph_store()
            page_id = f"page_{pk_id}"

            # 创建元素节点 + HAS_ELEMENT 关系
            for elem in analysis.get("elements", []):
                elem_id = f"elem_{pk_id}_{elem.get('name', '')}"
                await ext_graph.create_element_node(
                    element_id=elem_id,
                    page_id=page_id,
                    tag_name=elem.get("type", ""),
                    text=elem.get("text", ""),
                    locator=elem.get("locator", ""),
                )

            # 创建页面关系
            for rel in analysis.get("relations", []):
                target_page = rel.get("target_page", "")
                if target_page:
                    await ext_graph.link_page_navigate(page_id, f"page_{target_page}")
        except Exception as e:
            logger.warning(f"[PageKnowledge] Neo4j 存储失败: {e}")

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_page_by_name(self, page_name: str) -> Optional[Dict[str, Any]]:
        """按页面名称查询页面知识（不需要再次OCR）

        CaseAgent 调用此方法获取页面所有元素。
        """
        db = SessionLocal()
        try:
            pk = db.query(PageKnowledge).filter_by(
                page_name=page_name
            ).order_by(PageKnowledge.version.desc()).first()
            if pk is None:
                return None
            return self._pk_to_dict(pk, include_elements=True, db=db)
        finally:
            db.close()

    def get_page_elements(self, page_name: str) -> List[Dict[str, Any]]:
        """获取页面的所有元素（不需要再次OCR）

        这是 CaseAgent 的核心查询接口：
        查询「登录页面」→ 返回所有元素（按钮/输入框/菜单等）
        """
        db = SessionLocal()
        try:
            pk = db.query(PageKnowledge).filter_by(
                page_name=page_name
            ).order_by(PageKnowledge.version.desc()).first()
            if pk is None:
                return []
            elements = (
                db.query(PageKnowledgeElement)
                .filter_by(page_knowledge_id=pk.id)
                .all()
            )
            return [self._element_to_dict(e) for e in elements]
        finally:
            db.close()

    def get_page_elements_by_type(
        self, page_name: str, element_type: str
    ) -> List[Dict[str, Any]]:
        """按类型获取页面元素（如只要按钮或只要输入框）"""
        db = SessionLocal()
        try:
            pk = db.query(PageKnowledge).filter_by(
                page_name=page_name
            ).first()
            if pk is None:
                return []
            elements = (
                db.query(PageKnowledgeElement)
                .filter_by(page_knowledge_id=pk.id, element_type=element_type)
                .all()
            )
            return [self._element_to_dict(e) for e in elements]
        finally:
            db.close()

    def search_pages(
        self,
        keyword: str = "",
        page_type: str = "",
        module: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """搜索页面知识"""
        db = SessionLocal()
        try:
            q = db.query(PageKnowledge)
            if keyword:
                q = q.filter(PageKnowledge.page_name.contains(keyword))
            if page_type:
                q = q.filter_by(page_type=page_type)
            if module:
                q = q.filter_by(module=module)
            q = q.order_by(PageKnowledge.created_at.desc()).limit(limit)
            return [self._pk_to_dict(pk, include_elements=False, db=db) for pk in q.all()]
        finally:
            db.close()

    def get_page_relations(self, page_name: str) -> List[Dict[str, Any]]:
        """获取页面关系"""
        db = SessionLocal()
        try:
            pk = db.query(PageKnowledge).filter_by(
                page_name=page_name
            ).first()
            if pk is None or not pk.relations_json:
                return []
            try:
                return json.loads(pk.relations_json)
            except Exception:
                return []
        finally:
            db.close()

    async def search_pages_by_vector(
        self, query: str, top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """向量搜索页面（通过 Milvus）"""
        try:
            from app.rag.vector_store.multi_vector_store import get_multi_vector_store
            from app.rag.embedding.factory import get_embedding_factory

            store = get_multi_vector_store()
            embedding_provider = get_embedding_factory().get_embedding()
            query_vector = await embedding_provider.embed(query)

            results = await store.search(
                query_vector=query_vector,
                entity_types=["page"],
                top_k=top_k,
            )
            return [r.model_dump() for r in results]
        except Exception as e:
            logger.warning(f"[PageKnowledge] 向量搜索失败: {e}")
            return []

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取页面知识统计"""
        db = SessionLocal()
        try:
            from sqlalchemy import func
            total = db.query(func.count(PageKnowledge.id)).scalar() or 0
            by_status = {}
            rows = db.query(
                PageKnowledge.status, func.count(PageKnowledge.id)
            ).group_by(PageKnowledge.status).all()
            for st, cnt in rows:
                by_status[st] = cnt
            by_type = {}
            rows = db.query(
                PageKnowledge.page_type, func.count(PageKnowledge.id)
            ).filter(PageKnowledge.page_type.isnot(None)).group_by(PageKnowledge.page_type).all()
            for pt, cnt in rows:
                by_type[pt] = cnt
            total_elements = db.query(func.count(PageKnowledgeElement.id)).scalar() or 0
            return {
                "total_pages": total,
                "total_elements": total_elements,
                "by_status": by_status,
                "by_type": by_type,
            }
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _update_status(
        self,
        pk_id: int,
        status: Optional[PageKnowledgeStatus],
        **kwargs,
    ):
        """更新页面知识状态和字段"""
        db = SessionLocal()
        try:
            pk = db.query(PageKnowledge).filter_by(id=pk_id).first()
            if pk is None:
                return
            if status is not None:
                pk.status = status
            for k, v in kwargs.items():
                if v is not None and hasattr(pk, k):
                    setattr(pk, k, v)
            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[PageKnowledge] 状态更新失败: {e}")
        finally:
            db.close()

    @staticmethod
    def _pk_to_dict(pk: PageKnowledge, include_elements: bool = True, db=None) -> Dict[str, Any]:
        """将 ORM 对象转为字典"""
        result = {
            "id": pk.id,
            "page_name": pk.page_name,
            "page_url": pk.page_url,
            "screenshot_path": pk.screenshot_path,
            "ocr_text": (pk.ocr_text[:200] + "...") if pk.ocr_text and len(pk.ocr_text) > 200 else pk.ocr_text,
            "page_description": pk.page_description,
            "page_type": pk.page_type,
            "module": pk.module,
            "status": pk.status,
            "version": pk.version,
            "milvus_id": pk.milvus_id,
            "neo4j_synced": pk.neo4j_synced,
            "created_at": pk.created_at.isoformat() if pk.created_at else None,
        }
        # 解析 JSON 字段
        for field in ["elements_json", "buttons_json", "inputs_json", "menus_json", "relations_json"]:
            val = getattr(pk, field, None)
            if val:
                try:
                    result[field.replace("_json", "")] = json.loads(val)
                except Exception:
                    result[field.replace("_json", "")] = []
            else:
                result[field.replace("_json", "")] = []

        if include_elements and db:
            elements = (
                db.query(PageKnowledgeElement)
                .filter_by(page_knowledge_id=pk.id)
                .all()
            )
            result["elements_detail"] = [
                PageKnowledgeService._element_to_dict(e) for e in elements
            ]
        return result

    @staticmethod
    def _element_to_dict(e: PageKnowledgeElement) -> Dict[str, Any]:
        """将元素 ORM 对象转为字典"""
        return {
            "id": e.id,
            "page_knowledge_id": e.page_knowledge_id,
            "name": e.name,
            "type": e.element_type,
            "text": e.text,
            "locator": e.locator,
            "locator_strategy": e.locator_strategy,
            "placeholder": e.placeholder,
            "is_required": e.is_required,
        }


# ===== 单例 =====
_service: Optional[PageKnowledgeService] = None


def get_page_knowledge_service() -> PageKnowledgeService:
    global _service
    if _service is None:
        _service = PageKnowledgeService()
    return _service
