"""
RequirementUnderstandingAgent - L1 需求理解Agent

职责：将非结构化输入转换为"测试意图"（Test Intention）

L1 输出：features / entities / api_candidates / test_strategy

禁止行为：
- 禁止生成测试步骤
- 禁止生成请求结构
- 禁止生成代码
- 禁止执行测试
"""
import json
from typing import Any, Dict, List, Optional
from app.core.config import settings
from app.core.logger import log
from app.core.llm import call_llm
from app.agent.core.base import BaseAgent


class RequirementUnderstandingAgent(BaseAgent):
    """L1 需求理解 Agent - 输出测试意图，不涉及执行细节"""

    agent_name = "requirement_understanding"

    def __init__(self):
        super().__init__()
        self.model = None
        self.system_prompt = (
            "你是一个专业的测试架构师。你的任务是从需求中提取结构化测试意图，包括：\n"
            "1. 功能特性（features）：要测什么功能\n"
            "2. 业务实体（entities）：涉及哪些数据实体\n"
            "3. API候选（api_candidates）：可能涉及的接口路径\n"
            "4. 测试策略（test_strategy）：覆盖策略和优先级\n"
            "\n"
            "你只输出测试意图，不输出测试步骤、请求结构或代码。"
        )

    def execute(self, **kwargs) -> Any:
        return self.understand(**kwargs)

    def understand(
        self,
        requirement_context: str,
        source_type: str = "text",
        structured_data: Optional[Dict[str, Any]] = None,
        rag_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        理解需求，输出测试意图

        Args:
            requirement_context: 需求文本
            source_type: 输入类型
            structured_data: 结构化数据（如Swagger端点）
            rag_context: R2R检索结果

        Returns:
            {
                "requirement_id": str,
                "features": [{"name", "type", "risk_level", "test_focus"}],
                "entities": [str],
                "api_candidates": [str],
                "test_strategy": {"coverage", "priority"}
            }
        """
        log.info(f"RequirementUnderstandingAgent | 开始理解 | source_type={source_type}, context_len={len(requirement_context)}")

        prompt = self._build_prompt(requirement_context, source_type, structured_data, rag_context)

        try:
            raw = self._call_llm(prompt)
            result = self._parse_result(raw)
            self.emit("understood", {"feature_count": len(result.get("features", []))})
            log.info(f"RequirementUnderstandingAgent | 理解完成 | features={len(result.get('features', []))}")
            return result
        except Exception as e:
            log.error(f"RequirementUnderstandingAgent | 理解失败: {e}")
            return {"requirement_id": "", "features": [], "entities": [], "api_candidates": [], "test_strategy": {}, "error": str(e)}

    def _build_prompt(
        self,
        context: str,
        source_type: str,
        structured_data: Optional[Dict],
        rag_context: Optional[Dict],
    ) -> str:
        sections = [
            "# 任务：从需求中提取结构化测试意图\n",
            f"## 输入类型: {source_type}\n",
            f"## 需求内容\n{context[:6000]}\n",
        ]

        if structured_data:
            sections.append(f"\n## 结构化数据\n```json\n{json.dumps(structured_data, ensure_ascii=False)[:3000]}\n```\n")

        if rag_context:
            chunks = rag_context.get("all_chunks", [])
            if chunks:
                rag_text = "\n".join(c.get("text", "")[:200] for c in chunks[:5])
                sections.append(f"\n## 知识库参考\n{rag_text}\n")
            constraints = rag_context.get("constraints", [])
            if constraints:
                sections.append(f"\n## 业务约束\n{json.dumps(constraints, ensure_ascii=False)[:2000]}\n")
            apis = rag_context.get("apis", [])
            if apis:
                sections.append(f"\n## 已知API列表\n{json.dumps(apis, ensure_ascii=False)[:2000]}\n")

        sections.append("""
## 输出格式（严格JSON）
{
    "requirement_id": "REQ_001",
    "features": [
        {
            "name": "功能名称",
            "type": "API",
            "risk_level": "high",
            "test_focus": ["测试关注点1", "测试关注点2"]
        }
    ],
    "entities": ["实体1", "实体2"],
    "api_candidates": ["/api/xxx"],
    "test_strategy": {
        "coverage": "functional + negative + boundary",
        "priority": "P0"
    }
}

## type 可选值: API, UI, Flow, Data, Security
## risk_level 可选值: high, medium, low
## priority 可选值: P0, P1, P2, P3
## coverage 可选值: functional, negative, boundary, security, performance（可组合）

## 要求
1. features只描述'要测什么'，不描述'怎么测'
2. test_focus是每个feature的测试关注点（不超过6个）
3. entities是从需求中识别的业务实体
4. api_candidates是从需求中推断的API路径
5. test_strategy定义整体测试策略
6. 只输出JSON
""")
        return "\n".join(sections)

    def _call_llm(self, prompt: str) -> str:
        return call_llm(self.system_prompt, prompt, temperature=0.3)

    def _parse_result(self, raw: str) -> Dict[str, Any]:
        try:
            data = json.loads(raw)
            features = data.get("features", [])
            for f in features:
                # 兼容旧格式：title → name
                if "name" not in f and "title" in f:
                    f["name"] = f["title"]
                if "name" not in f:
                    f["name"] = "未命名功能"
                # 兼容旧格式：test_points → test_focus
                if "test_focus" not in f and "test_points" in f:
                    f["test_focus"] = f["test_points"]
                if "test_focus" not in f:
                    f["test_focus"] = []
                if "type" not in f:
                    f["type"] = "API"
                if "risk_level" not in f:
                    f["risk_level"] = "medium"
            return {
                "requirement_id": data.get("requirement_id", ""),
                "features": features,
                "entities": data.get("entities", []),
                "api_candidates": data.get("api_candidates", []),
                "test_strategy": data.get("test_strategy", {
                    "coverage": "functional + negative + boundary",
                    "priority": "P1",
                }),
            }
        except json.JSONDecodeError:
            log.warning(f"RequirementUnderstandingAgent | JSON解析失败: {raw[:200]}")
            return {"requirement_id": "", "features": [], "entities": [], "api_candidates": [], "test_strategy": {}}
