"""
ElementAgent - Vision视觉分析Agent

职责：识别页面截图中可交互的UI元素
核心原则：只识别可交互元素，过滤营销文案和纯展示文本
"""
import asyncio
import json
import base64
import httpx
from typing import AsyncGenerator, Dict, Any, List
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from pathlib import Path
from app.core.config import settings
from app.core.logger import log
from app.core.upload_paths import resolve_upload_path


class ElementAgent(NewBaseAgent):
    """页面元素分析Agent - 使用通义千问Vision模型"""

    agent_name = "element"
    capabilities = [AgentCapability.VISION]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        # 优先从 ApplicationContainer 获取预初始化的 VisionService
        self._vision_service = None
        try:
            from app.bootstrap import get_container
            container = get_container()
            if container.is_initialized:
                vs = container.vision_service
                self.api_key = vs.api_key
                self.api_url = vs.api_url
                self.model = vs.model
                self._vision_service = vs
                log.info(f"ElementAgent初始化完成 | 从Container获取Vision配置 | model: {self.model}")
                return
        except Exception:
            pass
        # 降级: 直接从 settings 读取 (兼容未初始化 Container 的场景)
        self.api_key = settings.QWEN_API_KEY
        self.api_url = settings.QWEN_API_URL or "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
        self.model = settings.QWEN_MODEL or "qwen-vl-plus"
        self.system_prompt = None
        log.info(f"ElementAgent初始化完成 | 从settings读取配置 | model: {self.model}")

    def _encode_image(self, image_path: str) -> str:
        resolved = resolve_upload_path(image_path)
        if not Path(resolved).is_file():
            raise FileNotFoundError(f"图片不存在或无法读取: {image_path}")
        with open(resolved, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _get_image_mime(self, image_path: str) -> str:
        lower = image_path.lower()
        if lower.endswith(".png"):
            return "image/png"
        elif lower.endswith(".webp"):
            return "image/webp"
        return "image/jpeg"

    VISION_PROMPT = """你是一名资深UI自动化测试工程师。
你的职责：识别页面中可交互的UI元素，并从浏览器地址栏中提取页面URL。

【第一步：识别地址栏URL】
请仔细观察截图顶部的浏览器地址栏，提取完整的URL地址。如果地址栏不可见或无法识别，则page_url设为null。

【第二步：识别可交互元素】
识别优先级：
P0（必须识别）：Button、Input、SearchBox、Textarea、Checkbox、Radio、Select、Dropdown、Menu、Tab、Link
P1（重要识别）：Form、Dialog、Modal、Popup、Pagination、Table
P2（辅助识别）：Image（可点击的）、Icon（可点击的）

【严格过滤规则 - 以下内容禁止输出】
- 广告、营销文案、运营活动、推荐语
- 优惠信息、红包信息、福利信息
- 商品介绍、说明文字、纯展示文本

【输出格式 - 严格JSON，禁止任何解释】
{
  "page_type": "页面类型",
  "page_url": "https://www.example.com/path",
  "elements": [
    {
      "name": "搜索输入框",
      "type": "input",
      "text": "",
      "role": "searchbox",
      "label": "搜索",
      "placeholder": "请输入关键词",
      "id": "可见的稳定id，没有则空",
      "html_name": "input的name属性，没有则空",
      "css": "稳定CSS如 input[name=q]，禁止随机class",
      "test_id": "data-testid，没有则空",
      "aria_label": "aria-label，没有则空",
      "clickable": true,
      "confidence": 95
    },
    {
      "name": "搜索按钮",
      "type": "button",
      "text": "搜索",
      "role": "button",
      "label": "",
      "placeholder": "",
      "id": "",
      "html_name": "",
      "css": "",
      "test_id": "",
      "aria_label": "",
      "clickable": true,
      "confidence": 95
    }
  ]
}

page_url：从浏览器地址栏识别的完整URL，无法识别时为null
type只能是：button、input、searchbox、textarea、checkbox、radio、select、dropdown、menu、tab、link、form、dialog、modal、popup、pagination、table、img
confidence范围：0-100，表示该元素对自动化测试的重要程度
clickable：该元素是否可点击/可交互

要求：
1. 优先识别地址栏URL，这对生成可执行测试脚本至关重要
2. 只输出可交互元素，不要输出纯文本
3. 每个元素必须有name和type
4. 能从截图读到的 id / name / placeholder / aria-label / data-testid / 稳定CSS 必须输出，读不到则空字符串
5. 只输出JSON，不要有任何解释文字"""

    async def _call_vision_api(self, image_path: str) -> Dict[str, Any]:
        if not self.api_key:
            raise Exception("QWEN_API_KEY 未配置，请在 .env 文件中设置 QWEN_API_KEY")

        image_base64 = self._encode_image(image_path)
        mime_type = self._get_image_mime(image_path)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}
                    },
                    {"type": "text", "text": self.VISION_PROMPT}
                ]
            }
        ]

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 4096,
            "temperature": 0.1
        }

        # 优先使用 Container 中预建的共享 httpx 客户端
        if self._vision_service is not None:
            log.info(f"调用千问Vision API | model: {self.model} | 使用共享HTTP客户端")
            response = await self._vision_service.client.post(
                self.api_url, headers=headers, json=payload
            )
        else:
            # 降级: 每次创建新客户端 (兼容未初始化 Container 的场景)
            log.info(f"调用千问Vision API | model: {self.model} | 使用临时HTTP客户端")
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    self.api_url, headers=headers, json=payload
                )

        if response.status_code != 200:
            error_text = response.text
            log.error(f"千问API调用失败 | 状态码: {response.status_code}, 响应: {error_text[:300]}")
            raise Exception(f"API调用失败: {response.status_code} - {error_text[:200]}")

        result = response.json()

        choices = result.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            log.error(f"千问API返回异常 | 完整响应: {json.dumps(result, ensure_ascii=False)[:500]}")
            raise Exception(f"API返回数据异常: 无choices字段或为空")

        message = choices[0].get("message", {})
        content = message.get("content")
        if not content:
            raise Exception("API返回内容为空")

        log.info(f"千问API返回: {content[:300]}...")

        # 解析JSON（处理markdown代码块包裹）
        content = content.strip()
        if content.startswith("```"):
            lines = content.split("\n")
            end_idx = len(lines) - 1
            for i in range(len(lines) - 1, 0, -1):
                if lines[i].strip().startswith("```"):
                    end_idx = i
                    break
            content = "\n".join(lines[1:end_idx])

        return json.loads(content)

    def execute(self, **kwargs) -> Any:
        """执行元素分析（BaseAgent抽象方法实现）

        管道兼容：支持 image_path（单数）和 image_paths（复数，取第一张）
        """
        image_path = kwargs.get("image_path", "")
        if not image_path:
            image_paths = kwargs.get("image_paths", [])
            if image_paths and isinstance(image_paths, list):
                image_path = image_paths[0]
            elif image_paths and isinstance(image_paths, str):
                image_path = image_paths
        task_id = kwargs.get("task_id", 0)
        if not image_path:
            return {
                "status": "INVALID_INPUT",
                "elements": [],
                "page_url": "",
                "page_type": "",
                "message": "请上传页面截图，或提供可访问的页面 URL",
            }
        resolved = resolve_upload_path(image_path)
        if not Path(resolved).is_file():
            return {
                "status": "FAILED",
                "elements": [],
                "page_url": "",
                "page_type": "",
                "message": f"图片不存在或无法读取: {image_path}",
            }
        # 同步包装：实际调用方应使用 analyze_image 异步方法
        loop = asyncio.get_event_loop()
        result = None
        async def _collect():
            nonlocal result
            async for step in self.analyze_image(task_id, resolved):
                if step.get("step") == "result":
                    result = step.get("data")
        try:
            loop.run_until_complete(_collect())
        except Exception as exc:
            return {
                "status": "FAILED",
                "elements": [],
                "page_url": "",
                "page_type": "",
                "message": f"页面图片识别失败: {exc}",
            }
        if not result:
            return {"status": "FAILED", "elements": [], "page_url": "", "page_type": "", "message": "图片识别未返回结果"}
        result["status"] = "SUCCESS"
        return result

    def analyze(self, input_data: dict) -> Dict[str, Any]:
        """同步分析入口（兼容 dict 参数调用）"""
        image_path = input_data.get("image_path", "")
        if not image_path:
            image_paths = input_data.get("image_paths", [])
            if image_paths and isinstance(image_paths, list):
                image_path = image_paths[0]
        if not image_path:
            return {
                "status": "INVALID_INPUT",
                "elements": [],
                "page_url": "",
                "page_type": "",
                "message": "请上传页面截图，或提供可访问的页面 URL",
            }
        return self.execute(image_path=image_path, task_id=input_data.get("task_id", 0))

    async def analyze_image(
        self,
        task_id: int,
        image_path: str
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """分析页面截图，提取可交互UI元素"""
        yield {"step": "开始分析", "progress": 10, "message": "正在加载图片..."}
        await asyncio.sleep(0.3)

        yield {"step": "调用AI", "progress": 20, "message": "正在调用AI模型识别可交互元素..."}

        try:
            api_result = await self._call_vision_api(image_path)
        except Exception as e:
            log.error(f"Task {task_id} | API调用失败: {e}")
            yield {"step": "错误", "progress": 0, "message": f"AI分析失败: {e}"}
            raise

        elements = api_result.get("elements", [])
        page_type = api_result.get("page_type", "未知页面")
        page_url = api_result.get("page_url")

        # 过滤低置信度和不可交互元素
        elements = [e for e in elements if e.get("confidence", 0) >= 30 and e.get("clickable", True)]

        log.info(f"Task {task_id} | Vision识别到 {len(elements)} 个可交互元素, 页面类型: {page_type}, 识别URL: {page_url}")

        # 逐类型报告
        type_counts = {}
        for el in elements:
            t = el.get("type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1

        progress = 30
        type_names = {
            "button": "按钮", "input": "输入框", "searchbox": "搜索框",
            "textarea": "文本域", "checkbox": "复选框", "radio": "单选框",
            "select": "下拉框", "dropdown": "下拉菜单", "menu": "菜单",
            "tab": "标签页", "link": "链接", "form": "表单",
            "dialog": "对话框", "modal": "弹窗", "popup": "弹出层",
            "pagination": "分页", "table": "表格", "img": "图片",
        }

        for el_type, count in type_counts.items():
            progress = min(progress + 8, 85)
            type_label = type_names.get(el_type, el_type)
            yield {"step": f"识别{type_label}", "progress": progress, "message": f"识别到 {count} 个{type_label}"}
            await asyncio.sleep(0.2)

        if page_url:
            yield {"step": "识别地址栏URL", "progress": 88, "message": f"识别到页面URL: {page_url}"}
        else:
            yield {"step": "地址栏URL未识别", "progress": 88, "message": "未识别到地址栏URL，将仅使用Vision分析结果"}

        yield {"step": "保存结果", "progress": 90, "message": "正在保存Vision分析结果..."}

        analysis_result = {
            "status": "SUCCESS",
            "page_type": page_type,
            "page_url": page_url,
            "elements": elements,
        }

        yield {"step": "result", "progress": 100, "message": f"Vision分析完成，识别到 {len(elements)} 个可交互元素" + (f"，识别到URL: {page_url}" if page_url else ""), "data": analysis_result}
