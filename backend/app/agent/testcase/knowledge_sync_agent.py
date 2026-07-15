"""
KnowledgeSyncAgent - 数据同步Agent

职责：
    MySQL业务数据 → 同步到 → Milvus + Neo4j

同步流程：
    1. 监听MySQL数据变更（新增测试用例/脚本/页面元素等）
    2. 生成embedding写入Milvus
    3. 抽取实体关系写入Neo4j

同步场景：
    - 新增测试用例 → Milvus(test_case_vector) + Neo4j(TestCase节点)
    - 新增脚本 → Milvus(script_vector) + Neo4j(Script节点)
    - 新增页面元素 → Milvus(ui_element_vector) + Neo4j(Page/Element节点)

使用已有的TriStoreCoordinator实现三库同步写入。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from app.agent.core.base_agent import BaseAgent as NewBaseAgent
from app.agent.core.types import AgentCapability

logger = logging.getLogger(__name__)


class KnowledgeSyncAgent(NewBaseAgent):
    """数据同步Agent

    将MySQL业务数据同步到Milvus向量库和Neo4j图数据库。
    使用已有的TriStoreCoordinator实现统一三库写入。

    同步类型：
        - test_case: 测试用例同步
        - script: 脚本同步
        - page: 页面元素同步
        - requirement: 需求同步
    """

    agent_name = "knowledge_sync_agent"
    display_name = "数据同步Agent"
    description = "MySQL业务数据同步到Milvus+Neo4j，实现三库数据一致性"
    capabilities = [AgentCapability.KNOWLEDGE_UPDATE]

    # 同步类型 → 实体类型映射
    SYNC_TYPE_MAP = {
        "test_case": "case",
        "script": "script",
        "page": "page",
        "requirement": "requirement",
        "api": "api",
    }

    def __init__(self, config=None, runtime=None, session_id=None, **kwargs):
        super().__init__(config=config, runtime=runtime, session_id=session_id, **kwargs)

    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        执行数据同步

        Args:
            sync_type: 同步类型（test_case/script/page/requirement/api）
            entity_id: 实体ID
            entity_data: 实体数据（dict）
            text: 用于生成embedding的文本
            tags: 标签列表
            neo4j_properties: Neo4j节点额外属性
            neo4j_relations: Neo4j关系列表

        Returns:
            {
                status: "success",
                synced: {milvus: bool, neo4j: bool},
                errors: []
            }
        """
        sync_type = kwargs.get("sync_type", "")
        entity_id = kwargs.get("entity_id", "")
        entity_data = kwargs.get("entity_data", {})
        text = kwargs.get("text", "")
        tags = kwargs.get("tags", [])
        neo4j_properties = kwargs.get("neo4j_properties", {})
        neo4j_relations = kwargs.get("neo4j_relations", [])

        if not sync_type or not entity_id:
            return {
                "status": "error",
                "error": "缺少sync_type或entity_id",
            }

        self.logger.info(f"[数据同步] 开始 | 类型: {sync_type} | ID: {entity_id}")

        errors = []
        synced = {"milvus": False, "neo4j": False}

        # 获取TriStoreCoordinator
        try:
            from app.rag.service.tri_store_coordinator import get_tri_store_coordinator
            coordinator = get_tri_store_coordinator()

            entity_type = self.SYNC_TYPE_MAP.get(sync_type, sync_type)

            # 构建metadata
            metadata = {
                "source_type": sync_type,
                "entity_id": str(entity_id),
                "sync_time": kwargs.get("sync_time", ""),
            }
            metadata.update(entity_data)

            # 执行三库同步写入
            result = await coordinator.sync_write(
                entity_type=entity_type,
                entity_id=str(entity_id),
                text=text or json.dumps(entity_data, ensure_ascii=False),
                metadata=metadata,
                embedding=None,  # TriStoreCoordinator会自动生成
                tags=tags,
                neo4j_label=None,  # 使用默认映射
                neo4j_properties=neo4j_properties or entity_data,
            )

            if result.get("milvus", {}).get("success"):
                synced["milvus"] = True
            else:
                errors.append(f"Milvus同步失败: {result.get('milvus', {}).get('error', '')}")

            if result.get("neo4j", {}).get("success"):
                synced["neo4j"] = True
            else:
                errors.append(f"Neo4j同步失败: {result.get('neo4j', {}).get('error', '')}")

            # 写入关系
            if neo4j_relations:
                for rel in neo4j_relations:
                    try:
                        await coordinator.sync_write_relation(
                            from_type=rel.get("from_type", entity_type),
                            from_id=rel.get("from_id", str(entity_id)),
                            rel_type=rel.get("rel_type", "RELATED_TO"),
                            to_type=rel.get("to_type", ""),
                            to_id=rel.get("to_id", ""),
                            properties=rel.get("properties", {}),
                        )
                    except Exception as e:
                        errors.append(f"关系写入失败: {e}")

        except Exception as e:
            self.logger.error(f"[数据同步] 失败: {e}", exc_info=True)
            errors.append(str(e))

        success = all(synced.values()) if synced else False

        self.logger.info(
            f"[数据同步] 完成 | 类型: {sync_type} | "
            f"Milvus: {'✓' if synced['milvus'] else '✗'} | "
            f"Neo4j: {'✓' if synced['neo4j'] else '✗'} | "
            f"错误数: {len(errors)}"
        )

        return {
            "status": "success" if success else "partial",
            "synced": synced,
            "errors": errors,
            "entity_id": entity_id,
            "sync_type": sync_type,
        }

    async def sync_test_case(self, case_id: int, case_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步测试用例到Milvus+Neo4j"""
        text = f"{case_data.get('case_name', '')} {case_data.get('precondition', '')} {case_data.get('expected_result', '')}"
        return await self.execute(
            sync_type="test_case",
            entity_id=case_id,
            entity_data=case_data,
            text=text,
            tags=[case_data.get("priority", ""), case_data.get("type", "")],
            neo4j_properties={
                "name": case_data.get("case_name", ""),
                "priority": case_data.get("priority", ""),
                "type": case_data.get("type", ""),
                "status": case_data.get("status", "draft"),
            },
        )

    async def sync_script(self, script_id: int, script_data: Dict[str, Any]) -> Dict[str, Any]:
        """同步脚本到Milvus+Neo4j"""
        text = f"{script_data.get('name', '')} {script_data.get('description', '')} {script_data.get('content', '')[:500]}"
        return await self.execute(
            sync_type="script",
            entity_id=script_id,
            entity_data=script_data,
            text=text,
            tags=[script_data.get("language", ""), script_data.get("type", "")],
            neo4j_properties={
                "name": script_data.get("name", ""),
                "language": script_data.get("language", "python"),
                "type": script_data.get("type", "playwright"),
            },
        )

    async def sync_page(self, page_id: str, page_data: Dict[str, Any], elements: List[Dict] = None) -> Dict[str, Any]:
        """同步页面及元素到Milvus+Neo4j"""
        text = f"{page_data.get('page_name', '')} {page_data.get('page_url', '')} {page_data.get('description', '')}"

        relations = []
        if elements:
            for elem in elements:
                relations.append({
                    "from_type": "page",
                    "from_id": page_id,
                    "rel_type": "HAS_ELEMENT",
                    "to_type": "element",
                    "to_id": str(elem.get("id", "")),
                    "properties": {"element_type": elem.get("element_type", "")},
                })

        return await self.execute(
            sync_type="page",
            entity_id=page_id,
            entity_data=page_data,
            text=text,
            tags=[page_data.get("module", "")],
            neo4j_properties={
                "name": page_data.get("page_name", ""),
                "url": page_data.get("page_url", ""),
            },
            neo4j_relations=relations,
        )
