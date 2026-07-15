"""
多模态需求输入模型

存储用户通过文本/图片/URL/脚本等多种方式输入的需求信息
"""
import enum
from sqlalchemy import Column, String, Integer, Text, ForeignKey, Index
from app.models.base import OwnedModel


class InputMode(str, enum.Enum):
    """输入模式"""
    TEXT = "text"          # 纯文本
    IMAGE = "image"        # 图片（Vision模式）
    URL = "url"            # URL（DOM模式）
    SCRIPT = "script"      # 脚本上传（复用模式）
    MIXED = "mixed"        # 混合输入


class RequirementInput(OwnedModel):
    """
    多模态需求输入表

    存储用户通过多种方式输入的需求，支持文本、图片、URL、脚本的混合输入
    """
    __tablename__ = "requirement_input"

    # 关联的需求任务ID
    requirement_id = Column(
        Integer,
        ForeignKey("requirement_task.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
        comment="关联的需求任务ID"
    )

    # 输入模式
    mode = Column(
        String(20),
        default=InputMode.TEXT,
        nullable=False,
        comment="输入模式: text/image/url/script/mixed"
    )

    # 文本需求
    text = Column(
        Text,
        nullable=True,
        comment="文本需求内容"
    )

    # 图片路径（JSON数组）
    images = Column(
        Text,
        nullable=True,
        comment="上传的图片路径列表(JSON数组)"
    )

    # URL列表（JSON数组）
    urls = Column(
        Text,
        nullable=True,
        comment="输入的URL列表(JSON数组)"
    )

    # 上传的脚本路径
    script_path = Column(
        String(500),
        nullable=True,
        comment="上传的脚本文件路径"
    )

    # 脚本内容（直接粘贴）
    script_content = Column(
        Text,
        nullable=True,
        comment="直接粘贴的脚本内容"
    )

    # 脚本语言
    script_language = Column(
        String(30),
        nullable=True,
        comment="脚本语言: python/javascript/yaml等"
    )

    # 关联的数据库页面ID（JSON数组）
    page_ids = Column(
        Text,
        nullable=True,
        comment="关联的数据库页面ID列表(JSON数组)"
    )

    # AI推荐的模式
    recommended_mode = Column(
        String(20),
        nullable=True,
        comment="AI推荐的处理模式: vision/dom/reuse"
    )

    # 推荐原因
    recommended_reason = Column(
        String(500),
        nullable=True,
        comment="AI推荐模式的理由"
    )

    # 解析结果（各Parser的输出，JSON）
    parsed_result = Column(
        Text,
        nullable=True,
        comment="各Parser解析结果(JSON)"
    )

    # 融合结果（FusionAgent的输出，JSON）
    fused_result = Column(
        Text,
        nullable=True,
        comment="FusionAgent融合结果(JSON)"
    )

    # 融合后的统一需求文本
    unified_requirement = Column(
        Text,
        nullable=True,
        comment="融合后的统一需求文本"
    )

    def __repr__(self):
        return f"<RequirementInput(id={self.id}, mode={self.mode})>"


Index('idx_req_input_requirement', RequirementInput.requirement_id)
Index('idx_req_input_mode', RequirementInput.mode)
