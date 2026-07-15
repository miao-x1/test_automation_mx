"""
ReuseService - 脚本复用检查服务

统一封装脚本复用检查逻辑，供管道API、第一代流程、MCP工具共用。

执行顺序（调整后）：
  1. 需求解析（RequirementAgent）→ 结构化需求 (intent + steps)
  2. 基于结构化需求做复用检查
     ├─ 命中 → 直接返回历史脚本，跳过后续
     └─ 未命中 → 继续走RAG + 用例生成 + 脚本生成

两级检索策略：
  Level A: 快速预检 — 用原始文本做粗粒度检索（阈值0.95，1秒）
           极端相似时直接复用，连需求解析都省掉
  Level B: 精确检索 — 用结构化需求做语义检索（阈值0.90，1秒）
           解析后intent+steps匹配更准确

使用方式：
    from app.services.reuse_service import ReuseService

    # 快速预检（可选，在需求解析之前）
    result = ReuseService.quick_check(requirement="测试登录功能")
    if result["reuse"]:
        return result["script_content"]

    # 精确检索（在需求解析之后）
    result = ReuseService.check_reuse(
        requirement="测试登录功能",
        intent="login_test",
        steps=["打开登录页", "输入用户名", ...],
    )
    if result["reuse"]:
        return result["script_content"]
"""
import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReuseService:
    """脚本复用检查服务"""

    # 快速预检阈值（高阈值，只抓极端相似）
    QUICK_CHECK_THRESHOLD = 0.95
    # 精确检索阈值（标准阈值，基于结构化需求）
    PRECISE_CHECK_THRESHOLD = 0.90

    @staticmethod
    def quick_check(requirement: str) -> Dict[str, Any]:
        """
        快速预检 — 用原始文本做粗粒度检索

        在需求解析之前调用，只抓极端相似的情况。
        阈值0.95，只有几乎完全相同的需求才会命中。

        Args:
            requirement: 原始需求文本

        Returns:
            同 check_reuse() 的返回结构
        """
        try:
            from app.agent.script.script_reuse_agent import ScriptReuseAgent

            agent = ScriptReuseAgent()
            result = agent.check_reuse(requirement, top_k=1)

            similarity = result.get("similarity", 0)

            # 快速预检使用更高阈值
            if result.get("reuse") and similarity >= ReuseService.QUICK_CHECK_THRESHOLD:
                logger.info(
                    f"[ReuseService] 快速预检命中 | similarity={similarity}, "
                    f"script_name={result.get('script_name', '')}"
                )
                return ReuseService._build_reuse_result(result, similarity)

            logger.info(
                f"[ReuseService] 快速预检未命中 | similarity={similarity}, "
                f"threshold={ReuseService.QUICK_CHECK_THRESHOLD}"
            )
            return {
                "reuse": False,
                "similarity": similarity,
                "script_content": None,
                "script_name": result.get("script_name", ""),
                "degradation_info": None,
            }

        except Exception as e:
            logger.warning(f"[ReuseService] 快速预检失败: {e}")
            return {"reuse": False, "similarity": 0, "script_content": None, "degradation_info": None}

    @staticmethod
    def check_reuse(
        requirement: str,
        intent: str = "",
        steps: List[str] = None,
        top_k: int = 1,
    ) -> Dict[str, Any]:
        """
        精确检索 — 基于结构化需求做复用检查

        在需求解析之后调用，用解析后的intent+steps构建增强检索文本。
        阈值0.90，语义相似但表达不同的需求也能命中。

        Args:
            requirement: 原始需求文本
            intent: 需求意图（来自RequirementAgent解析）
            steps: 测试步骤列表（来自RequirementAgent解析）
            top_k: 检索数量

        Returns:
            {
                "reuse": bool,
                "similarity": float,
                "script_content": str,
                "script_name": str,
                "script_id": Optional[int],
                "task_id": Optional[int],
                "degradation_info": {...},
            }
        """
        try:
            from app.agent.script.script_reuse_agent import ScriptReuseAgent

            # 构建增强检索文本：融合原始需求 + 结构化解析结果
            enhanced_requirement = ReuseService._build_enhanced_text(
                requirement, intent, steps
            )

            agent = ScriptReuseAgent()
            result = agent.check_reuse(enhanced_requirement, top_k=top_k)

            if result.get("reuse"):
                similarity = result.get("similarity", 0)
                logger.info(
                    f"[ReuseService] 精确检索命中 | similarity={similarity}, "
                    f"intent={intent}, script_name={result.get('script_name', '')}"
                )
                return ReuseService._build_reuse_result(result, similarity)
            else:
                similarity = result.get("similarity", 0)
                logger.info(
                    f"[ReuseService] 精确检索未命中 | similarity={similarity}, "
                    f"threshold={ReuseService.PRECISE_CHECK_THRESHOLD}, intent={intent}"
                )
                return {
                    "reuse": False,
                    "similarity": similarity,
                    "script_content": None,
                    "script_name": result.get("script_name", ""),
                    "script_id": result.get("script_id"),
                    "task_id": result.get("task_id"),
                    "degradation_info": None,
                }

        except Exception as e:
            logger.warning(f"[ReuseService] 精确检索失败: {e}，继续生成新脚本")
            return {
                "reuse": False,
                "similarity": 0,
                "script_content": None,
                "degradation_info": None,
            }

    @staticmethod
    def _build_enhanced_text(
        requirement: str, intent: str, steps: List[str] = None
    ) -> str:
        """
        构建增强检索文本

        将原始需求 + 结构化解析结果融合为一个语义更丰富的文本，
        用于Embedding检索，提高匹配精度。

        示例：
            原始: "测试登录功能"
            增强: "测试登录功能\n意图: login_test\n步骤: 打开登录页, 输入用户名, 输入密码, 点击登录"
        """
        parts = [requirement]
        if intent:
            parts.append(f"意图: {intent}")
        if steps:
            parts.append(f"步骤: {', '.join(steps)}")
        return "\n".join(parts)

    @staticmethod
    def _build_reuse_result(result: Dict, similarity: float) -> Dict[str, Any]:
        """构建复用命中的返回结构"""
        return {
            "reuse": True,
            "similarity": similarity,
            "script_content": result.get("script_content", ""),
            "script_name": result.get("script_name", ""),
            "script_id": result.get("script_id"),
            "task_id": result.get("task_id"),
            "degradation_info": {
                "level": 0,
                "source": "reuse",
                "quality": "high" if similarity >= 0.95 else "medium",
                "action_required": similarity < 0.95,
                "message": f"已复用历史脚本（相似度: {similarity}）"
                           + ("" if similarity >= 0.95 else "，建议审查脚本适用性"),
            },
        }
