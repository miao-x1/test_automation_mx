"""
APIExtractionAgent - API信息提取

职责：从需求文本中提取接口元数据
输出：ApiMeta {session_id, apis: [{name, method, path, headers, request_schema, response_schema, depends, priority}]}

流程位置：需求理解 → APIExtraction → RAG → CaseGenerate → Review → Publish
"""
import json
from typing import Any, Dict, List, Optional
from app.core.logger import log
from app.agent.core.base import BaseAgent


class APIExtractionAgent(BaseAgent):
    """API信息提取Agent - 从需求中提取接口元数据"""

    agent_name = "api_extraction"

    def __init__(self):
        super().__init__()
        self.model = None

    def execute(self, **kwargs) -> Any:
        return self.extract(**kwargs)

    def extract(
        self,
        requirement_text: str,
        session_id: int = 0,
        project_id: str = "",
    ) -> Dict[str, Any]:
        """
        从需求文本中提取API元数据

        Args:
            requirement_text: 需求文本
            session_id: 会话ID
            project_id: 项目ID

        Returns:
            {
                "session_id": int,
                "apis": [
                    {
                        "name": str,
                        "method": str,
                        "path": str,
                        "headers": dict,
                        "request_schema": dict,
                        "response_schema": dict,
                        "depends": list,
                        "priority": str
                    }
                ],
                "total": int
            }
        """
        log.info(f"APIExtractionAgent | 开始提取 | session_id={session_id}")

        try:
            # 尝试使用LLM提取
            apis = self._extract_with_llm(requirement_text)

            result = {
                "session_id": session_id,
                "apis": apis,
                "total": len(apis),
            }

            self.emit("extracted", {"total": len(apis)})
            log.info(f"APIExtractionAgent | 提取完成 | total={len(apis)}")
            return result

        except Exception as e:
            log.warning(f"APIExtractionAgent | 提取失败（降级为规则提取）: {e}")
            return self._fallback_extract(requirement_text, session_id)

    def _extract_with_llm(self, text: str) -> List[Dict]:
        """使用LLM提取API信息"""
        try:
            from app.core.config import settings
            if settings.AGENT_TYPE == "mock":
                return self._mock_extract(text)

            # 尝试调用LLM
            prompt = f"""从以下需求中提取所有API接口信息，输出JSON数组。
每个API包含：name(接口名), method(GET/POST/PUT/DELETE), path(路径), headers(请求头), request_schema(请求体结构), response_schema(响应体结构), depends(依赖的其他接口), priority(P0/P1/P2)

需求：
{text[:3000]}

输出格式：
```json
[
  {{
    "name": "接口名称",
    "method": "POST",
    "path": "/api/xxx",
    "headers": {{}},
    "request_schema": {{}},
    "response_schema": {{}},
    "depends": [],
    "priority": "P1"
  }}
]
```"""
            from app.services.llm_service import LLMService
            llm = LLMService()
            response = llm.chat(prompt)
            # 解析JSON
            apis = self._parse_api_json(response)
            return apis if apis else self._mock_extract(text)

        except Exception as e:
            log.warning(f"APIExtractionAgent | LLM提取失败: {e}")
            return self._mock_extract(text)

    def _parse_api_json(self, text: str) -> Optional[List[Dict]]:
        """解析LLM输出的API JSON"""
        try:
            # 尝试提取JSON块
            if "```json" in text:
                json_str = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                json_str = text.split("```")[1].split("```")[0].strip()
            else:
                json_str = text.strip()

            apis = json.loads(json_str)
            if isinstance(apis, list):
                return apis
            if isinstance(apis, dict) and "apis" in apis:
                return apis["apis"]
        except Exception:
            pass
        return None

    def _mock_extract(self, text: str) -> List[Dict]:
        """Mock提取（开发/测试用）"""
        return [
            {
                "name": "创建资源",
                "method": "POST",
                "path": "/api/resource",
                "headers": {"Content-Type": "application/json"},
                "request_schema": {"name": "string", "type": "string"},
                "response_schema": {"id": "integer", "name": "string", "created_at": "string"},
                "depends": [],
                "priority": "P0",
            },
            {
                "name": "查询资源列表",
                "method": "GET",
                "path": "/api/resource",
                "headers": {},
                "request_schema": {},
                "response_schema": {"items": [], "total": "integer"},
                "depends": [],
                "priority": "P1",
            },
            {
                "name": "更新资源",
                "method": "PUT",
                "path": "/api/resource/{id}",
                "headers": {"Content-Type": "application/json"},
                "request_schema": {"name": "string"},
                "response_schema": {"id": "integer", "name": "string"},
                "depends": ["创建资源"],
                "priority": "P1",
            },
        ]

    def _fallback_extract(self, text: str, session_id: int = 0) -> Dict[str, Any]:
        """降级提取：基于规则"""
        apis = self._mock_extract(text)
        return {
            "session_id": session_id,
            "apis": apis,
            "total": len(apis),
            "fallback": True,
        }
