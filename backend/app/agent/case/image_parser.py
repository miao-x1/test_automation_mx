"""
ImageParserAgent - 图片解析Agent

职责：解析用户上传的页面截图，使用通义千问VL视觉模型识别：
- 页面上的UI元素（按钮、输入框、链接等）
- 页面布局和结构
- 可操作的交互点
- 业务流程意图

输出格式与DocumentParserAgent一致：
  {
      "requirement_context": str,   # 从图片中提取的需求描述
      "structured_data": dict,      # 结构化元素信息
      "source_type": "image"
  }
"""
import base64
import json
import os
import time as _time
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.agent.core.base import BaseAgent


class ImageParserAgent(BaseAgent):
    """图片解析Agent - 使用VL视觉模型分析页面截图"""

    agent_name = "image_parser"

    # 支持的图片格式
    SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}

    def __init__(self):
        super().__init__()
        self.model = settings.QWEN_MODEL  # qwen-vl-plus（视觉模型）
        self.system_prompt = (
            "你是一个专业的UI测试分析师。"
            "用户会上传页面截图，你需要分析图片中的UI元素、布局结构和交互点，"
            "并将其转化为结构化的测试需求描述。"
        )

    def execute(self, **kwargs) -> Any:
        """统一执行入口"""
        return self.parse(**kwargs)

    def parse(self, task_id: int, source_type: str = "image", **kwargs) -> Dict[str, Any]:
        """
        解析图片输入

        Args:
            task_id: 用例任务ID
            source_type: 输入类型
            **kwargs: file_path（图片路径）, raw_text（附加上下文）

        Returns:
            {
                "requirement_context": str,
                "structured_data": dict,
                "source_type": "image"
            }
        """
        file_path = kwargs.get("file_path", "")
        raw_text = kwargs.get("raw_text", "")

        log.info(f"ImageParserAgent | 开始解析 | file={file_path}, task_id={task_id}")

        if not file_path or not os.path.exists(file_path):
            log.warning(f"ImageParserAgent | 文件不存在: {file_path}")
            return {
                "requirement_context": raw_text or "图片文件不存在",
                "structured_data": {},
                "source_type": "image",
                "error": "file not found",
            }

        # 检查格式
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in self.SUPPORTED_FORMATS:
            log.warning(f"ImageParserAgent | 不支持的格式: {ext}")
            return {
                "requirement_context": raw_text or f"不支持的图片格式: {ext}",
                "structured_data": {},
                "source_type": "image",
                "error": f"unsupported format: {ext}",
            }

        try:
            # 编码图片为base64
            image_b64 = self._encode_image(file_path)
            if not image_b64:
                return {
                    "requirement_context": raw_text or "图片编码失败",
                    "structured_data": {},
                    "source_type": "image",
                    "error": "image encoding failed",
                }

            # 调用VL模型分析
            analysis = self._analyze_image(image_b64, ext, raw_text)

            self.emit("parsed", {"task_id": task_id, "source_type": "image"})
            log.info(
                f"ImageParserAgent | 解析完成 | "
                f"elements={len(analysis.get('elements', []))}, "
                f"actions={len(analysis.get('suggested_actions', []))}"
            )

            return {
                "requirement_context": analysis.get("requirement_description", ""),
                "structured_data": {
                    "elements": analysis.get("elements", []),
                    "page_type": analysis.get("page_type", ""),
                    "suggested_actions": analysis.get("suggested_actions", []),
                    "layout_summary": analysis.get("layout_summary", ""),
                    "file_path": file_path,
                },
                "source_type": "image",
            }

        except Exception as e:
            log.error(f"ImageParserAgent | 解析失败 | error={e}")
            return {
                "requirement_context": raw_text or f"图片解析失败: {e}",
                "structured_data": {},
                "source_type": "image",
                "error": str(e),
            }

    def _encode_image(self, file_path: str) -> Optional[str]:
        """将图片文件编码为base64"""
        try:
            file_size = os.path.getsize(file_path)
            if file_size > 10 * 1024 * 1024:  # 10MB
                log.warning(f"ImageParserAgent | 图片过大: {file_size} bytes")
                # TODO: 可在此处添加图片压缩逻辑

            with open(file_path, "rb") as f:
                image_data = f.read()

            return base64.b64encode(image_data).decode("utf-8")

        except Exception as e:
            log.error(f"ImageParserAgent | 图片编码失败: {e}")
            return None

    def _analyze_image(self, image_b64: str, ext: str, user_context: str = "") -> Dict[str, Any]:
        """
        调用通义千问VL模型分析图片

        Args:
            image_b64: base64编码的图片
            ext: 图片扩展名
            user_context: 用户附带的文字说明

        Returns:
            {
                "requirement_description": str,
                "elements": [{name, type, locator_hint, description}],
                "page_type": str,
                "suggested_actions": [{action, target, description}],
                "layout_summary": str
            }
        """
        import httpx

        api_key = settings.QWEN_API_KEY
        if not api_key:
            raise ValueError("未配置 QWEN_API_KEY（VL模型需要通义千问API）")

        url = settings.QWEN_API_URL
        mime_type = self._get_mime_type(ext)

        # 构建多模态消息
        user_content = f"""请分析这张页面截图，提取UI元素和交互信息。

{f"用户附加说明：{user_context}" if user_context else ""}

请按以下JSON格式输出（不要输出其他内容）：
{{
    "page_type": "页面类型（如：登录页/注册页/列表页/详情页/表单页/首页/购物车页等）",
    "layout_summary": "页面布局描述（1-2句话）",
    "requirement_description": "基于图片内容生成的测试需求描述，包含页面名称、主要功能和测试重点",
    "elements": [
        {{
            "name": "元素名称（如：用户名输入框）",
            "type": "元素类型（input/button/link/text/image/dropdown/checkbox/radio/select/textarea）",
            "locator_hint": "定位提示（如：页面顶部左侧、导航栏右侧等）",
            "description": "元素说明"
        }}
    ],
    "suggested_actions": [
        {{
            "action": "建议的测试操作（如：输入用户名/点击登录按钮/验证错误提示等）",
            "target": "目标元素名称",
            "description": "操作说明"
        }}
    ]
}}

要求：
1. 尽可能识别所有可见的交互元素（按钮、输入框、链接、下拉框等）
2. requirement_description 要包含完整的测试场景描述
3. suggested_actions 要覆盖正常流程和异常场景
4. 只输出JSON"""

        payload = {
            "model": self.model,  # qwen-vl-plus（视觉模型）
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_b64}"}},
                        {"type": "text", "text": user_content},
                    ],
                },
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        _start = _time.time()
        log.info(f"ImageParserAgent | 调用VL模型 | model={self.model}")

        response = httpx.post(url, json=payload, headers=headers, timeout=120)
        result = response.json()

        if "choices" not in result:
            raise RuntimeError(f"VL模型API错误: {result}")

        content = result["choices"][0]["message"]["content"]
        _elapsed = _time.time() - _start
        log.info(f"ImageParserAgent | VL模型返回 | content_length={len(content)} | 耗时={_elapsed:.2f}s")

        return self._parse_vl_result(content)

    def _parse_vl_result(self, raw: str) -> Dict[str, Any]:
        """解析VL模型返回的JSON"""
        try:
            cleaned = raw.strip()
            if cleaned.startswith("```json"):
                cleaned = cleaned[7:]
            if cleaned.startswith("```"):
                cleaned = cleaned[3:]
            if cleaned.endswith("```"):
                cleaned = cleaned[:-3]
            cleaned = cleaned.strip()

            data = json.loads(cleaned)

            return {
                "page_type": data.get("page_type", "未知页面"),
                "layout_summary": data.get("layout_summary", ""),
                "requirement_description": data.get("requirement_description", ""),
                "elements": data.get("elements", []),
                "suggested_actions": data.get("suggested_actions", []),
            }
        except (json.JSONDecodeError, Exception) as e:
            log.warning(f"ImageParserAgent | JSON解析失败: {e}, raw={raw[:200]}")
            return {
                "page_type": "未知页面",
                "layout_summary": "",
                "requirement_description": raw[:500],
                "elements": [],
                "suggested_actions": [],
            }

    @staticmethod
    def _get_mime_type(ext: str) -> str:
        """获取图片的MIME类型"""
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".bmp": "image/bmp",
        }
        return mime_map.get(ext.lower(), "image/png")
