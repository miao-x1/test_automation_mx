"""
TestTypeClassifierAgent - 测试类型智能识别Agent

职责：
  分析用户输入的需求（文本/图片/Swagger/数据库结构/页面信息），
  自动判断测试类型、平台、框架，并给出置信度。

输出格式：
  {
    test_type:  WEB | API | ANDROID | PERFORMANCE
    platform:   browser | mobile | server
    framework:  playwright | appium | pytest | jmeter
    confidence: 0-1
  }

设计：
  1. 规则引擎优先（TypeClassifier 已有完善的规则体系）
  2. LLM 增强（当规则置信度较低时，调用LLM进行语义理解）
  3. 强制映射（test_type → platform/framework 固定映射表）
"""
import json
from typing import Any, Dict, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.agent.requirement.type_classifier import TypeClassifier, TestType, ClassifyResult
from app.core.logger import log


# ================================================================== #
#  类型 → 平台/框架 映射表                                              #
# ================================================================== #

TYPE_PLATFORM_MAP: Dict[str, str] = {
    "web": "browser",
    "api": "server",
    "android": "mobile",
    "performance": "server",
}

TYPE_FRAMEWORK_MAP: Dict[str, str] = {
    "web": "playwright",
    "api": "pytest",
    "android": "appium",
    "performance": "jmeter",
}

TYPE_LABELS: Dict[str, str] = {
    "web": "Web自动化测试",
    "api": "API接口测试",
    "android": "Android移动端测试",
    "performance": "性能测试",
}


class TestTypeClassifierAgent(NewBaseAgent):
    """
    测试类型智能识别Agent

    使用规则引擎 + LLM混合方式判断测试类型。
    规则引擎优先，当置信度低于阈值时调用LLM增强。
    """

    agent_name = "test_type_classifier"
    display_name = "Test Type Classifier Agent"
    description = "测试类型智能识别Agent - 分析需求自动判断测试类型/平台/框架"
    capabilities = [AgentCapability.TYPE_CLASSIFY]

    # LLM增强阈值：规则置信度低于此值时调用LLM
    LLM_CONFIDENCE_THRESHOLD = 0.7

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)
        self._rule_classifier = TypeClassifier(config=config, runtime=runtime, session_id=session_id)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行测试类型分类

        支持的参数：
          - requirement: 需求文本
          - urls: URL列表
          - script_content: 脚本内容
          - script_language: 脚本语言
          - images: 图片路径列表
          - swagger_content: Swagger/OpenAPI JSON内容
          - db_schema: 数据库结构信息
          - page_info: 页面信息

        Returns:
            {
                "test_type": "web" | "api" | "android" | "performance",
                "platform": "browser" | "mobile" | "server",
                "framework": "playwright" | "appium" | "pytest" | "jmeter",
                "confidence": 0.0-1.0,
                "reason": str,
                "scores": Dict[str, float],
                "detected_signals": List[str],
            }
        """
        requirement = kwargs.get("requirement", "")
        urls = kwargs.get("urls", [])
        script_content = kwargs.get("script_content", "")
        script_language = kwargs.get("script_language", "")
        images = kwargs.get("images", [])
        swagger_content = kwargs.get("swagger_content", "")
        db_schema = kwargs.get("db_schema", "")
        page_info = kwargs.get("page_info", "")

        # 合并附加信息到需求文本
        combined_text = requirement
        if swagger_content:
            combined_text += f"\n[Swagger] {swagger_content[:2000]}"
        if db_schema:
            combined_text += f"\n[DB Schema] {db_schema[:2000]}"
        if page_info:
            combined_text += f"\n[Page Info] {page_info[:2000]}"

        # 第一步：规则引擎分类
        result = self._rule_classifier.classify(
            text=combined_text,
            urls=urls,
            script_content=script_content,
            script_language=script_language,
            images=images,
        )

        log.info(
            f"TestTypeClassifierAgent规则分类 | "
            f"type={result.task_type.value}, confidence={result.confidence:.2f}"
        )

        # 第二步：如果置信度较低，尝试LLM增强
        if result.confidence < self.LLM_CONFIDENCE_THRESHOLD:
            llm_result = await self._llm_classify(combined_text, urls, images, swagger_content, db_schema, page_info)
            if llm_result:
                # LLM结果与规则一致 → 提升置信度
                if llm_result["test_type"] == result.task_type.value:
                    result.confidence = max(result.confidence, llm_result["confidence"])
                    result.detected_signals.append("LLM增强确认")
                    log.info(f"TestTypeClassifierAgent LLM确认规则结果 | type={result.task_type.value}")
                else:
                    # LLM结果与规则不一致 → 取LLM结果（LLM语义理解更准）
                    result.task_type = TestType(llm_result["test_type"])
                    result.confidence = llm_result["confidence"]
                    result.reason = f"LLM判断: {llm_result.get('reason', '')}"
                    result.detected_signals.append("LLM覆盖规则结果")
                    log.info(
                        f"TestTypeClassifierAgent LLM覆盖 | "
                        f"规则={result.task_type.value} → LLM={llm_result['test_type']}"
                    )

        # 第三步：映射 platform 和 framework
        test_type_value = result.task_type.value
        platform = TYPE_PLATFORM_MAP.get(test_type_value, "browser")
        framework = TYPE_FRAMEWORK_MAP.get(test_type_value, "playwright")

        output = {
            "test_type": test_type_value,
            "platform": platform,
            "framework": framework,
            "confidence": round(result.confidence, 4),
            "reason": result.reason,
            "scores": result.scores,
            "detected_signals": result.detected_signals,
        }

        log.info(
            f"TestTypeClassifierAgent 最终结果 | "
            f"type={output['test_type']}, platform={output['platform']}, "
            f"framework={output['framework']}, confidence={output['confidence']}"
        )

        return output

    async def _llm_classify(
        self,
        text: str,
        urls: List[str],
        images: List[str],
        swagger_content: str,
        db_schema: str,
        page_info: str,
    ) -> Optional[Dict[str, Any]]:
        """
        调用LLM进行语义级分类

        当规则引擎置信度不足时使用。
        返回 None 表示LLM不可用或解析失败。
        """
        try:
            from app.services.model_service import get_model_service

            model_service = get_model_service()
            if not model_service:
                log.warning("TestTypeClassifierAgent LLM不可用，跳过增强")
                return None

            prompt = self._build_llm_prompt(text, urls, images, swagger_content, db_schema, page_info)

            system_prompt = (
                "你是测试架构师。请分析用户的需求，判断最适合的自动化测试类型。\n"
                "只返回JSON，不要其他内容。格式：\n"
                '{"test_type":"web|api|android|performance","confidence":0.0-1.0,"reason":"简短原因"}\n\n'
                "判断标准：\n"
                "- web: 涉及网页、浏览器、UI交互、页面操作\n"
                "- api: 涉及接口、请求、REST、GraphQL、Swagger\n"
                "- android: 涉及App、安卓、移动端、APK\n"
                "- performance: 涉及压测、并发、TPS/QPS、负载、性能瓶颈"
            )

            response = await model_service.chat(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                model_name="qwen-plus",
                temperature=0.1,
                max_tokens=256,
            )

            # 解析LLM返回
            if isinstance(response, dict):
                content = response.get("content", "")
            elif isinstance(response, str):
                content = response
            else:
                content = str(response)

            # 提取JSON
            content = content.strip()
            if content.startswith("```"):
                # 去掉markdown代码块标记
                lines = content.split("\n")
                content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

            data = json.loads(content)
            test_type = data.get("test_type", "").lower().strip()

            # 验证test_type合法
            valid_types = {"web", "api", "android", "performance"}
            if test_type not in valid_types:
                log.warning(f"TestTypeClassifierAgent LLM返回非法类型: {test_type}")
                return None

            return {
                "test_type": test_type,
                "confidence": float(data.get("confidence", 0.5)),
                "reason": data.get("reason", ""),
            }

        except Exception as e:
            log.warning(f"TestTypeClassifierAgent LLM分类失败: {e}")
            return None

    def _build_llm_prompt(
        self,
        text: str,
        urls: List[str],
        images: List[str],
        swagger_content: str,
        db_schema: str,
        page_info: str,
    ) -> str:
        """构建LLM提示词"""
        parts = [f"需求: {text[:3000]}"]

        if urls:
            parts.append(f"URL: {', '.join(urls[:5])}")
        if images:
            parts.append(f"图片数量: {len(images)}")
        if swagger_content:
            parts.append(f"Swagger: {swagger_content[:500]}")
        if db_schema:
            parts.append(f"数据库结构: {db_schema[:500]}")
        if page_info:
            parts.append(f"页面信息: {page_info[:500]}")

        return "\n".join(parts)

    def classify_sync(
        self,
        text: str = "",
        urls: List[str] = None,
        script_content: str = "",
        script_language: str = "",
        images: List[str] = None,
        swagger_content: str = "",
        db_schema: str = "",
        page_info: str = "",
    ) -> Dict[str, Any]:
        """
        同步分类接口（不调用LLM，仅规则引擎）

        适用于需要快速响应的场景。
        """
        urls = urls or []
        images = images or []

        combined_text = text
        if swagger_content:
            combined_text += f"\n[Swagger] {swagger_content[:2000]}"
        if db_schema:
            combined_text += f"\n[DB Schema] {db_schema[:2000]}"
        if page_info:
            combined_text += f"\n[Page Info] {page_info[:2000]}"

        result = self._rule_classifier.classify(
            text=combined_text,
            urls=urls,
            script_content=script_content,
            script_language=script_language,
            images=images,
        )

        test_type_value = result.task_type.value
        platform = TYPE_PLATFORM_MAP.get(test_type_value, "browser")
        framework = TYPE_FRAMEWORK_MAP.get(test_type_value, "playwright")

        return {
            "test_type": test_type_value,
            "platform": platform,
            "framework": framework,
            "confidence": round(result.confidence, 4),
            "reason": result.reason,
            "scores": result.scores,
            "detected_signals": result.detected_signals,
        }
