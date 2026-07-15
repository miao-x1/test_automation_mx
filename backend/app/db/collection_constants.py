"""
Milvus Collection 命名统一常量

所有 Milvus Collection 名称的唯一定义来源。
项目中所有模块必须从此文件导入集合名称常量，禁止硬编码字符串。

命名规范：{domain}_{entity}_vector
  - ui_element_vector    → UI元素向量
  - test_case_vector     → 测试用例向量
  - script_vector        → 脚本向量
  - rag_knowledge_vector → RAG知识文档向量
  - requirement_vector   → 需求向量
  - page_vector          → 页面向量
"""

# ===== 基础集合（milvus_client.py 管理 Schema，特定字段）=====
UI_ELEMENT_COLLECTION = "ui_element_vector"
CASE_COLLECTION = "test_case_vector"
SCRIPT_COLLECTION = "script_vector"

# ===== RAG 扩展集合（multi_vector_store.py 管理 Schema，统一结构）=====
RAG_KNOWLEDGE_COLLECTION = "rag_knowledge_vector"
REQUIREMENT_COLLECTION = "requirement_vector"
PAGE_COLLECTION = "page_vector"
# MultiVectorStore 统一 Schema 集合（与 milvus_client 的集合分离，避免 Schema 冲突）
MV_CASE_COLLECTION = "mv_case_vector"
MV_SCRIPT_COLLECTION = "mv_script_vector"

# ===== 全部集合列表 =====
ALL_COLLECTIONS = [
    UI_ELEMENT_COLLECTION,
    CASE_COLLECTION,
    SCRIPT_COLLECTION,
    RAG_KNOWLEDGE_COLLECTION,
    REQUIREMENT_COLLECTION,
    PAGE_COLLECTION,
    MV_CASE_COLLECTION,
    MV_SCRIPT_COLLECTION,
]
