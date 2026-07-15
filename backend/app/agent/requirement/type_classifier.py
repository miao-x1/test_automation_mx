"""
TypeClassifier - 测试类型自动分类器

根据需求内容、URL、脚本等多模态输入自动判断测试类型：
- URL → WEB
- swagger/openapi → API
- apk/android → ANDROID
- TPS/QPS/并发 → PERFORMANCE

规则优先级：
1. 强制规则（swagger → API, apk → ANDROID）
2. URL特征规则（http/https → WEB）
3. 关键词权重规则
4. 默认回退 → WEB
"""
import re
from typing import Dict, Any, List, Optional
from enum import Enum
from app.core.logger import log
from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability


class TestType(str, Enum):
    WEB = "web"
    API = "api"
    ANDROID = "android"
    PERFORMANCE = "performance"


class ClassifyResult:
    """分类结果"""
    def __init__(self):
        self.task_type: TestType = TestType.WEB
        self.confidence: float = 0.5
        self.reason: str = ""
        self.scores: Dict[str, float] = {}
        self.detected_signals: List[str] = []

    def to_dict(self) -> Dict:
        return {
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "scores": self.scores,
            "detected_signals": self.detected_signals,
        }


class TypeClassifier(NewBaseAgent):
    """测试类型自动分类器"""

    agent_name = "type_classify"
    display_name = "Type Classifier"
    description = "测试类型自动分类器 - 根据需求内容自动判断测试类型"
    capabilities = [AgentCapability.TYPE_CLASSIFY]

    # 强制规则：匹配到直接决定类型
    FORCE_RULES = [
        {"patterns": [r'\bswagger\b', r'\bopenapi\b', r'\bapi-docs?\b', r'/v[123]/api', r'\bschema\.json\b'], "type": TestType.API, "signal": "检测到Swagger/OpenAPI特征"},
        {"patterns": [r'\.apk\b', r'\bandroid\b', r'\b安卓\b', r'\bapp测试\b', r'\bAPP测试\b', r'\b移动端测试\b'], "type": TestType.ANDROID, "signal": "检测到Android/App特征"},
        {"patterns": [r'\bTPS\b', r'\bQPS\b', r'\b压测\b', r'\b压力测试\b', r'\b负载测试\b', r'\b并发测试\b', r'\bbenchmark\b'], "type": TestType.PERFORMANCE, "signal": "检测到性能测试特征"},
    ]

    # 关键词权重表
    KEYWORDS: Dict[str, Dict[str, float]] = {
        "web": {
            "页面": 3, "网页": 3, "浏览器": 3, "UI": 2, "界面": 2,
            "点击": 2, "输入": 2, "截图": 2, "登录": 1, "搜索": 1,
            "按钮": 2, "表单": 2, "弹窗": 2, "导航": 1, "前端": 2,
            "购物车": 1, "注册": 1, "提交": 1, "URL": 2, "网址": 2,
            "网站": 2, "渲染": 2, "交互": 2, "下拉": 1, "拖拽": 1,
        },
        "api": {
            "接口": 3, "API": 3, "请求": 3, "返回值": 3, "响应": 2,
            "状态码": 3, "JSON": 2, "REST": 3, "HTTP": 2, "GET": 2,
            "POST": 2, "PUT": 2, "DELETE": 2, "端点": 3, "endpoint": 3,
            "鉴权": 2, "token": 2, "webhook": 3, "幂等": 3, "微服务": 2,
        },
        "performance": {
            "性能": 3, "压力": 3, "并发": 3, "响应时间": 3, "吞吐量": 3,
            "负载": 3, "QPS": 3, "TPS": 3, "延迟": 2, "吞吐": 2,
            "容量": 2, "瓶颈": 2, "压测": 3, "benchmark": 3, "高并发": 3,
            "大流量": 2, "慢查询": 2, "超时率": 2, "资源占用": 2,
        },
        "android": {
            "android": 3, "安卓": 3, "app": 2, "APP": 2, "移动端": 3,
            "手机": 2, "iOS": 2, "原生": 2, "小程序": 2, "触摸": 2,
            "手势": 2, "推送": 2, "权限": 1, "机型": 2, "适配": 1,
        },
    }

    # URL特征规则
    URL_RULES = [
        {"pattern": r'swagger|api-docs|openapi|/api/v\d', "type": TestType.API, "signal": "URL包含API文档特征"},
        {"pattern": r'\.apk|play\.google|apps\.apple', "type": TestType.ANDROID, "signal": "URL包含应用商店特征"},
        {"pattern": r'https?://', "type": TestType.WEB, "signal": "检测到HTTP URL"},
    ]

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    def classify(
        self,
        text: str = "",
        urls: List[str] = None,
        script_content: str = "",
        script_language: str = "",
        images: List[str] = None,
    ) -> ClassifyResult:
        """
        自动分类测试类型

        Args:
            text: 需求文本
            urls: URL列表
            script_content: 脚本内容
            script_language: 脚本语言
            images: 图片路径列表

        Returns:
            ClassifyResult
        """
        result = ClassifyResult()
        urls = urls or []
        images = images or []
        combined_text = f"{text} {' '.join(urls)} {script_content}".lower()

        # 1. 强制规则（最高优先级）
        for rule in self.FORCE_RULES:
            for pattern in rule["patterns"]:
                if re.search(pattern, combined_text, re.IGNORECASE):
                    result.task_type = rule["type"]
                    result.detected_signals.append(rule["signal"])
                    result.confidence = 0.95
                    result.reason = rule["signal"]
                    result.scores = self._compute_scores(combined_text)
                    result.scores[rule["type"].value] = 10.0
                    log.info(f"TypeClassifier强制规则命中 | type={rule['type'].value}, signal={rule['signal']}")
                    return result

        # 2. URL特征规则
        for url in urls:
            for rule in self.URL_RULES:
                if re.search(rule["pattern"], url, re.IGNORECASE):
                    result.task_type = rule["type"]
                    result.detected_signals.append(rule["signal"])
                    result.confidence = 0.8
                    result.reason = rule["signal"]
                    result.scores = self._compute_scores(combined_text)
                    log.info(f"TypeClassifier URL规则命中 | type={rule['type'].value}, url={url[:50]}")
                    return result

        # 3. 脚本特征规则
        script_type = self._detect_from_script(script_content, script_language)
        if script_type:
            result.task_type = script_type
            result.confidence = 0.7
            result.reason = f"从脚本内容推断为{script_type.value}"
            result.detected_signals.append(result.reason)
            result.scores = self._compute_scores(combined_text)
            return result

        # 4. 图片特征（有截图 → WEB）
        if images and not text:
            result.task_type = TestType.WEB
            result.confidence = 0.6
            result.reason = "检测到UI截图，推断为Web测试"
            result.detected_signals.append(result.reason)
            result.scores = self._compute_scores(combined_text)
            return result

        # 5. 关键词权重评分
        scores = self._compute_scores(combined_text)
        result.scores = scores

        if all(v == 0 for v in scores.values()):
            scores["web"] = 1.0

        max_type = max(scores, key=scores.get)
        max_score = scores[max_type]
        total = sum(scores.values())

        result.task_type = TestType(max_type)
        result.confidence = min(max_score / max(total, 1) + 0.3, 1.0) if total > 0 else 0.5

        # 生成原因
        type_labels = {"web": "Web测试", "api": "接口测试", "performance": "性能测试", "android": "Android测试"}
        result.reason = f"识别为{type_labels.get(max_type, max_type)}({max_score:.0f}分)"

        log.info(f"TypeClassifier分类 | type={result.task_type.value}, confidence={result.confidence:.2f}")
        return result

    def _compute_scores(self, text: str) -> Dict[str, float]:
        """计算各类型得分"""
        scores = {"web": 0.0, "api": 0.0, "performance": 0.0, "android": 0.0}
        text_lower = text.lower()

        for type_name, keywords in self.KEYWORDS.items():
            for keyword, weight in keywords.items():
                if keyword.lower() in text_lower:
                    scores[type_name] += weight

        return scores

    def _detect_from_script(self, content: str, language: str) -> Optional[TestType]:
        """从脚本内容推断类型"""
        if not content:
            return None

        content_lower = content.lower()

        # Playwright/Midscene → WEB
        if any(kw in content_lower for kw in ["playwright", "midscene", "page.goto", "browser.new_page", "aiAction"]):
            return TestType.WEB

        # requests/httpx → API
        if any(kw in content_lower for kw in ["requests.", "httpx.", "api_client", "base_url", "endpoint"]):
            return TestType.API

        # locust/k6 → PERFORMANCE
        if any(kw in content_lower for kw in ["locust", "k6", "artillery", "wrk", "ab -"]):
            return TestType.PERFORMANCE

        # appium → ANDROID
        if any(kw in content_lower for kw in ["appium", "desired_caps", "mobile:", "android.driver"]):
            return TestType.ANDROID

        return None
