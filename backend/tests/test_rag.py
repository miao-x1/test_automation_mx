"""
RAG系统端到端测试

测试流程：
1. Milvus连接和集合创建
2. DashScope Embedding API调用
3. 元素索引
4. 语义检索
"""
import sys
import os
import asyncio

# 添加项目路径
sys.path.insert(0, os.path.dirname(__file__))

from app.db.milvus_client import get_or_create_collection, COLLECTION_NAME, EMBEDDING_DIM
from app.core.config import settings


def test_milvus_connection():
    """测试1: Milvus连接和集合创建"""
    print("=== 测试1: Milvus连接 ===")

    # 如果旧集合存在，先删除（维度可能不匹配）
    from app.db.milvus_client import get_milvus_client
    client = get_milvus_client()
    if client.has_collection(COLLECTION_NAME):
        # 检查现有集合的维度
        try:
            info = client.describe_collection(COLLECTION_NAME)
            for field in info.get("fields", []):
                if field.get("name") == "embedding":
                    old_dim = field.get("params", {}).get("dim")
                    if old_dim and int(old_dim) != EMBEDDING_DIM:
                        print(f"  旧集合维度 {old_dim} != 配置维度 {EMBEDDING_DIM}，删除重建")
                        client.drop_collection(COLLECTION_NAME)
                        break
        except Exception as e:
            print(f"  检查集合信息异常: {e}，删除重建")
            client.drop_collection(COLLECTION_NAME)

    # 重新创建
    from app.db.milvus_client import create_collection
    create_collection(client)

    assert client.has_collection(COLLECTION_NAME), f"集合 {COLLECTION_NAME} 不存在"
    stats = client.get_collection_stats(COLLECTION_NAME)
    print(f"  集合: {COLLECTION_NAME}")
    print(f"  行数: {stats.get('row_count', 0)}")
    print(f"  向量维度: {EMBEDDING_DIM}")
    print(f"  Embedding方式: {settings.EMBEDDING_PROVIDER}")
    print("  PASS")


def test_embedding():
    """测试2: Embedding API调用"""
    print("\n=== 测试2: Embedding API ===")
    from app.agent.rag.embedding_agent import EmbeddingAgent
    agent = EmbeddingAgent()

    # 测试生成embedding
    texts = ["登录按钮", "搜索输入框", "提交表单"]
    embeddings = agent._embed(texts)

    print(f"  向量数量: {len(embeddings)}")
    print(f"  向量维度: {len(embeddings[0])}")
    print(f"  方式: {settings.EMBEDDING_PROVIDER}")
    assert len(embeddings) == 3, f"向量数量不对: {len(embeddings)}"
    assert len(embeddings[0]) == EMBEDDING_DIM, f"向量维度不对: {len(embeddings[0])} != {EMBEDDING_DIM}"
    print("  PASS")


def test_index_and_search():
    """测试3: 索引和检索"""
    print("\n=== 测试3: 索引和检索 ===")

    # 读取数据库中的元素
    from app.db.database import SessionLocal
    from app.models.task import Task
    from app.models.ui_element import UIElement

    db = SessionLocal()
    elements = db.query(UIElement).limit(20).all()
    print(f"  数据库中元素数量: {len(elements)}")

    if len(elements) == 0:
        print("  跳过: 没有元素数据，请先执行页面分析")
        db.close()
        return

    # 转换为字典
    elem_dicts = [
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
    db.close()

    # 执行Embedding
    from app.agent.rag.embedding_agent import EmbeddingAgent
    agent = EmbeddingAgent()

    async def run_embed():
        async for log_data in agent.embed_elements(elem_dicts, task_id=elem_dicts[0]["task_id"]):
            print(f"  [Embed] {log_data['step']} | {log_data['progress']}% | {log_data['message']}")

    asyncio.run(run_embed())

    # 执行检索
    from app.agent.rag.retrieval_agent import RetrievalAgent
    retrieval = RetrievalAgent()

    async def run_search():
        results = []
        async for log_data in retrieval.search("测试登录", top_k=5):
            print(f"  [Search] {log_data['step']} | {log_data['progress']}% | {log_data['message']}")
            if "data" in log_data:
                results.append(log_data["data"])
        return results

    search_results = asyncio.run(run_search())

    if search_results:
        data = search_results[-1]
        print(f"  检索结果数量: {data.get('total', 0)}")
        for r in data.get("results", [])[:3]:
            print(f"    - {r['element_name']} ({r['element_type']}) | 相似度: {r['score']} | 定位器: {r['locator'][:50] if r['locator'] else 'N/A'}")

    print("  PASS")


if __name__ == "__main__":
    test_milvus_connection()
    test_embedding()
    test_index_and_search()
    print("\n=== 所有测试通过 ===")
