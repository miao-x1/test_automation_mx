"""
InputRouter - 多模态输入路由器

根据输入类型分发到对应的Parser：
- TextParser: 纯文本需求解析
- VisionParser: 图片需求解析（调用视觉LLM）
- UrlParser: URL需求解析（DOM抓取）
- ScriptParser: 脚本需求解析（复用检测）

融合：FusionAgent 将多路解析结果融合为 UnifiedRequirement
"""
import json
import re
from typing import Dict, Any, List, Optional
from app.core.logger import log
from app.core.config import settings
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class ParseResult:
    """解析结果基类"""

    def __init__(self, source: str, success: bool = True):
        self.source = source
        self.success = success
        self.intent = ""
        self.summary = ""
        self.steps: List[str] = []
        self.keywords: List[str] = []
        self.target_url = ""
        self.elements: List[Dict] = []
        self.extra: Dict[str, Any] = {}

    def to_dict(self) -> Dict:
        return {
            "source": self.source,
            "success": self.success,
            "intent": self.intent,
            "summary": self.summary,
            "steps": self.steps,
            "keywords": self.keywords,
            "target_url": self.target_url,
            "elements": self.elements,
            "extra": self.extra,
        }


class TextParser:
    """文本需求解析器"""

    def parse(self, text: str) -> ParseResult:
        result = ParseResult(source="text")
        if not text or not text.strip():
            result.success = False
            return result

        result.summary = text.strip()
        result.steps = self._extract_steps(text)
        result.keywords = self._extract_keywords(text)
        result.target_url = self._extract_url(text)
        result.intent = self._infer_intent(text)
        return result

    def _extract_steps(self, text: str) -> List[str]:
        """从文本中提取步骤"""
        steps = []
        # 匹配数字序号步骤: 1. xxx / 1、xxx
        numbered = re.findall(r'(?:^|\n)\s*\d+[.、)\s]+(.+?)(?=\n\s*\d+[.、)]|$)', text, re.DOTALL)
        if numbered:
            steps = [s.strip() for s in numbered if s.strip()]
        else:
            # 匹配"先...然后...最后..."模式
            flow_words = re.split(r'[，,；;]\s*(?:然后|接着|再|之后|最后)\s*', text)
            if len(flow_words) > 1:
                steps = [s.strip() for s in flow_words if s.strip()]
            else:
                steps = [text.strip()]
        return steps

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        # 移除常见停用词
        stopwords = {'的', '了', '在', '是', '我', '有', '和', '就', '不', '人', '都', '一', '一个', '上', '也', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'}
        words = re.findall(r'[\u4e00-\u9fff]{2,4}|[a-zA-Z]{2,}', text)
        keywords = [w for w in words if w not in stopwords]
        return keywords[:10]

    def _extract_url(self, text: str) -> str:
        """提取URL"""
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        match = re.search(url_pattern, text)
        return match.group(0) if match else ""

    def _infer_intent(self, text: str) -> str:
        """推断意图"""
        test_keywords = ['测试', '验证', '检查', '检测', 'test', 'verify', 'check']
        for kw in test_keywords:
            if kw in text.lower():
                # 尝试提取测试对象
                match = re.search(r'(?:测试|验证|检查|检测|test|verify|check)\s*([^\s,，。.]{1,20})', text, re.IGNORECASE)
                if match:
                    return f"{match.group(1)}_test"
        return "general_test"


class VisionParser:
    """图片需求解析器 - 调用视觉LLM分析UI截图"""

    def parse(self, image_paths: List[str]) -> ParseResult:
        result = ParseResult(source="vision")
        if not image_paths:
            result.success = False
            return result

        try:
            from app.core.config import settings as app_settings
            api_key = app_settings.QWEN_API_KEY
            if not api_key:
                log.warning("VisionParser: 未配置QWEN_API_KEY，降级为简单解析")
                return self._fallback_parse(image_paths)

            # 构建多图消息
            content_items = []
            content_items.append({
                "type": "text",
                "text": "请分析以下UI截图，提取测试需求信息。输出JSON格式：\n"
                        "{\n"
                        "  \"intent\": \"测试意图标识\",\n"
                        "  \"summary\": \"需求概述\",\n"
                        "  \"steps\": [\"操作步骤1\", \"操作步骤2\"],\n"
                        "  \"keywords\": [\"关键词1\", \"关键词2\"],\n"
                        "  \"elements\": [{\"name\": \"元素名\", \"type\": \"按钮/输入框/链接\", \"action\": \"点击/输入\"}],\n"
                        "  \"page_type\": \"登录页/注册页/搜索页/列表页/详情页/其他\"\n"
                        "}"
            })

            for img_path in image_paths:
                import base64
                from pathlib import Path
                full_path = Path(app_settings.UPLOAD_DIR) / img_path
                if full_path.exists():
                    with open(full_path, "rb") as f:
                        b64 = base64.b64encode(f.read()).decode()
                    content_items.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"}
                    })

            if len(content_items) <= 1:
                # 没有有效图片
                result.success = False
                result.extra["error"] = "图片文件不存在"
                return result

            import httpx
            url = app_settings.QWEN_API_URL
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }
            # 使用视觉模型
            model = app_settings.QWEN_MODEL
            if "-plus" in model and "-vl-" not in model:
                model = model.replace("-plus", "-vl-plus")
            if "-max" in model and "-vl-" not in model:
                model = model.replace("-max", "-vl-max")

            payload = {
                "model": model,
                "messages": [
                    {"role": "user", "content": content_items}
                ],
                "temperature": 0.2,
            }

            response = httpx.post(url, json=payload, headers=headers, timeout=60)
            resp_json = response.json()

            if "choices" in resp_json and resp_json["choices"]:
                content = resp_json["choices"][0]["message"]["content"]
                # 提取JSON
                json_match = re.search(r'\{[\s\S]*\}', content)
                if json_match:
                    parsed = json.loads(json_match.group())
                    result.intent = parsed.get("intent", "vision_test")
                    result.summary = parsed.get("summary", "")
                    result.steps = parsed.get("steps", [])
                    result.keywords = parsed.get("keywords", [])
                    result.elements = parsed.get("elements", [])
                    result.extra["page_type"] = parsed.get("page_type", "其他")
                else:
                    result.summary = content[:200]
                    result.steps = [content[:100]]
            else:
                result.success = False
                result.extra["error"] = "LLM返回格式异常"

        except Exception as e:
            log.error(f"VisionParser异常: {e}", exc_info=True)
            return self._fallback_parse(image_paths)

        return result

    def _fallback_parse(self, image_paths: List[str]) -> ParseResult:
        """降级解析：无法调用LLM时使用"""
        result = ParseResult(source="vision_fallback")
        result.summary = f"基于{len(image_paths)}张UI截图的测试需求"
        result.intent = "ui_test"
        result.steps = ["分析UI截图", "识别页面元素", "生成测试步骤"]
        result.keywords = ["UI截图", "页面测试"]
        result.extra["image_count"] = len(image_paths)
        return result


class UrlParser:
    """URL需求解析器 - 抓取页面DOM提取信息"""

    def parse(self, urls: List[str]) -> ParseResult:
        result = ParseResult(source="url")
        if not urls:
            result.success = False
            return result

        primary_url = urls[0]
        result.target_url = primary_url
        result.intent = self._infer_intent_from_url(primary_url)
        result.keywords = self._extract_domain_keywords(primary_url)

        # 尝试抓取页面标题和基本信息
        try:
            import httpx
            resp = httpx.get(primary_url, timeout=10, follow_redirects=True)
            if resp.status_code == 200:
                html = resp.text
                # 提取title
                title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
                if title_match:
                    page_title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                    result.extra["page_title"] = page_title
                    result.summary = f"测试页面: {page_title} ({primary_url})"

                # 提取meta description
                desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
                if desc_match:
                    result.extra["page_description"] = desc_match.group(1)

                # 提取表单和链接信息
                forms = re.findall(r'<form[^>]*>', html, re.IGNORECASE)
                links = re.findall(r'<a[^>]*href=["\'](.*?)["\']', html, re.IGNORECASE)
                inputs = re.findall(r'<input[^>]*type=["\'](.*?)["\']', html, re.IGNORECASE)

                result.extra["form_count"] = len(forms)
                result.extra["link_count"] = len(links)
                result.extra["input_types"] = list(set(inputs))

                # 生成基本步骤
                if forms:
                    result.steps.append("填写表单字段")
                    result.steps.append("提交表单")
                if links:
                    result.steps.append("验证页面链接可访问")
                result.steps.insert(0, f"访问 {primary_url}")

        except Exception as e:
            log.warning(f"UrlParser抓取失败: {e}")
            result.summary = f"测试URL: {primary_url}"
            result.steps = [f"访问 {primary_url}", "验证页面加载", "检查页面元素"]

        if not result.summary:
            result.summary = f"测试URL: {primary_url}"

        return result

    def _infer_intent_from_url(self, url: str) -> str:
        """从URL推断意图"""
        url_lower = url.lower()
        intent_map = {
            'login': 'login_test',
            'signin': 'login_test',
            'register': 'register_test',
            'signup': 'register_test',
            'search': 'search_test',
            'cart': 'cart_test',
            'checkout': 'checkout_test',
            'order': 'order_test',
            'profile': 'profile_test',
            'dashboard': 'dashboard_test',
            'api': 'api_test',
        }
        for key, intent in intent_map.items():
            if key in url_lower:
                return intent
        return "url_test"

    def _extract_domain_keywords(self, url: str) -> List[str]:
        """从URL提取域名关键词"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.replace("www.", "")
            parts = domain.split(".")
            return [p for p in parts if p and p not in ("com", "cn", "org", "net", "io")][:3]
        except Exception:
            return []


class ScriptParser:
    """脚本需求解析器 - 解析上传的脚本，检测可复用性"""

    def parse(self, script_content: str, script_language: str = "python") -> ParseResult:
        result = ParseResult(source="script")
        if not script_content or not script_content.strip():
            result.success = False
            return result

        result.extra["script_language"] = script_language
        result.extra["script_length"] = len(script_content)

        # 提取脚本中的关键信息
        if script_language in ("python", "py"):
            result = self._parse_python(script_content, result)
        elif script_language in ("javascript", "js", "ts"):
            result = self._parse_javascript(script_content, result)
        elif script_language == "yaml":
            result = self._parse_yaml(script_content, result)
        else:
            result.summary = f"上传的{script_language}脚本"
            result.steps = ["复用已有脚本逻辑"]
            result.keywords = [script_language]

        result.intent = "script_reuse"
        return result

    def _parse_python(self, content: str, result: ParseResult) -> ParseResult:
        """解析Python脚本"""
        # 提取函数名
        functions = re.findall(r'def\s+(\w+)\s*\(', content)
        # 提取类名
        classes = re.findall(r'class\s+(\w+)', content)
        # 提取URL
        urls = re.findall(r'https?://[^\s<>"\']+', content)
        # 提取选择器
        selectors = re.findall(r'(?:selector|locator|css|xpath)\s*[=:]\s*["\']([^"\']+)["\']', content, re.IGNORECASE)
        # 提取注释中的描述
        comments = re.findall(r'#\s*(.+)', content)
        docstrings = re.findall(r'"""([\s\S]*?)"""', content)

        result.extra["functions"] = functions
        result.extra["classes"] = classes
        result.extra["selectors"] = selectors

        if urls:
            result.target_url = urls[0]
            result.extra["urls"] = urls

        # 生成摘要
        if docstrings:
            result.summary = docstrings[0].strip()[:200]
        elif comments:
            result.summary = comments[0].strip()[:200]
        else:
            result.summary = f"Python脚本，包含{len(functions)}个函数"

        result.steps = [f"执行函数: {fn}" for fn in functions[:5]] if functions else ["执行脚本"]
        result.keywords = functions[:5] + classes[:3]

        return result

    def _parse_javascript(self, content: str, result: ParseResult) -> ParseResult:
        """解析JavaScript脚本"""
        functions = re.findall(r'(?:function\s+(\w+)|(?:const|let|var)\s+(\w+)\s*=\s*(?:async\s+)?(?:\([^)]*\)|[^=])\s*=>)', content)
        func_names = [f[0] or f[1] for f in functions if f[0] or f[1]]
        urls = re.findall(r'https?://[^\s<>"\']+', content)
        selectors = re.findall(r'(?:selector|locator|css|xpath)\s*[=:]\s*["\']([^"\']+)["\']', content, re.IGNORECASE)

        result.extra["functions"] = func_names
        result.extra["selectors"] = selectors

        if urls:
            result.target_url = urls[0]
            result.extra["urls"] = urls

        result.summary = f"JavaScript脚本，包含{len(func_names)}个函数"
        result.steps = [f"执行: {fn}" for fn in func_names[:5]] if func_names else ["执行脚本"]
        result.keywords = func_names[:5]

        return result

    def _parse_yaml(self, content: str, result: ParseResult) -> ParseResult:
        """解析YAML脚本"""
        try:
            import yaml
            parsed = yaml.safe_load(content)
            if isinstance(parsed, dict):
                result.extra["yaml_keys"] = list(parsed.keys())
                if "name" in parsed:
                    result.summary = f"YAML测试: {parsed['name']}"
                if "steps" in parsed and isinstance(parsed["steps"], list):
                    result.steps = [s.get("name", str(s)) if isinstance(s, dict) else str(s) for s in parsed["steps"]]
        except Exception:
            result.summary = "YAML格式脚本"
            result.steps = ["执行YAML脚本"]

        result.keywords = ["yaml", "配置化测试"]
        return result


class InputRouter(NewBaseAgent):
    """
    多模态输入路由器

    根据输入内容自动分发到对应的Parser，并推荐处理模式
    """

    agent_name = "input_router"
    display_name = "Input Router"
    description = "多模态输入路由器 - 根据输入类型分发到对应的Parser"
    capabilities = [AgentCapability.INTENT_ROUTE]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self.text_parser = TextParser()
        self.vision_parser = VisionParser()
        self.url_parser = UrlParser()
        self.script_parser = ScriptParser()

    def route(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        路由输入到对应的Parser

        Args:
            input_data: {
                text: str,
                images: list[str],
                urls: list[str],
                script_content: str,
                script_language: str,
                page_ids: list[int]
            }

        Returns:
            {
                mode: str,  # 推荐模式
                recommended_mode: str,  # AI推荐模式
                recommended_reason: str,
                parse_results: list[ParseResult],
            }
        """
        text = input_data.get("text", "")
        images = input_data.get("images", [])
        urls = input_data.get("urls", [])
        script_content = input_data.get("script_content", "")
        script_language = input_data.get("script_language", "python")
        page_ids = input_data.get("page_ids", [])

        parse_results = []
        active_modes = []

        # 分发到各Parser
        if text and text.strip():
            result = self.text_parser.parse(text)
            parse_results.append(result)
            active_modes.append("text")

        if images:
            result = self.vision_parser.parse(images)
            parse_results.append(result)
            active_modes.append("image")

        if urls:
            result = self.url_parser.parse(urls)
            parse_results.append(result)
            active_modes.append("url")

        if script_content and script_content.strip():
            result = self.script_parser.parse(script_content, script_language)
            parse_results.append(result)
            active_modes.append("script")

        # 确定模式和推荐
        mode, recommended_mode, recommended_reason = self._determine_mode(
            active_modes, images, urls, script_content, text
        )

        return {
            "mode": mode,
            "recommended_mode": recommended_mode,
            "recommended_reason": recommended_reason,
            "parse_results": [r.to_dict() for r in parse_results],
            "active_modes": active_modes,
        }

    def _determine_mode(
        self, active_modes: List[str], images: List, urls: List,
        script_content: str, text: str
    ) -> tuple:
        """确定输入模式和推荐模式"""
        if len(active_modes) > 1:
            mode = "mixed"
        elif active_modes:
            mode = active_modes[0]
        else:
            mode = "text"

        # 智能推荐
        recommended_mode = ""
        recommended_reason = ""

        if images and not text:
            recommended_mode = "vision"
            recommended_reason = "检测到图片输入，推荐使用Vision模式进行UI元素识别和需求提取"
        elif images and text:
            recommended_mode = "vision"
            recommended_reason = "检测到图片+文本混合输入，Vision模式可增强图片中的UI元素理解"
        elif urls and not text:
            recommended_mode = "dom"
            recommended_reason = "检测到URL输入，推荐使用DOM模式自动抓取页面结构和元素"
        elif urls and text:
            recommended_mode = "dom"
            recommended_reason = "检测到URL+文本输入，DOM模式可自动提取页面元素辅助测试"
        elif script_content:
            recommended_mode = "reuse"
            recommended_reason = "检测到脚本输入，推荐使用复用模式，基于已有脚本逻辑生成测试"
        elif text:
            recommended_mode = "text"
            recommended_reason = "纯文本输入，使用标准文本解析模式"

        return mode, recommended_mode, recommended_reason
