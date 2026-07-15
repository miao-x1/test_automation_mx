"""
PageKnowledge 模型 - 页面知识库

上传页面截图后自动完成：
  OCR → 页面描述 → 页面元素（按钮/输入框/菜单）→ 页面关系
  → MySQL + Milvus + Neo4j

以后 CaseAgent 可以直接查询「登录页面」返回所有元素，不需要再次 OCR。
"""
import enum
from sqlalchemy import Column, String, Integer, Text, Float, Boolean, ForeignKey, Index, JSON
from app.models.base import OwnedModel


class PageKnowledgeStatus(str, enum.Enum):
    """页面知识状态"""
    PENDING = "pending"           # 待处理
    OCR_PROCESSING = "ocr_processing"  # OCR 中
    OCR_DONE = "ocr_done"          # OCR 完成
    ANALYZING = "analyzing"        # LLM 分析中
    ANALYZED = "analyzed"          # 分析完成
    STORING = "storing"            # 三库存储中
    STORED = "stored"              # 存储完成
    FAILED = "failed"              # 失败


class PageKnowledge(OwnedModel):
    """页面知识表

    存储页面的完整知识信息，包括 OCR 文本、页面描述、元素列表、页面关系。
    一次 OCR 分析后永久存储，后续查询直接返回，不重复 OCR。
    """
    __tablename__ = "page_knowledge"

    # 页面标识
    page_name = Column(
        String(200), nullable=False, index=True,
        comment="页面名称（如：登录页面、首页、用户管理页）"
    )
    page_url = Column(
        String(500), nullable=True, index=True,
        comment="页面URL（可选）"
    )
    screenshot_path = Column(
        String(500), nullable=True,
        comment="截图文件路径"
    )

    # OCR 结果
    ocr_text = Column(
        Text, nullable=True,
        comment="OCR识别的完整文本"
    )
    ocr_confidence = Column(
        Float, nullable=True,
        comment="OCR置信度(0-1)"
    )

    # LLM 分析结果
    page_description = Column(
        Text, nullable=True,
        comment="LLM生成的页面描述"
    )
    page_type = Column(
        String(50), nullable=True,
        comment="页面类型: login/list/detail/form/dashboard/error/other"
    )
    module = Column(
        String(100), nullable=True,
        comment="所属模块: auth/user/order/admin等"
    )

    # 元素信息（JSON 数组）
    elements_json = Column(
        Text, nullable=True,
        comment="页面元素列表(JSON): [{name, type, locator, text, ...}]"
    )
    buttons_json = Column(
        Text, nullable=True,
        comment="按钮列表(JSON)"
    )
    inputs_json = Column(
        Text, nullable=True,
        comment="输入框列表(JSON)"
    )
    menus_json = Column(
        Text, nullable=True,
        comment="菜单列表(JSON)"
    )

    # 页面关系
    relations_json = Column(
        Text, nullable=True,
        comment="页面关系列表(JSON): [{target_page, relation_type, trigger}]"
    )

    # 三库存储状态
    milvus_id = Column(
        Integer, nullable=True,
        comment="Milvus 向量ID"
    )
    neo4j_synced = Column(
        Boolean, default=False, nullable=False,
        comment="Neo4j 是否已同步"
    )

    # 处理状态
    status = Column(
        String(30), nullable=False, default=PageKnowledgeStatus.PENDING,
        index=True, comment="处理状态"
    )
    error_message = Column(
        Text, nullable=True,
        comment="错误信息"
    )

    # 版本
    version = Column(
        Integer, nullable=False, default=1,
        comment="版本号（重新OCR时递增）"
    )

    __table_args__ = (
        Index("idx_page_knowledge_name_url", "page_name", "page_url"),
        Index("idx_page_knowledge_module_type", "module", "page_type"),
    )


class PageKnowledgeElement(OwnedModel):
    """页面知识元素表 - 单独存储每个元素便于查询

    从 elements_json 展开到独立行，支持按元素类型/名称精确查询。
    """
    __tablename__ = "page_knowledge_element"

    page_knowledge_id = Column(
        Integer, ForeignKey("page_knowledge.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="页面知识ID"
    )
    name = Column(
        String(255), nullable=False,
        comment="元素名称（语义描述）"
    )
    element_type = Column(
        String(50), nullable=False, index=True,
        comment="元素类型: button/input/link/select/textarea/form/table/img/menu/text"
    )
    text = Column(
        String(512), nullable=True,
        comment="元素文本内容"
    )
    locator = Column(
        String(512), nullable=True,
        comment="最佳定位器"
    )
    locator_strategy = Column(
        String(50), nullable=True,
        comment="定位策略: id/name/css/xpath/aria_label/role"
    )
    placeholder = Column(
        String(255), nullable=True,
        comment="placeholder属性"
    )
    is_required = Column(
        Boolean, default=False, nullable=False,
        comment="是否必填（输入框）"
    )

    __table_args__ = (
        Index("idx_pke_page_type", "page_knowledge_id", "element_type"),
    )
