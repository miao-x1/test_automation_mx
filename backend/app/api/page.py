"""
页面抓取接口

数据隔离：所有查询自动过滤 user_id
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse
from app.db.database import get_db
from app.schemas.response import Response
from app.services.page_crawler_service import PageCrawlerService
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User

router = APIRouter()


class CrawlRequest(BaseModel):
    """页面抓取请求"""
    url: str = Field(..., description="页面URL")
    task_name: str = Field(default=None, description="任务名称（可选）")


class PageElementResponse(BaseModel):
    """页面元素响应"""
    id: int
    tag_name: str
    element_text: str | None = None
    element_id: str | None = None
    element_class: str | None = None
    element_name: str | None = None
    placeholder: str | None = None
    href: str | None = None
    aria_label: str | None = None
    role: str | None = None
    xpath: str | None = None
    css_selector: str | None = None

    model_config = {"from_attributes": True}


@router.post("/crawl", summary="创建页面抓取任务")
async def create_crawl_task(
    req: CrawlRequest,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """创建页面抓取任务并返回task_id"""
    task = PageCrawlerService.create_crawl_task(db, req.url, req.task_name, user_id=user.id)
    return Response(
        code=200,
        message="抓取任务创建成功",
        data={"task_id": task.id, "url": req.url}
    )


@router.get("/{task_id}/crawl-analyze", summary="执行页面抓取（SSE）")
async def run_crawl(
    task_id: int,
    url: str,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """执行页面抓取，通过SSE实时推送进度"""
    from app.models.task import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    return EventSourceResponse(
        PageCrawlerService.run_crawl(task_id, url)
    )


@router.get("/{task_id}/elements", summary="获取页面元素列表")
async def get_page_elements(
    task_id: int,
    user: User = Depends(require_auth),
    db: Session = Depends(get_db)
):
    """获取任务抓取到的页面元素"""
    from app.models.task import Task
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.user_id is not None and task.user_id != user.id:
        raise HTTPException(status_code=403, detail="无权访问")

    elements = PageCrawlerService.get_page_elements(db, task_id)
    return Response(
        code=200,
        message="success",
        data=[PageElementResponse.model_validate(el) for el in elements]
    )
