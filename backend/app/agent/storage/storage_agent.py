"""
StorageAgent - 脚本存储 Agent

将脚本和用例存储到数据库 + Milvus 向量化 + Neo4j 知识更新。
作为管道步骤在 script_generator 之后、execution_agent 之前执行。

架构约束：
  Agent 禁止直接导入 app.db.milvus_client，
  所有 Milvus 写入通过 StorageRouter 统一路由。

所有操作均 try/except，失败返回 degraded 状态但不抛异常（required: False）。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability
from app.agents.factory import AgentRegistry
from app.db.collection_constants import SCRIPT_COLLECTION

logger = logging.getLogger(__name__)


class StorageAgent(NewBaseAgent):
    """存储Agent - 脚本入库 + Milvus向量化 + Neo4j知识更新"""

    agent_name = "storage_agent"
    display_name = "存储Agent"
    capabilities = [AgentCapability.KNOWLEDGE_UPDATE]

    def store(
        self,
        test_script: Any,
        requirement: str = "",
        task_id: int = 0,
        test_cases: Any = None,
    ) -> Dict[str, Any]:
        """
        将脚本和用例存储到数据库 + Milvus + Neo4j

        Args:
            test_script: 脚本数据（dict 含 script_content, 或纯字符串）
            requirement: 原始需求
            task_id: 任务ID
            test_cases: 测试用例列表

        Returns:
            {
                "status": "success" | "degraded",
                "script_id": Optional[int],
                "milvus_count": int,
                "neo4j_count": int,
                "message": str,
            }
        """
        # 提取 script_content
        if isinstance(test_script, dict):
            script_content = test_script.get("script_content", "")
        elif isinstance(test_script, str):
            script_content = test_script
        else:
            script_content = str(test_script)

        if not script_content:
            return {
                "status": "degraded",
                "script_id": None,
                "milvus_count": 0,
                "neo4j_count": 0,
                "message": "脚本内容为空，跳过存储",
            }

        result = {
            "status": "success",
            "script_id": None,
            "milvus_count": 0,
            "neo4j_count": 0,
            "message": "",
        }

        # 1. 保存脚本到数据库
        try:
            from app.services.context_router.storage_router import get_storage_router

            storage = get_storage_router()
            script_id = storage.mysql_save("Script", {
                "script_name": f"task_{task_id}_script" if task_id else f"auto_{hash(script_content) % 10000}",
                "script_content": script_content,
                "script_language": "python",
                "framework": "playwright",
                "task_id": task_id if task_id else None,
                "description": requirement[:200] if requirement else "",
            })
            result["script_id"] = script_id
            if script_id:
                logger.info(f"[StorageAgent] 脚本保存到数据库 | script_id={script_id}")
            else:
                raise Exception("mysql_save returned None")
        except Exception as e:
            logger.warning(f"[StorageAgent] 保存脚本到数据库失败: {e}")
            result["status"] = "degraded"
            result["message"] = f"保存脚本失败: {e}"

        # 2. Milvus 向量化
        try:
            from app.services.context_router.storage_router import get_storage_router

            embed_agent = AgentRegistry.create("embedding_agent")
            embed_text = (requirement[:500] if requirement else script_content[:500])
            script_vector = embed_agent._embed([embed_text])

            if script_vector:
                storage = get_storage_router()
                storage.milvus_insert(SCRIPT_COLLECTION, [{
                    "id": hash(f"task_{task_id}_script") & 0x7FFFFFFF if task_id else hash("auto_script") & 0x7FFFFFFF,
                    "task_id": task_id or 0,
                    "script_name": f"task_{task_id}_script" if task_id else "auto_script",
                    "script_content": script_content[:8000],
                    "description": embed_text,
                    "vector": script_vector[0],
                }])
                result["milvus_count"] = 1
                logger.info(f"[StorageAgent] Milvus向量化完成 | task_id={task_id}")
        except Exception as e:
            logger.warning(f"[StorageAgent] Milvus向量化失败: {e}")
            result["status"] = "degraded"
            result["message"] += f" | Milvus失败: {e}"

        # 3. Neo4j 知识更新
        try:
            kb_agent = AgentRegistry.create("knowledge_update_agent")
            kb_result = kb_agent.update_after_execution(
                requirement_id=task_id if task_id else 0,
                task_id=task_id if task_id else 0,
                execution_id=None,
            )

            if isinstance(kb_result, dict):
                neo4j_info = kb_result.get("neo4j", {})
                result["neo4j_count"] = neo4j_info.get("nodes", 0)
            logger.info(f"[StorageAgent] Neo4j知识更新完成 | task_id={task_id}")
        except Exception as e:
            logger.warning(f"[StorageAgent] Neo4j知识更新失败: {e}")
            result["status"] = "degraded"
            result["message"] += f" | Neo4j失败: {e}"

        if result["status"] == "success":
            result["message"] = f"存储完成 | script_id={result['script_id']} | Milvus={result['milvus_count']} | Neo4j={result['neo4j_count']}"

        return result

    def execute(self, **kwargs) -> Dict[str, Any]:
        """管道统一入口"""
        return self.store(
            test_script=kwargs.get("test_script"),
            requirement=kwargs.get("requirement", ""),
            task_id=kwargs.get("task_id", 0),
            test_cases=kwargs.get("test_cases"),
        )
