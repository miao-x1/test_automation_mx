"""
任务数据验证模型
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from app.models.task import TaskStatus


class ImageFileResponse(BaseModel):
    """图片文件响应"""
    id: int = Field(..., description="图片ID")
    original_filename: str = Field(..., description="原始文件名")
    file_path: str = Field(..., description="文件路径")
    file_size: int = Field(..., description="文件大小")
    file_type: str = Field(..., description="文件类型")
    created_at: datetime = Field(..., description="创建时间")

    model_config = {"from_attributes": True}


class AnalysisResultResponse(BaseModel):
    """分析结果响应"""
    id: int = Field(..., description="分析结果ID")
    agent_type: str = Field(..., description="Agent类型")
    page_type: Optional[str] = Field(None, description="页面类型")
    elements_json: Optional[str] = Field(None, description="UI元素JSON")
    interactions_json: Optional[str] = Field(None, description="交互JSON")
    analysis_summary: Optional[str] = Field(None, description="分析总结")
    created_at: datetime = Field(..., description="创建时间")

    model_config = {"from_attributes": True}


class ScriptResponse(BaseModel):
    """脚本响应"""
    id: int = Field(..., description="脚本ID")
    script_type: str = Field(..., description="脚本类型")
    script_content: str = Field(..., description="脚本内容")
    script_language: str = Field(..., description="脚本语言")
    created_at: datetime = Field(..., description="创建时间")

    model_config = {"from_attributes": True}


class UIElementResponse(BaseModel):
    """统一UI元素响应"""
    id: int = Field(..., description="元素ID")
    name: str = Field(..., description="元素名称")
    type: str = Field(..., description="元素类型")
    text: Optional[str] = Field(None, description="元素文本")
    source: str = Field(..., description="来源: vision/dom/merge")
    locator: Optional[str] = Field(None, description="最佳定位器")
    xpath: Optional[str] = Field(None, description="XPath")
    css_selector: Optional[str] = Field(None, description="CSS选择器")
    element_id: Optional[str] = Field(None, description="元素id属性")
    element_class: Optional[str] = Field(None, description="元素class属性")
    element_name: Optional[str] = Field(None, description="元素name属性")
    placeholder: Optional[str] = Field(None, description="placeholder")
    href: Optional[str] = Field(None, description="href")
    aria_label: Optional[str] = Field(None, description="aria-label")
    role: Optional[str] = Field(None, description="role")
    data_testid: Optional[str] = Field(None, description="data-testid")
    page_url: Optional[str] = Field(None, description="页面URL")
    confidence: Optional[float] = Field(None, description="置信度")

    model_config = {"from_attributes": True}


class PageElementResponse(BaseModel):
    """页面元素响应（Playwright抓取的DOM元素，兼容旧接口）"""
    id: int = Field(..., description="元素ID")
    tag_name: str = Field(..., description="标签名")
    element_text: Optional[str] = Field(None, description="元素文本")
    element_id: Optional[str] = Field(None, description="元素ID属性")
    element_class: Optional[str] = Field(None, description="元素class属性")
    element_name: Optional[str] = Field(None, description="元素name属性")
    placeholder: Optional[str] = Field(None, description="placeholder属性")
    href: Optional[str] = Field(None, description="href属性")
    aria_label: Optional[str] = Field(None, description="aria-label属性")
    role: Optional[str] = Field(None, description="role属性")
    xpath: Optional[str] = Field(None, description="XPath定位")
    css_selector: Optional[str] = Field(None, description="CSS选择器定位")

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    """创建任务请求"""
    task_name: str = Field(..., min_length=1, max_length=255, description="任务名称")


class TaskResponse(BaseModel):
    """任务响应"""
    id: int = Field(..., description="任务ID")
    task_name: str = Field(..., description="任务名称")
    status: TaskStatus = Field(..., description="任务状态")
    input_mode: str = Field(default="image", description="输入模式: image/url")
    task_type: Optional[str] = Field(default="web", description="测试类型: web/api/performance/android")
    type_config: Optional[str] = Field(None, description="测试类型配置(JSON)")
    page_url: Optional[str] = Field(None, description="页面URL")
    error_message: Optional[str] = Field(None, description="错误信息")
    created_at: datetime = Field(..., description="创建时间")
    updated_at: datetime = Field(..., description="更新时间")

    # 关联数据
    images: List[ImageFileResponse] = Field(default_factory=list, description="图片列表")
    analysis_result: Optional[AnalysisResultResponse] = Field(None, description="分析结果")
    script: Optional[ScriptResponse] = Field(None, description="测试脚本")
    ui_elements: List[UIElementResponse] = Field(default_factory=list, description="统一元素列表")
    page_elements: List[PageElementResponse] = Field(default_factory=list, description="页面元素列表(DOM抓取,兼容)")

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    """任务列表响应"""
    total: int = Field(..., description="总数")
    items: list[TaskResponse] = Field(..., description="任务列表")
