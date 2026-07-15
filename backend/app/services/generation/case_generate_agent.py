"""
CaseGenerateAgent - 用例生成

职责：根据需求和RAG上下文生成测试用例
输入：GenerationContext
输出：List[CaseDTO]

禁止：数据库/HTTP/文件
"""
import json
from typing import Any, Dict, Generator, List
from app.services.generation.context import GenerationContext, CaseDTO
from app.core.logger import log
from app.agents.factory import AgentRegistry


class CaseGenerateAgent:
    """用例生成Agent"""

    def generate(self, ctx: GenerationContext) -> List[CaseDTO]:
        """
        批量生成测试用例

        Args:
            ctx: 生成上下文

        Returns:
            用例DTO列表
        """
        results = []
        for case_data in self.generate_stream(ctx):
            results.append(case_data)
        return results

    def generate_stream(self, ctx: GenerationContext) -> Generator[CaseDTO, None, None]:
        """
        流式生成测试用例（逐条）

        Args:
            ctx: 生成上下文

        Yields:
            CaseDTO
        """
        try:
            compiler = AgentRegistry.create("case_agent")

            rag_context = ctx.rag if ctx.rag else {}
            gen = compiler.compile_stream(
                features=ctx.features,
                rag_context=rag_context,
                requirement_context=ctx.requirement_summary[:500],
            )

            for case_data in gen:
                case_dto = self._to_case_dto(case_data, ctx)
                yield case_dto

        except Exception as e:
            log.error(f"CaseGenerateAgent | 生成失败: {e}")

    def _to_case_dto(self, case_data: Dict, ctx: GenerationContext) -> CaseDTO:
        """将原始用例数据转换为CaseDTO"""
        # 推断asset_type
        from app.services.case.test_type_router import TestTypeRouter
        test_type = TestTypeRouter.route({
            "method": case_data.get("method", "POST"),
            "url": case_data.get("url", ""),
        })

        asset_type = "api"
        if test_type in ("UI", "WEB"):
            asset_type = "web"
        elif test_type == "ANDROID":
            asset_type = "android"

        # 构建steps（Case First：完整可执行用例）
        steps = case_data.get("steps", [])
        if not steps:
            # 从旧格式构建steps
            request_data = case_data.get("request", {})
            if request_data:
                steps = [{
                    "action": f"{request_data.get('method', 'POST')} {request_data.get('url', '')}",
                    "url": request_data.get("url", case_data.get("url", "")),
                    "method": request_data.get("method", case_data.get("method", "POST")),
                    "headers": request_data.get("headers", {}),
                    "body": request_data.get("body", {}),
                }]
            elif case_data.get("method") or case_data.get("url"):
                steps = [{
                    "action": f"{case_data.get('method', 'POST')} {case_data.get('url', '')}",
                    "url": case_data.get("url", ""),
                    "method": case_data.get("method", "POST"),
                    "headers": case_data.get("headers", {}),
                    "body": case_data.get("body", {}),
                }]

        # 构建assertions
        assertions = case_data.get("assertions", [])

        # 构建preconditions
        preconditions = case_data.get("preconditions", case_data.get("pre_steps", []))
        if isinstance(preconditions, str):
            preconditions = [preconditions]

        return CaseDTO(
            title=case_data.get("title", "未命名用例"),
            preconditions=preconditions,
            steps=steps,
            assertions=assertions,
            expected_result=case_data.get("expected_result", case_data.get("expected", "")),
            priority=case_data.get("priority", "P1"),
            tags=case_data.get("tags", []) if isinstance(case_data.get("tags"), list) else [],
            env=ctx.config.get("env", "test"),
            asset_type=asset_type,
            source_type="ai",
        )
