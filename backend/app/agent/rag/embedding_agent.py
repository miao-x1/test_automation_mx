"""
EmbeddingAgent - 读取统一元素库，生成向量，写入Milvus

架构变更：
  原：Agent 自带 DashScope Embedding 实现（重复代码）
  新：Agent 通过 EmbeddingFactory 统一获取 Embedding

  所有 Embedding 调用通过 EmbeddingFactory → DashScopeEmbedding，
  禁止在 Agent 中重复实现 DashScope API 调用。

  Agent 禁止直接导入 app.db.milvus_client，
  所有 Milvus 写入通过 StorageRouter 统一路由。

流程：
1. 从数据库读取UIElement
2. 构建描述文本（名称+类型+定位器+文本+页面URL）
3. 通过 EmbeddingFactory 生成 embedding
4. 通过 StorageRouter 写入Milvus集合
"""
from typing import AsyncGenerator, Dict, Any, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.db.collection_constants import UI_ELEMENT_COLLECTION


class EmbeddingAgent(NewBaseAgent):
    """Embedding生成Agent

    通过 EmbeddingFactory 统一获取 Embedding，禁止重复实现。
    """

    agent_name = "embedding"
    display_name = "Embedding Agent"
    description = "Embedding生成Agent - 读取统一元素库，生成向量，写入Milvus"
    capabilities = [AgentCapability.EMBEDDING]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self._storage = None
        self.model = None
        self.system_prompt = None

    @property
    def storage(self):
        """延迟加载 StorageRouter（统一获取 Embedding + Milvus 写入）"""
        if self._storage is None:
            from app.services.context_router.storage_router import get_storage_router
            self._storage = get_storage_router()
        return self._storage

    def _build_description(self, element: Dict[str, Any]) -> str:
        """
        构建元素的描述文本（用于生成embedding）

        将元素的关键信息拼接成自然语言描述，
        使语义搜索能匹配到相关元素
        """
        parts = []

        # 元素名称
        name = element.get("name", "")
        if name:
            parts.append(f"元素: {name}")

        # 元素类型
        elem_type = element.get("type", "")
        if elem_type:
            type_map = {
                "button": "按钮", "input": "输入框", "text": "文本",
                "checkbox": "复选框", "radio": "单选框", "link": "链接",
                "select": "下拉选择", "textarea": "文本域", "form": "表单",
                "table": "表格", "img": "图片", "searchbox": "搜索框",
                "menu": "菜单", "dropdown": "下拉菜单",
            }
            type_cn = type_map.get(elem_type, elem_type)
            parts.append(f"类型: {type_cn}")

        # 文本内容
        text = element.get("text", "")
        if text:
            parts.append(f"文本: {text}")

        # placeholder
        placeholder = element.get("placeholder", "")
        if placeholder:
            parts.append(f"提示: {placeholder}")

        # aria_label
        aria_label = element.get("aria_label", "")
        if aria_label:
            parts.append(f"标签: {aria_label}")

        # 页面URL
        page_url = element.get("page_url", "")
        if page_url:
            parts.append(f"页面: {page_url}")

        # 定位器
        locator = element.get("locator", "")
        if locator:
            parts.append(f"定位: {locator}")

        return " | ".join(parts)

    def _embed(self, texts: List[str]) -> List[List[float]]:
        """通过 StorageRouter 统一生成 embedding（同步）

        禁止直接导入 embedding_factory，统一通过 StorageRouter。
        """
        return self.storage.embed_batch_sync(texts)

    async def embed_elements(
        self,
        elements: List[Dict[str, Any]],
        task_id: int,
        on_log: Optional[callable] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        将元素列表生成embedding并写入Milvus

        Args:
            elements: UIElement字典列表
            task_id: 任务ID
            on_log: 日志回调

        Yields:
            进度信息
        """
        total = len(elements)
        if total == 0:
            yield {"step": "Embedding完成", "progress": 100, "message": "没有可索引的元素"}
            return

        yield {"step": "开始Embedding", "progress": 10, "message": f"准备处理 {total} 个元素 | 方式: {settings.EMBEDDING_PROVIDER}"}

        # 使用 StorageRouter 统一写入入口（禁止直接导入 milvus_client）
        storage = self.storage

        # 构建描述文本
        yield {"step": "构建描述", "progress": 20, "message": "正在构建元素描述文本..."}
        descriptions = []
        valid_elements = []

        for elem in elements:
            desc = self._build_description(elem)
            if desc.strip():
                descriptions.append(desc)
                valid_elements.append(elem)

        if not valid_elements:
            yield {"step": "Embedding完成", "progress": 100, "message": "没有有效的元素描述"}
            return

        # 生成embedding
        yield {"step": "生成向量", "progress": 40, "message": f"正在为 {len(descriptions)} 个元素生成向量..."}
        embeddings = self._embed(descriptions)

        yield {"step": "向量生成完成", "progress": 70, "message": f"已生成 {len(embeddings)} 个向量 | 维度: {len(embeddings[0])}"}

        # 构建写入数据
        data = []
        for i, (elem, emb) in enumerate(zip(valid_elements, embeddings)):
            page_url = elem.get("page_url", "") or ""
            if len(page_url) > 512:
                page_url = page_url[:512]

            locator = elem.get("locator", "") or ""
            if len(locator) > 1024:
                locator = locator[:1024]

            description = descriptions[i]
            if len(description) > 2048:
                description = description[:2048]

            element_name = elem.get("name", "") or ""
            if len(element_name) > 255:
                element_name = element_name[:255]

            element_type = elem.get("type", "") or ""
            if len(element_type) > 50:
                element_type = element_type[:50]

            data.append({
                "task_id": task_id,
                "page_name": page_url,
                "element_name": element_name,
                "element_type": element_type,
                "locator": locator,
                "description": description,
                "embedding": emb,
            })

        # 写入Milvus（通过 StorageRouter 统一路由）
        yield {"step": "写入Milvus", "progress": 85, "message": f"正在写入 {len(data)} 条向量数据..."}
        storage.milvus_insert(UI_ELEMENT_COLLECTION, data)

        yield {"step": "Embedding完成", "progress": 100, "message": f"成功索引 {len(data)} 个元素到Milvus"}
