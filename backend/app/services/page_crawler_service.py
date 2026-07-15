"""
页面抓取服务层
"""
import json
from typing import AsyncGenerator
from sqlalchemy.orm import Session
from app.models.task import Task, TaskStatus
from app.models.page_element import PageElement
from app.models.script import Script
from app.agent.vision.page_crawler_agent import PageCrawlerAgent
from app.core.logger import log


class PageCrawlerService:
    """页面抓取服务"""

    @staticmethod
    def create_crawl_task(db: Session, url: str, task_name: str = None) -> Task:
        """创建页面抓取任务"""
        if not task_name:
            task_name = f"抓取: {url[:50]}"
        
        task = Task(
            task_name=task_name,
            status=TaskStatus.PENDING
        )
        db.add(task)
        db.commit()
        db.refresh(task)
        log.info(f"页面抓取任务创建成功 | ID: {task.id}, URL: {url}")
        return task

    @staticmethod
    async def run_crawl(task_id: int, url: str) -> AsyncGenerator[str, None]:
        """
        执行页面抓取流程（SSE事件流）
        """
        from app.db.database import SessionLocal

        db = SessionLocal()
        try:
            task = db.query(Task).filter(Task.id == task_id).first()
            if not task:
                yield json.dumps({"error": "任务不存在"}, ensure_ascii=False)
                return

            # 更新状态
            task.status = TaskStatus.PROCESSING
            db.commit()

            agent = PageCrawlerAgent()
            crawl_data = None

            try:
                async for step_data in agent.crawl_page(task_id, url):
                    if step_data.get("step") == "result":
                        crawl_data = step_data.get("data")
                    yield json.dumps(step_data, ensure_ascii=False)

                if crawl_data:
                    # 保存页面元素到数据库
                    elements = crawl_data.get("elements", [])
                    for el in elements:
                        page_el = PageElement(
                            task_id=task_id,
                            page_url=el.get("page_url", url),
                            tag_name=el.get("tag_name", ""),
                            element_text=el.get("element_text"),
                            element_id=el.get("element_id"),
                            element_class=el.get("element_class"),
                            element_name=el.get("element_name"),
                            placeholder=el.get("placeholder"),
                            href=el.get("href"),
                            aria_label=el.get("aria_label"),
                            role=el.get("role"),
                            xpath=el.get("xpath"),
                            css_selector=el.get("css_selector")
                        )
                        db.add(page_el)

                    yield json.dumps({"step": "保存数据", "progress": 90, "message": f"保存 {len(elements)} 个元素到数据库..."}, ensure_ascii=False)

                    # 生成Playwright测试脚本
                    test_script = PageCrawlerService._generate_script(url, elements)
                    script = Script(
                        task_id=task_id,
                        script_type="playwright",
                        script_content=test_script,
                        script_language="python"
                    )
                    db.add(script)

                    task.status = TaskStatus.SUCCESS
                    db.commit()
                    log.info(f"页面抓取完成 | ID: {task_id}, 元素: {len(elements)}")

                    yield json.dumps({
                        "step": "任务完成",
                        "progress": 100,
                        "message": "任务完成",
                        "test_script": test_script,
                        "element_count": len(elements)
                    }, ensure_ascii=False)

            except Exception as e:
                log.error(f"页面抓取失败 | ID: {task_id}, 错误: {e}")
                task.status = TaskStatus.FAILED
                task.error_message = str(e)
                db.commit()
                yield json.dumps({"error": str(e)}, ensure_ascii=False)

        finally:
            db.close()

    @staticmethod
    def _generate_script(url: str, elements: list) -> str:
        """根据抓取的真实DOM元素生成Playwright测试脚本"""
        lines = [
            '"""',
            f'自动生成的Playwright测试脚本',
            f'页面: {url}',
            '"""',
            'from playwright.sync_api import Page, expect',
            '',
            '',
            'def test_page(page: Page):',
            f'    """测试页面: {url}"""',
            f'    page.goto("{url}")',
            '',
        ]

        # 按类型分组生成测试步骤
        inputs = [e for e in elements if e["tag_name"] in ("input", "textarea")]
        buttons = [e for e in elements if e["tag_name"] == "button"]
        links = [e for e in elements if e["tag_name"] == "a" and e.get("element_text")]

        if inputs:
            lines.append('    # 输入框操作')
            for inp in inputs[:5]:
                selector = PageCrawlerService._best_selector(inp)
                placeholder = inp.get("placeholder") or inp.get("element_name") or "value"
                lines.append(f'    page.locator("{selector}").fill("test_{placeholder}")')
            lines.append('')

        if buttons:
            lines.append('    # 按钮操作')
            for btn in buttons[:3]:
                selector = PageCrawlerService._best_selector(btn)
                lines.append(f'    page.locator("{selector}").click()')
            lines.append('')

        if links[:3]:
            lines.append('    # 链接验证')
            for link in links[:3]:
                text = (link.get("element_text") or "")[:30]
                if text:
                    lines.append(f'    expect(page.get_by_text("{text}")).to_be_visible()')
            lines.append('')

        lines.append('    # 验证页面加载成功')
        lines.append(f'    expect(page).to_have_url("{url}")')
        lines.append('')

        return '\n'.join(lines)

    @staticmethod
    def _best_selector(el: dict) -> str:
        """选择最佳定位策略"""
        if el.get("element_id"):
            return f'#{el["element_id"]}'
        if el.get("aria_label"):
            return f'[aria-label="{el["aria_label"]}"]'
        if el.get("element_name"):
            return f'[name="{el["element_name"]}"]'
        if el.get("placeholder"):
            return f'[placeholder="{el["placeholder"]}"]'
        if el.get("css_selector"):
            return el["css_selector"]
        return el.get("xpath", el["tag_name"])

    @staticmethod
    def get_page_elements(db: Session, task_id: int) -> list:
        """获取任务的页面元素列表"""
        return db.query(PageElement).filter(
            PageElement.task_id == task_id
        ).all()
