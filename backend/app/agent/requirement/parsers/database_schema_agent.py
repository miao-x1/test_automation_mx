"""DatabaseSchemaAgent - 数据库Schema解析Agent

将SQL DDL语句解析为统一的RequirementContext。
使用正则提取表结构和字段，LLM分析生成测试要点。
"""
import json
import logging
import re
from typing import Any, Dict, List

from autogen_core import message_handler, MessageContext, default_subscription

from app.runtime.base_agent import BaseRoutedAgent
from app.runtime.messages import AgentRequest, AgentResponse
from app.agent.requirement.requirement_context import (
    RequirementContext, PageInfo, ElementInfo, BusinessFlow, TestPoint, Constraint,
)
from app.core.logger import log

logger = logging.getLogger(__name__)


@default_subscription
class DatabaseSchemaAgent(BaseRoutedAgent):
    """数据库Schema解析Agent - 将SQL DDL解析为RequirementContext"""

    def __init__(self) -> None:
        super().__init__(
            description="数据库Schema解析Agent，提取表结构和字段约束生成测试要点",
            display_name="DatabaseSchemaAgent",
            capabilities=["schema_parse", "ddl_parse", "requirement_parse"],
        )

    async def execute(self, payload: Dict[str, Any], ctx: MessageContext) -> Dict[str, Any]:
        """解析数据库Schema"""
        schema_content = payload.get("schema_content", "")
        file_path = payload.get("file_path", "")
        requirement = payload.get("requirement", "")
        task_id = payload.get("task_id", "")
        session_key = payload.get("session_key", "default")

        log.info(f"[DatabaseSchemaAgent] 开始解析Schema: file={file_path or 'inline'}")

        # 若未提供内容但有文件路径，尝试从文件读取
        if not schema_content and file_path:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    schema_content = f.read()
            except Exception as e:
                log.error(f"[DatabaseSchemaAgent] 读取文件失败: {e}")
                return {"status": "error", "error": f"读取Schema文件失败: {e}"}

        if not schema_content:
            return {"status": "error", "error": "未提供Schema内容(schema_content)或文件路径(file_path)"}

        # Step 1: 解析SQL DDL提取表结构
        tables: List[Dict[str, Any]] = []
        try:
            tables = self._parse_ddl(schema_content)
            log.info(f"[DatabaseSchemaAgent] 提取表结构: {len(tables)} 张表")
        except Exception as e:
            log.error(f"[DatabaseSchemaAgent] DDL解析失败: {e}")
            tables = []

        # Step 2: LLM分析生成测试要点
        schema_text = json.dumps(tables, ensure_ascii=False, default=str)
        if len(schema_text) > 8000:
            schema_text = schema_text[:8000]

        system_prompt = (
            "你是数据库测试需求分析专家。请分析以下数据库表结构，生成测试相关信息。\n"
            "重点关注：字段约束（非空、唯一、主键）、外键关系、字段类型边界值、\n"
            "数据完整性校验、级联操作、索引性能等测试场景。\n"
            "返回JSON格式，包含以下字段：\n"
            '{"pages": [{"url":"","title":"表名/模块名","page_type":"dashboard","description":"表描述","elements":[]}],\n'
            '"elements": [{"name":"字段名","element_type":"input","locator":"","text":"","action":"input","required":false}],\n'
            '{"business_flow": [{"flow_name":"流程名","steps":[{"action":"insert/update/delete/select","target":"表名","description":""}],"preconditions":[],"postconditions":[]}],\n'
            '"test_points": [{"name":"测试点名","description":"描述","category":"functional/boundary/error/security","priority":"high/medium/low","test_data":{}}],\n'
            '"constraints": [{"type":"business/technical/environmental","description":"约束描述","source":"schema"}],\n'
            '"summary": "整体摘要","intent": "测试意图"}\n'
            "只返回JSON，不要其他内容。"
        )

        user_prompt = f"数据库Schema:\n{schema_text}"
        if requirement:
            user_prompt = f"附加需求: {requirement}\n\n{user_prompt}"

        try:
            llm_response = await self.call_llm(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=0.3,
                max_tokens=4096,
                task_id=task_id,
                step="schema_llm_analyze",
                session_key=session_key,
            )
            parsed = self._parse_llm_json(llm_response)
        except Exception as e:
            log.error(f"[DatabaseSchemaAgent] LLM分析失败: {e}")
            parsed = {
                "summary": f"数据库Schema: {len(tables)} 张表",
                "intent": "schema_test",
            }

        # Step 3: 构建RequirementContext
        source_files = [file_path] if file_path else []
        context = RequirementContext(
            task_id=task_id,
            session_key=session_key,
            source_types=["schema"],
            source_files=source_files,
            raw_requirement=schema_content[:4000],
            summary=parsed.get("summary", f"数据库Schema: {len(tables)} 张表"),
            intent=parsed.get("intent", "schema_test"),
            metadata={
                "table_count": len(tables),
                "tables": tables,
            },
        )

        # 填充pages（每个表作为一个页面信息）
        for p in parsed.get("pages", []):
            context.pages.append(PageInfo(
                url=p.get("url", ""),
                title=p.get("title", ""),
                page_type=p.get("page_type", ""),
                description=p.get("description", ""),
                elements=p.get("elements", []),
            ))

        # 填充elements
        for e in parsed.get("elements", []):
            context.elements.append(ElementInfo(
                name=e.get("name", ""),
                element_type=e.get("element_type", ""),
                locator=e.get("locator", ""),
                text=e.get("text", ""),
                action=e.get("action", ""),
                required=e.get("required", False),
            ))

        # 填充business_flow
        for f in parsed.get("business_flow", []):
            context.business_flow.append(BusinessFlow(
                flow_name=f.get("flow_name", ""),
                steps=f.get("steps", []),
                preconditions=f.get("preconditions", []),
                postconditions=f.get("postconditions", []),
            ))

        # 填充test_points
        for tp in parsed.get("test_points", []):
            context.test_points.append(TestPoint(
                name=tp.get("name", ""),
                description=tp.get("description", ""),
                category=tp.get("category", "functional"),
                priority=tp.get("priority", "medium"),
                test_data=tp.get("test_data", {}),
            ))

        # 填充constraints
        for c in parsed.get("constraints", []):
            context.constraints.append(Constraint(
                type=c.get("type", "business"),
                description=c.get("description", ""),
                source="schema",
            ))

        log.info(
            f"[DatabaseSchemaAgent] 解析完成: "
            f"{len(context.test_points)} test_points, {len(context.business_flow)} flows, "
            f"{len(context.constraints)} constraints"
        )
        return {"status": "success", "context": context.to_dict()}

    def _parse_ddl(self, schema_content: str) -> List[Dict[str, Any]]:
        """解析SQL DDL语句，提取表结构和字段"""
        tables: List[Dict[str, Any]] = []

        # 提取 CREATE TABLE 语句
        table_matches = re.findall(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[]?(\w+)[`"\]]?\s*\((.*?)\)',
            schema_content,
            re.IGNORECASE | re.DOTALL,
        )

        for table_name, columns_sql in table_matches:
            table_info: Dict[str, Any] = {
                "table_name": table_name,
                "columns": [],
                "primary_key": "",
                "foreign_keys": [],
                "indexes": [],
            }

            column_lines = columns_sql.strip().split("\n")
            for line in column_lines:
                line = line.strip().rstrip(",")
                if not line:
                    continue
                # 跳过约束定义行
                if line.upper().startswith(
                    ("PRIMARY", "FOREIGN", "UNIQUE", "KEY", "CONSTRAINT", "INDEX", "CHECK")
                ):
                    # 提取主键
                    pk_match = re.match(
                        r'PRIMARY\s+KEY\s*\(([^)]+)\)', line, re.IGNORECASE
                    )
                    if pk_match:
                        table_info["primary_key"] = pk_match.group(1).strip().strip('`"[]')
                    # 提取外键
                    fk_match = re.match(
                        r'FOREIGN\s+KEY\s*\(([^)]+)\)\s*REFERENCES\s+[`"\[]?(\w+)[`"\]]?\s*\(([^)]+)\)',
                        line, re.IGNORECASE,
                    )
                    if fk_match:
                        table_info["foreign_keys"].append({
                            "column": fk_match.group(1).strip().strip('`"[]'),
                            "ref_table": fk_match.group(2),
                            "ref_column": fk_match.group(3).strip().strip('`"[]'),
                        })
                    continue

                parts = line.split()
                if not parts:
                    continue
                col_name = parts[0].strip('`"[]')
                col_type = parts[1] if len(parts) > 1 else ""
                # 检测 NOT NULL / DEFAULT / UNIQUE 等
                col_upper = line.upper()
                is_required = "NOT NULL" in col_upper
                is_unique = "UNIQUE" in col_upper
                default_match = re.search(r'DEFAULT\s+(\S+)', col_upper)
                default_val = default_match.group(1) if default_match else None

                column_info = {
                    "name": col_name,
                    "type": col_type,
                    "required": is_required,
                    "unique": is_unique,
                    "default": default_val,
                    "raw": line,
                }
                table_info["columns"].append(column_info)

            # 若该表没有显式 PRIMARY KEY，尝试从字段定义中识别
            if not table_info["primary_key"]:
                for col in table_info["columns"]:
                    if "PRIMARY KEY" in col["raw"].upper():
                        table_info["primary_key"] = col["name"]
                        break

            tables.append(table_info)

        return tables

    def _parse_llm_json(self, raw: str) -> dict:
        """解析LLM返回的JSON"""
        if isinstance(raw, dict):
            return raw
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1]) if len(lines) > 2 else raw
        try:
            return json.loads(raw)
        except Exception:
            return {"summary": str(raw)[:500]}
