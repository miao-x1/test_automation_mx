"""
UI元素模型 - 统一元素表

支持三种来源：
- vision: Vision视觉分析结果
- dom: Playwright DOM抓取结果
- merge: 融合结果（Vision语义 + DOM定位）
"""
from sqlalchemy import Column, String, Integer, Float, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class UIElement(OwnedModel):
    """
    统一UI元素表

    存储来自Vision分析、DOM抓取和融合后的元素信息
    """
    __tablename__ = "ui_element"

    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID"
    )

    # 元素基本信息
    name = Column(
        String(255),
        nullable=False,
        comment="元素名称（语义描述）"
    )

    type = Column(
        String(50),
        nullable=False,
        index=True,
        comment="元素类型(button/input/text/checkbox/radio/link/select/textarea/form/table/img)"
    )

    text = Column(
        String(512),
        nullable=True,
        comment="元素文本内容"
    )

    # 来源标识
    source = Column(
        String(20),
        nullable=False,
        index=True,
        comment="元素来源: vision/dom/merge"
    )

    # 定位信息
    locator = Column(
        String(512),
        nullable=True,
        comment="最佳定位器（优先id > name > aria-label > css > xpath）"
    )

    xpath = Column(
        String(1024),
        nullable=True,
        comment="XPath定位"
    )

    css_selector = Column(
        String(1024),
        nullable=True,
        comment="CSS选择器定位"
    )

    # DOM属性（dom/merge来源时填充）
    element_id = Column(
        String(255),
        nullable=True,
        comment="元素id属性"
    )

    element_class = Column(
        String(512),
        nullable=True,
        comment="元素class属性"
    )

    element_name = Column(
        String(255),
        nullable=True,
        comment="元素name属性"
    )

    placeholder = Column(
        String(255),
        nullable=True,
        comment="placeholder属性"
    )

    href = Column(
        String(1024),
        nullable=True,
        comment="href属性"
    )

    aria_label = Column(
        String(255),
        nullable=True,
        comment="aria-label属性"
    )

    role = Column(
        String(50),
        nullable=True,
        comment="role属性"
    )

    data_testid = Column(
        String(255),
        nullable=True,
        comment="data-testid属性"
    )

    # 页面URL（dom/merge来源时填充）
    page_url = Column(
        String(1024),
        nullable=True,
        comment="页面URL"
    )

    # 置信度
    confidence = Column(
        Float,
        nullable=True,
        comment="识别置信度(0-1)"
    )

    # 知识库审核状态
    kb_status = Column(
        String(20),
        default="approved",
        nullable=False,
        index=True,
        comment="知识库审核状态: draft/approved/rejected"
    )

    # 关联关系
    task = relationship("Task", back_populates="ui_elements")

    def __repr__(self):
        return f"<UIElement(id={self.id}, name={self.name}, type={self.type}, source={self.source})>"


# 复合索引
Index('idx_ui_element_task_type', UIElement.task_id, UIElement.type)
Index('idx_ui_element_task_source', UIElement.task_id, UIElement.source)
