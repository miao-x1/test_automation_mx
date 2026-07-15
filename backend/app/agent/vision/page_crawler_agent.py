"""
PageCrawlerAgent - 使用Playwright抓取页面真实DOM元素

职责：
1. 打开页面并截图
2. 提取可交互DOM元素
3. 为每个元素生成真实定位器（locator）
4. 自动过滤隐藏元素和广告区域

定位器优先级：id > data-testid > aria-label > role > name > css_selector > xpath
"""
import asyncio
import uuid
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.core.config import settings
from app.core.logger import log


class PageCrawlerAgent(NewBaseAgent):
    """页面抓取Agent - 提取DOM元素并生成真实定位器"""

    agent_name = "page_crawler"
    capabilities = [AgentCapability.CRAWL]

    # 优先提取的标签
    PRIORITY_TAGS = {"button", "input", "textarea", "select", "option", "a", "form", "label", "table"}

    def __init__(self):
        self.agent_type = "page_crawler"
        self.model = None
        self.system_prompt = None

    # 需要额外检查交互属性的标签
    INTERACTIVE_ATTR_TAGS = {"div", "span", "p", "li", "ul", "ol", "nav", "header", "section"}

    # 交互属性（存在这些属性的div/span等也要提取）
    INTERACTIVE_ATTRS = {"onclick", "role", "aria-label", "tabindex", "data-testid"}

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.screenshot_dir = Path(settings.UPLOAD_DIR) / "screenshots"
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

    async def crawl_page(self, task_id: int, url: str) -> AsyncGenerator[Dict[str, Any], None]:
        """抓取页面元素（SSE事件流）"""
        yield {"step": "开始抓取页面", "progress": 5, "message": f"正在打开页面: {url}"}

        # 在独立线程中运行同步Playwright，避免Windows asyncio子进程问题
        import concurrent.futures
        try:
            loop = asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                result = await loop.run_in_executor(executor, self._crawl_sync, task_id, url)
        except Exception as e:
            import traceback
            err_msg = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
            log.error(f"Task {task_id} | 页面抓取失败: {err_msg}\n{traceback.format_exc()}")
            raise RuntimeError(f"页面抓取失败: {err_msg}") from e

        # 逐步yield结果
        for msg in result:
            yield msg

    def _crawl_sync(self, task_id: int, url: str) -> List[Dict[str, Any]]:
        """同步执行Playwright抓取（在线程池中运行）"""
        import sys
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

        from playwright.sync_api import sync_playwright

        messages = []

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                locale="zh-CN",
            )
            # 反自动化检测
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            """)
            page = context.new_page()

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # 等待页面稳定
                page.wait_for_timeout(3000)

                # 记录最终URL（处理重定向）
                final_url = page.url
                if final_url != url:
                    log.info(f"Task {task_id} | 页面重定向: {url} -> {final_url}")

                messages.append({"step": "打开页面成功", "progress": 15, "message": f"页面加载完成: {final_url}"})

                # 截图
                screenshot_name = f"{uuid.uuid4().hex}.png"
                screenshot_path = str(self.screenshot_dir / screenshot_name)
                page.screenshot(path=screenshot_path)
                messages.append({"step": "页面截图完成", "progress": 25, "message": "页面截图完成"})
                log.info(f"Task {task_id} | 截图保存: {screenshot_path}")

                # 提取元素
                messages.append({"step": "解析DOM", "progress": 35, "message": "正在提取可交互DOM元素..."})

                elements = self._extract_elements(page, final_url)

                # 统计日志
                tag_counts = {}
                for el in elements:
                    tag = el.get("tag_name", "unknown")
                    tag_counts[tag] = tag_counts.get(tag, 0) + 1

                stats_msg = " | ".join(f"{tag}: {count}" for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1]))
                log.info(f"Task {task_id} | DOM元素统计: {stats_msg}")

                messages.append({
                    "step": "解析DOM完成",
                    "progress": 80,
                    "message": f"提取到 {len(elements)} 个可交互DOM元素 ({stats_msg})"
                })

                messages.append({
                    "step": "result",
                    "progress": 90,
                    "message": f"DOM抓取完成，共 {len(elements)} 个元素",
                    "data": {
                        "url": url,
                        "screenshot_path": screenshot_path,
                        "elements": elements,
                        "element_count": len(elements),
                    }
                })

            except Exception as e:
                log.error(f"Task {task_id} | 页面抓取失败: {e}")
                raise
            finally:
                browser.close()

        return messages

    def _extract_elements(self, page, url: str) -> List[Dict[str, Any]]:
        """从页面提取可交互元素，自动生成定位器"""
        elements = page.evaluate("""(pageUrl) => {
            const priorityTags = ['button', 'input', 'textarea', 'select', 'option', 'a', 'form', 'label', 'table'];
            const interactiveAttrTags = ['div', 'span', 'p', 'li', 'ul', 'ol', 'nav', 'header', 'section', 'img', 'i', 'svg'];
            const interactiveAttrs = ['onclick', 'role', 'aria-label', 'tabindex', 'data-testid'];

            const allNodes = document.querySelectorAll('*');
            const results = [];
            const seenTexts = new Set();

            function getXPath(el) {
                if (el.id) return `//*[@id="${el.id}"]`;
                const parts = [];
                let current = el;
                while (current && current.nodeType === Node.ELEMENT_NODE) {
                    let idx = 0;
                    let sibling = current.previousSibling;
                    while (sibling) {
                        if (sibling.nodeType === Node.ELEMENT_NODE && sibling.nodeName === current.nodeName) idx++;
                        sibling = sibling.previousSibling;
                    }
                    const part = current.nodeName.toLowerCase() + (idx > 0 ? `[${idx + 1}]` : '');
                    parts.unshift(part);
                    current = current.parentNode;
                }
                return '/' + parts.join('/');
            }

            function getCssSelector(el) {
                if (el.id) return '#' + CSS.escape(el.id);
                let selector = el.tagName.toLowerCase();
                if (el.className && typeof el.className === 'string') {
                    const classes = el.className.trim().split(/\\s+/).filter(c => c && !c.includes(':') && !c.startsWith('sc-'));
                    if (classes.length > 0) {
                        selector += '.' + classes.slice(0, 2).map(c => CSS.escape(c)).join('.');
                    }
                }
                if (el.name) selector += `[name="${el.name}"]`;
                return selector;
            }

            function generateLocator(el) {
                if (el.id) return { locator: '#' + CSS.escape(el.id), priority: 100 };
                const testId = el.getAttribute('data-testid');
                if (testId) return { locator: `[data-testid="${testId}"]`, priority: 95 };
                const ariaLabel = el.getAttribute('aria-label');
                if (ariaLabel) return { locator: `[aria-label="${ariaLabel}"]`, priority: 90 };
                const role = el.getAttribute('role');
                if (role) return { locator: `[role="${role}"]`, priority: 85 };
                if (el.name) return { locator: `[name="${el.name}"]`, priority: 80 };
                const placeholder = el.getAttribute('placeholder');
                if (placeholder) return { locator: `[placeholder="${placeholder}"]`, priority: 75 };
                const css = getCssSelector(el);
                if (css && css !== el.tagName.toLowerCase()) return { locator: css, priority: 60 };
                return { locator: getXPath(el), priority: 40 };
            }

            function isHidden(el) {
                const style = window.getComputedStyle(el);
                if (style.display === 'none') return true;
                if (style.visibility === 'hidden') return true;
                if (style.opacity === '0') return true;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 && rect.height === 0) return true;
                if (rect.top > window.innerHeight + 200) return true;
                return false;
            }

            function isAdElement(el) {
                const adClasses = ['ad', 'ads', 'advertisement', 'banner', 'sponsor', 'promo'];
                const classStr = (el.className || '').toLowerCase();
                const idStr = (el.id || '').toLowerCase();
                for (const ad of adClasses) {
                    if (classStr.includes(ad) || idStr.includes(ad)) return true;
                }
                return false;
            }

            function shouldExtract(el) {
                const tag = el.tagName.toLowerCase();
                if (priorityTags.includes(tag)) return true;
                if (interactiveAttrTags.includes(tag)) {
                    for (const attr of interactiveAttrs) {
                        if (el.hasAttribute(attr)) return true;
                    }
                    if (el.hasAttribute('href')) return true;
                }
                return false;
            }

            allNodes.forEach((el, index) => {
                if (index >= 2000) return;
                if (!shouldExtract(el)) return;
                if (isHidden(el)) return;
                if (isAdElement(el)) return;

                const tag = el.tagName.toLowerCase();
                const text = (el.innerText || el.textContent || '').trim().substring(0, 100);

                const dedupeKey = `${tag}:${text}`;
                if (text && seenTexts.has(dedupeKey)) return;
                if (text) seenTexts.add(dedupeKey);

                const { locator, priority } = generateLocator(el);

                results.push({
                    tag_name: tag,
                    element_text: text || null,
                    element_id: el.id || null,
                    element_class: el.className && typeof el.className === 'string' ? el.className.substring(0, 500) : null,
                    element_name: el.getAttribute('name') || null,
                    placeholder: el.getAttribute('placeholder') || null,
                    href: el.getAttribute('href') || null,
                    aria_label: el.getAttribute('aria-label') || null,
                    role: el.getAttribute('role') || null,
                    data_testid: el.getAttribute('data-testid') || null,
                    xpath: getXPath(el),
                    css_selector: getCssSelector(el),
                    locator: locator,
                    locator_priority: priority,
                    page_url: pageUrl,
                });
            });

            return results;
        }""", url)

        log.info(f"提取到 {len(elements)} 个可交互DOM元素")
        return elements
