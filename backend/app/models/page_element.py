"""
页面元素模型 - 存储Playwright抓取的真实DOM元素
"""
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from app.models.base import OwnedModel


class PageElement(OwnedModel):
    """
    页面元素表

    存储通过Playwright抓取的真实DOM元素信息
    包含定位属性（xpath, css_selector等）
    """
    __tablename__ = "page_element"

    task_id = Column(
        Integer,
        ForeignKey("task.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="任务ID"
    )

    page_url = Column(
        String(1024),
        nullable=False,
        comment="页面URL"
    )

    tag_name = Column(
        String(50),
        nullable=False,
        index=True,
        comment="标签名(button/input/a/select等)"
    )

    element_text = Column(
        String(512),
        nullable=True,
        comment="元素文本内容"
    )

    element_id = Column(
        String(255),
        nullable=True,
        comment="元素ID属性"
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

    # 关联关系
    task = relationship("Task", back_populates="page_elements")

    def __repr__(self):
        return f"<PageElement(id={self.id}, tag={self.tag_name}, text={self.element_text[:20] if self.element_text else ''})>"


# 复合索引
Index('idx_page_element_task_tag', PageElement.task_id, PageElement.tag_name)
