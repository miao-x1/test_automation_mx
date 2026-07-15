"""
APIKnowledgeService - 接口知识库服务

支持从 Swagger / OpenAPI / Postman / JMeter / JSON 自动解析：
  接口 → 参数 → Header → Body → Response → 数据库

建立接口依赖关系，后续 API Agent 能查询相关接口。

核心能力：
  1. parse_and_store: 解析文件 → 结构化 → MySQL + Milvus + Neo4j
  2. get_api: 查询接口详情
  3. search_apis: 按关键词/方法/模块搜索接口
  4. get_dependencies: 获取接口依赖关系
  5. get_related_apis: 获取相关接口
"""
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from app.db.database import SessionLocal
from app.models.api_knowledge import APIKnowledge, APIDependency, APISourceType
from app.rag.service.tri_store_coordinator import get_tri_store_coordinator

logger = logging.getLogger(__name__)


class APIKnowledgeService:
    """接口知识库服务

    管理接口知识的完整生命周期：
      解析 → 结构化 → MySQL + Milvus + Neo4j
    """

    def __init__(self):
        self._tri_store = get_tri_store_coordinator()

    # ------------------------------------------------------------------
    # 解析 + 存储
    # ------------------------------------------------------------------

    async def parse_and_store(
        self,
        file_path: str,
        source_type: str = "",
        project_id: str = "default",
        user_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """解析接口文件并存储到三库

        支持：Swagger / OpenAPI / Postman / JMeter / JSON

        Returns:
            解析结果汇总
        """
        start_time = time.time()
        errors: List[str] = []
        file_name = os.path.basename(file_path)

        # 自动检测来源类型
        if not source_type:
            source_type = self._detect_source_type(file_path)

        logger.info(f"[APIKnowledge] 开始解析 file={file_name} type={source_type}")

        # 解析文件
        try:
            apis = await self._parse_file(file_path, source_type)
            logger.info(f"[APIKnowledge] 解析完成: {len(apis)} 个接口")
        except Exception as e:
            logger.error(f"[APIKnowledge] 解析失败: {e}")
            return {"status": "failed", "error": str(e), "file_name": file_name}

        if not apis:
            return {"status": "empty", "message": "未解析到接口", "file_name": file_name}

        # 存储到 MySQL
        api_ids: List[int] = []
        for api_data in apis:
            try:
                api_id = self._save_api(api_data, file_path, source_type, project_id, user_id)
                api_ids.append(api_id)
            except Exception as e:
                errors.append(f"接口 {api_data.get('path', '')} 保存失败: {e}")

        # 存储到 Milvus + Neo4j
        for i, api_data in enumerate(apis):
            api_id = api_ids[i] if i < len(api_ids) else None
            if api_id is None:
                continue
            try:
                await self._store_to_vector_graph(api_id, api_data)
            except Exception as e:
                errors.append(f"三库存储失败 {api_data.get('path', '')}: {e}")

        # 自动检测接口依赖关系
        try:
            dep_count = self._detect_dependencies(api_ids)
            logger.info(f"[APIKnowledge] 依赖关系检测: {dep_count} 条")
        except Exception as e:
            errors.append(f"依赖检测失败: {e}")

        duration = time.time() - start_time
        return {
            "status": "success" if not errors else "partial",
            "file_name": file_name,
            "source_type": source_type,
            "api_count": len(apis),
            "stored_count": len(api_ids),
            "dependency_count": len(api_ids),
            "duration": round(duration, 2),
            "errors": errors,
        }

    # ------------------------------------------------------------------
    # 文件解析
    # ------------------------------------------------------------------

    def _detect_source_type(self, file_path: str) -> str:
        """自动检测来源类型"""
        lower = file_path.lower()
        if lower.endswith((".postman_collection.json",)):
            return APISourceType.POSTMAN.value
        if ".jmeter" in lower or lower.endswith(".jmx"):
            return APISourceType.JMETER.value
        if lower.endswith((".yaml", ".yml")):
            return APISourceType.OPENAPI.value
        if lower.endswith(".json"):
            with open(file_path, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                    if "swagger" in data:
                        return APISourceType.SWAGGER.value
                    if "openapi" in data:
                        return APISourceType.OPENAPI.value
                    if "info" in data and "item" in data:
                        return APISourceType.POSTMAN.value
                except Exception:
                    pass
            return APISourceType.JSON.value
        return APISourceType.JSON.value

    async def _parse_file(self, file_path: str, source_type: str) -> List[Dict[str, Any]]:
        """根据来源类型解析文件"""
        if source_type in (APISourceType.SWAGGER.value, APISourceType.OPENAPI.value):
            return await self._parse_swagger(file_path)
        elif source_type == APISourceType.POSTMAN.value:
            return await self._parse_postman(file_path)
        elif source_type == APISourceType.JMETER.value:
            return await self._parse_jmeter(file_path)
        else:
            return await self._parse_json(file_path)

    async def _parse_swagger(self, file_path: str) -> List[Dict[str, Any]]:
        """解析 Swagger/OpenAPI 文件"""
        import yaml

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        try:
            spec = json.loads(content)
        except json.JSONDecodeError:
            spec = yaml.safe_load(content)

        apis: List[Dict[str, Any]] = []
        paths = spec.get("paths", {})
        info = spec.get("info", {})
        base_url = spec.get("servers", [{}])[0].get("url", "") if spec.get("servers") else ""
        global_tags = {t.get("name", ""): t for t in spec.get("tags", [])}

        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue

                api: Dict[str, Any] = {
                    "api_name": details.get("summary", f"{method.upper()} {path}"),
                    "method": method.upper(),
                    "path": path,
                    "full_url": f"{base_url}{path}" if base_url else path,
                    "summary": details.get("summary", ""),
                    "description": details.get("description", ""),
                    "tags": ",".join(details.get("tags", [])),
                    "module": details.get("tags", [""])[0] if details.get("tags") else "",
                    "version": info.get("version", ""),
                }

                # 参数
                params = details.get("parameters", [])
                api["parameters_json"] = json.dumps([
                    {
                        "name": p.get("name", ""),
                        "in": p.get("in", "query"),
                        "type": p.get("schema", {}).get("type", "string"),
                        "required": p.get("required", False),
                        "description": p.get("description", ""),
                        "default": p.get("schema", {}).get("default", ""),
                        "enum": p.get("schema", {}).get("enum", []),
                    }
                    for p in params
                ], ensure_ascii=False)

                # 请求头（从 parameters 中过滤）
                headers = [p for p in params if p.get("in") == "header"]
                api["headers_json"] = json.dumps([
                    {
                        "key": h.get("name", ""),
                        "value": h.get("schema", {}).get("default", ""),
                        "required": h.get("required", False),
                        "description": h.get("description", ""),
                    }
                    for h in headers
                ], ensure_ascii=False)

                # 请求体
                request_body = details.get("requestBody", {})
                if request_body:
                    content = request_body.get("content", {})
                    app_json = content.get("application/json", {})
                    api["request_body_json"] = json.dumps({
                        "content_type": "application/json",
                        "schema": app_json.get("schema", {}),
                        "example": app_json.get("example", {}),
                        "required": request_body.get("required", False),
                    }, ensure_ascii=False)

                # 响应
                responses = details.get("responses", {})
                resp_list = []
                for code, resp in responses.items():
                    resp_content = resp.get("content", {})
                    app_json_resp = resp_content.get("application/json", {})
                    resp_list.append({
                        "status_code": code,
                        "description": resp.get("description", ""),
                        "content_type": "application/json" if app_json_resp else "",
                        "schema": app_json_resp.get("schema", {}),
                        "example": app_json_resp.get("example", {}),
                    })
                api["responses_json"] = json.dumps(resp_list, ensure_ascii=False)

                # 成功响应示例
                for resp in resp_list:
                    if resp["status_code"].startswith("2") and resp.get("example"):
                        api["success_response_example"] = json.dumps(resp["example"], ensure_ascii=False)
                        break

                # 认证
                security = details.get("security", spec.get("security", []))
                if security:
                    api["auth_type"] = "bearer"
                    api["auth_details"] = json.dumps(security, ensure_ascii=False)
                else:
                    api["auth_type"] = "none"

                apis.append(api)

        return apis

    async def _parse_postman(self, file_path: str) -> List[Dict[str, Any]]:
        """解析 Postman Collection"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        apis: List[Dict[str, Any]] = []
        collection_name = data.get("info", {}).get("name", "")

        def process_item(item, parent_name=""):
            name = item.get("name", "")
            full_name = f"{parent_name} > {name}" if parent_name else name
            request = item.get("request", {})
            if not request:
                return

            method = request.get("method", "GET").upper()
            url = request.get("url", {})
            if isinstance(url, dict):
                url_str = "/" + "/".join(url.get("path", []))
                query_params = url.get("query", [])
            else:
                url_str = str(url)
                query_params = []

            description = request.get("description", "")
            headers = request.get("header", [])
            body = request.get("body", {})

            api: Dict[str, Any] = {
                "api_name": name,
                "method": method,
                "path": url_str,
                "full_url": url_str,
                "summary": description[:500] if description else "",
                "description": description,
                "tags": collection_name,
                "module": parent_name or collection_name,
            }

            # 参数
            params = []
            for qp in query_params:
                params.append({
                    "name": qp.get("key", ""),
                    "in": "query",
                    "type": "string",
                    "required": not qp.get("disabled", False),
                    "description": qp.get("description", ""),
                    "default": qp.get("value", ""),
                })
            api["parameters_json"] = json.dumps(params, ensure_ascii=False)

            # 请求头
            api["headers_json"] = json.dumps([
                {
                    "key": h.get("key", ""),
                    "value": h.get("value", ""),
                    "required": True,
                    "description": h.get("description", ""),
                }
                for h in headers
            ], ensure_ascii=False)

            # 请求体
            if body and body.get("raw"):
                api["request_body_json"] = json.dumps({
                    "content_type": body.get("mode", "raw"),
                    "schema": {},
                    "example": body.get("raw", "")[:2000],
                    "required": True,
                }, ensure_ascii=False)

            # 响应
            responses = item.get("response", [])
            resp_list = []
            for resp in responses:
                resp_body = resp.get("body", "")
                resp_list.append({
                    "status_code": str(resp.get("code", 200)),
                    "description": resp.get("status", ""),
                    "content_type": resp.get("_postman_previewlanguage", "json"),
                    "schema": {},
                    "example": resp_body[:2000] if resp_body else "",
                })
            api["responses_json"] = json.dumps(resp_list, ensure_ascii=False)

            # 认证
            auth = request.get("auth", {})
            if auth:
                api["auth_type"] = auth.get("type", "none")
            else:
                api["auth_type"] = "none"

            apis.append(api)

            # 递归处理子项
            for child in item.get("item", []):
                process_item(child, full_name)

        for item in data.get("item", []):
            process_item(item)

        return apis

    async def _parse_jmeter(self, file_path: str) -> List[Dict[str, Any]]:
        """解析 JMeter .jmx 文件"""
        import xml.etree.ElementTree as ET

        tree = ET.parse(file_path)
        root = tree.getroot()

        apis: List[Dict[str, Any]] = []

        for sampler in root.iter("HTTPSamplerProxy"):
            testname = sampler.get("testname", "")
            method = sampler.find(".//string[@name='HTTPSampler.method']")
            path = sampler.find(".//string[@name='HTTPSampler.path']")
            domain = sampler.find(".//string[@name='HTTPSampler.domain']")

            http_method = method.text if method is not None else "GET"
            url_path = path.text if path is not None else "/"
            domain_str = domain.text if domain is not None else ""

            # 提取参数
            params = []
            for arg in sampler.iter("HTTPArgument"):
                name_el = arg.find(".//string[@name='Argument.name']")
                value_el = arg.find(".//string[@name='Argument.value']")
                if name_el is not None:
                    params.append({
                        "name": name_el.text or "",
                        "in": "query",
                        "type": "string",
                        "required": True,
                    })

            api: Dict[str, Any] = {
                "api_name": testname,
                "method": http_method.upper(),
                "path": url_path,
                "full_url": f"http://{domain_str}{url_path}" if domain_str else url_path,
                "summary": f"JMeter: {testname}",
                "description": testname,
                "tags": "jmeter",
                "module": "jmeter",
                "parameters_json": json.dumps(params, ensure_ascii=False),
                "headers_json": "[]",
                "request_body_json": "",
                "responses_json": "[]",
                "auth_type": "none",
            }
            apis.append(api)

        return apis

    async def _parse_json(self, file_path: str) -> List[Dict[str, Any]]:
        """解析普通 JSON 文件（自定义格式）"""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        apis: List[Dict[str, Any]] = []

        # 支持 {apis: [...]} 或 [...] 格式
        api_list = data if isinstance(data, list) else data.get("apis", data.get("endpoints", []))

        for item in api_list:
            api: Dict[str, Any] = {
                "api_name": item.get("name", item.get("summary", "")),
                "method": item.get("method", "GET").upper(),
                "path": item.get("path", item.get("url", "/")),
                "full_url": item.get("url", item.get("path", "")),
                "summary": item.get("summary", ""),
                "description": item.get("description", ""),
                "tags": ",".join(item.get("tags", [])) if isinstance(item.get("tags"), list) else item.get("tags", ""),
                "module": item.get("module", ""),
                "parameters_json": json.dumps(item.get("parameters", []), ensure_ascii=False),
                "headers_json": json.dumps(item.get("headers", []), ensure_ascii=False),
                "request_body_json": json.dumps(item.get("request_body", {}), ensure_ascii=False) if item.get("request_body") else "",
                "responses_json": json.dumps(item.get("responses", []), ensure_ascii=False) if item.get("responses") else "[]",
                "auth_type": item.get("auth_type", "none"),
            }
            apis.append(api)

        return apis

    # ------------------------------------------------------------------
    # MySQL 存储
    # ------------------------------------------------------------------

    def _save_api(
        self,
        api_data: Dict[str, Any],
        source_file: str,
        source_type: str,
        project_id: str,
        user_id: Optional[int],
    ) -> int:
        """保存接口到 MySQL"""
        db = SessionLocal()
        try:
            # 检查是否已存在（method + path 唯一）
            existing = db.query(APIKnowledge).filter_by(
                method=api_data.get("method", "GET"),
                path=api_data.get("path", ""),
            ).first()

            if existing:
                # 更新
                for k, v in api_data.items():
                    if v is not None and hasattr(existing, k):
                        setattr(existing, k, v)
                existing.source_type = source_type
                existing.source_file = source_file
                db.commit()
                return existing.id

            api = APIKnowledge(
                api_name=api_data.get("api_name", ""),
                method=api_data.get("method", "GET"),
                path=api_data.get("path", ""),
                full_url=api_data.get("full_url", ""),
                source_type=source_type,
                source_file=source_file,
                summary=api_data.get("summary", ""),
                description=api_data.get("description", ""),
                tags=api_data.get("tags", ""),
                module=api_data.get("module", ""),
                parameters_json=api_data.get("parameters_json", "[]"),
                headers_json=api_data.get("headers_json", "[]"),
                request_body_json=api_data.get("request_body_json", ""),
                responses_json=api_data.get("responses_json", "[]"),
                success_response_example=api_data.get("success_response_example", ""),
                auth_type=api_data.get("auth_type", "none"),
                auth_details=api_data.get("auth_details", ""),
                version=api_data.get("version", ""),
                created_by=str(user_id) if user_id else None,
            )
            db.add(api)
            db.flush()
            api_id = api.id
            db.commit()
            return api_id
        except Exception as e:
            db.rollback()
            logger.error(f"[APIKnowledge] 保存失败: {e}")
            raise
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 三库存储
    # ------------------------------------------------------------------

    async def _store_to_vector_graph(self, api_id: int, api_data: Dict[str, Any]):
        """存储到 Milvus + Neo4j"""
        # 构建用于向量化的文本
        text_parts = [
            f"{api_data.get('method', '')} {api_data.get('path', '')}",
            api_data.get("summary", ""),
            api_data.get("description", ""),
        ]
        # 添加参数描述
        params = json.loads(api_data.get("parameters_json", "[]"))
        for p in params:
            text_parts.append(f"参数 {p.get('name', '')}: {p.get('description', '')}")

        # 添加响应描述
        responses = json.loads(api_data.get("responses_json", "[]"))
        for r in responses:
            text_parts.append(f"响应 {r.get('status_code', '')}: {r.get('description', '')}")

        text = " ".join(text_parts)

        # Milvus + Neo4j
        await self._tri_store.sync_write(
            entity_type="api",
            entity_id=str(api_id),
            text=text,
            metadata={
                "method": api_data.get("method", ""),
                "path": api_data.get("path", ""),
                "module": api_data.get("module", ""),
                "tags": api_data.get("tags", ""),
            },
            neo4j_label="API",
            neo4j_properties={
                "method": api_data.get("method", ""),
                "url": api_data.get("path", ""),
                "summary": api_data.get("summary", "")[:500],
            },
        )

    # ------------------------------------------------------------------
    # 依赖关系检测
    # ------------------------------------------------------------------

    def _detect_dependencies(self, api_ids: List[int]) -> int:
        """自动检测接口依赖关系

        规则：
          1. POST/PUT/DELETE 接口依赖同模块的 GET 接口（获取数据）
          2. 需要 auth 的接口依赖登录接口
          3. 路径有层级关系的接口（/users → /users/{id}）
        """
        if not api_ids:
            return 0

        db = SessionLocal()
        dep_count = 0
        try:
            apis = db.query(APIKnowledge).filter(APIKnowledge.id.in_(api_ids)).all()

            # 按模块分组
            by_module: Dict[str, List[APIKnowledge]] = {}
            login_apis: List[APIKnowledge] = []
            for api in apis:
                module = api.module or ""
                if module:
                    by_module.setdefault(module, []).append(api)
                # 检测登录接口
                tags_lower = (api.tags or "").lower()
                path_lower = (api.path or "").lower()
                if any(kw in path_lower or kw in tags_lower for kw in ["login", "auth", "token"]):
                    login_apis.append(api)

            for api in apis:
                # 1. 非GET接口依赖同模块的GET接口
                if api.method in ("POST", "PUT", "DELETE", "PATCH"):
                    module = api.module or ""
                    if module in by_module:
                        for dep_api in by_module[module]:
                            if dep_api.method == "GET" and dep_api.id != api.id:
                                self._create_dependency(db, api.id, dep_api.id, "data", "同模块GET接口提供数据")
                                dep_count += 1

                # 2. 需要auth的接口依赖登录接口
                if api.auth_type and api.auth_type != "none":
                    for login_api in login_apis:
                        if login_api.id != api.id:
                            self._create_dependency(db, api.id, login_api.id, "auth", "需要登录获取token")
                            dep_count += 1

                # 3. 路径层级关系（/users → /users/{id}）
                path = api.path or ""
                for other_api in apis:
                    other_path = other_api.path or ""
                    if (other_api.id != api.id and
                        other_path.startswith(path.rstrip("/") + "/") and
                        other_api.method == "GET"):
                        self._create_dependency(db, api.id, other_api.id, "sequence", "子路径接口")
                        dep_count += 1

            db.commit()
        except Exception as e:
            db.rollback()
            logger.error(f"[APIKnowledge] 依赖检测失败: {e}")
        finally:
            db.close()
        return dep_count

    def _create_dependency(self, db, api_id: int, depends_on_id: int, dep_type: str, desc: str):
        """创建依赖关系"""
        existing = db.query(APIDependency).filter_by(
            api_id=api_id, depends_on_api_id=depends_on_id
        ).first()
        if existing is None:
            dep = APIDependency(
                api_id=api_id,
                depends_on_api_id=depends_on_id,
                dependency_type=dep_type,
                description=desc,
            )
            db.add(dep)

    # ------------------------------------------------------------------
    # 查询接口
    # ------------------------------------------------------------------

    def get_api(self, api_id: int) -> Optional[Dict[str, Any]]:
        """获取接口详情"""
        db = SessionLocal()
        try:
            api = db.query(APIKnowledge).filter_by(id=api_id).first()
            if api is None:
                return None
            return self._api_to_dict(api, db)
        finally:
            db.close()

    def get_api_by_method_path(self, method: str, path: str) -> Optional[Dict[str, Any]]:
        """按 method+path 查询接口"""
        db = SessionLocal()
        try:
            api = db.query(APIKnowledge).filter_by(
                method=method.upper(), path=path
            ).first()
            if api is None:
                return None
            return self._api_to_dict(api, db)
        finally:
            db.close()

    def search_apis(
        self,
        keyword: str = "",
        method: str = "",
        module: str = "",
        tags: str = "",
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """搜索接口"""
        db = SessionLocal()
        try:
            q = db.query(APIKnowledge)
            if keyword:
                q = q.filter(
                    (APIKnowledge.api_name.contains(keyword)) |
                    (APIKnowledge.path.contains(keyword)) |
                    (APIKnowledge.summary.contains(keyword)) |
                    (APIKnowledge.description.contains(keyword))
                )
            if method:
                q = q.filter_by(method=method.upper())
            if module:
                q = q.filter_by(module=module)
            if tags:
                q = q.filter(APIKnowledge.tags.contains(tags))
            q = q.order_by(APIKnowledge.created_at.desc()).limit(limit)
            return [self._api_to_dict(api, db) for api in q.all()]
        finally:
            db.close()

    def get_dependencies(self, api_id: int) -> Dict[str, Any]:
        """获取接口的依赖关系

        Returns:
            {
              "depends_on": [...],    # 本接口依赖哪些接口
              "consumed_by": [...],   # 哪些接口依赖本接口
            }
        """
        db = SessionLocal()
        try:
            # 本接口依赖的接口
            deps = db.query(APIDependency).filter_by(api_id=api_id).all()
            depends_on = []
            for dep in deps:
                target = db.query(APIKnowledge).filter_by(id=dep.depends_on_api_id).first()
                if target:
                    depends_on.append({
                        "api_id": target.id,
                        "api_name": target.api_name,
                        "method": target.method,
                        "path": target.path,
                        "dependency_type": dep.dependency_type,
                        "description": dep.description,
                    })

            # 依赖本接口的接口
            consumers = db.query(APIDependency).filter_by(depends_on_api_id=api_id).all()
            consumed_by = []
            for c in consumers:
                source = db.query(APIKnowledge).filter_by(id=c.api_id).first()
                if source:
                    consumed_by.append({
                        "api_id": source.id,
                        "api_name": source.api_name,
                        "method": source.method,
                        "path": source.path,
                        "dependency_type": c.dependency_type,
                        "description": c.description,
                    })

            return {
                "depends_on": depends_on,
                "consumed_by": consumed_by,
            }
        finally:
            db.close()

    def get_related_apis(self, api_id: int, depth: int = 1) -> List[Dict[str, Any]]:
        """获取相关接口（通过依赖关系图遍历）

        API Agent 调用此方法获取相关接口链路。
        """
        db = SessionLocal()
        try:
            visited = {api_id}
            result: List[Dict[str, Any]] = []

            current_level = [api_id]
            for _ in range(depth):
                next_level: List[int] = []
                for aid in current_level:
                    deps = db.query(APIDependency).filter_by(api_id=aid).all()
                    for dep in deps:
                        if dep.depends_on_api_id not in visited:
                            visited.add(dep.depends_on_api_id)
                            api = db.query(APIKnowledge).filter_by(id=dep.depends_on_api_id).first()
                            if api:
                                result.append(self._api_to_dict(api, db))
                                next_level.append(dep.depends_on_api_id)

                    consumers = db.query(APIDependency).filter_by(depends_on_api_id=aid).all()
                    for c in consumers:
                        if c.api_id not in visited:
                            visited.add(c.api_id)
                            api = db.query(APIKnowledge).filter_by(id=c.api_id).first()
                            if api:
                                result.append(self._api_to_dict(api, db))
                                next_level.append(c.api_id)

                current_level = next_level

            return result
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 统计
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """获取统计"""
        db = SessionLocal()
        try:
            from sqlalchemy import func
            total = db.query(func.count(APIKnowledge.id)).scalar() or 0
            total_deps = db.query(func.count(APIDependency.id)).scalar() or 0

            by_method = {}
            rows = db.query(APIKnowledge.method, func.count(APIKnowledge.id)).group_by(APIKnowledge.method).all()
            for m, c in rows:
                by_method[m] = c

            by_source = {}
            rows = db.query(APIKnowledge.source_type, func.count(APIKnowledge.id)).group_by(APIKnowledge.source_type).all()
            for s, c in rows:
                by_source[s] = c

            by_module = {}
            rows = db.query(APIKnowledge.module, func.count(APIKnowledge.id)).filter(
                APIKnowledge.module.isnot(None)
            ).group_by(APIKnowledge.module).all()
            for m, c in rows:
                by_module[m or "unknown"] = c

            return {
                "total_apis": total,
                "total_dependencies": total_deps,
                "by_method": by_method,
                "by_source": by_source,
                "by_module": by_module,
            }
        finally:
            db.close()

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _api_to_dict(api: APIKnowledge, db=None) -> Dict[str, Any]:
        """将 ORM 对象转为字典"""
        result = {
            "id": api.id,
            "api_name": api.api_name,
            "method": api.method,
            "path": api.path,
            "full_url": api.full_url,
            "source_type": api.source_type,
            "summary": api.summary,
            "description": api.description,
            "tags": api.tags,
            "module": api.module,
            "auth_type": api.auth_type,
            "version": api.version,
            "is_deprecated": api.is_deprecated,
            "created_at": api.created_at.isoformat() if api.created_at else None,
        }
        # 解析 JSON 字段
        for field in ["parameters_json", "headers_json", "request_body_json",
                       "responses_json", "depends_on_json", "consumed_by_json",
                       "db_operations_json", "auth_details"]:
            val = getattr(api, field, None)
            field_name = field.replace("_json", "")
            if val:
                try:
                    result[field_name] = json.loads(val)
                except Exception:
                    result[field_name] = val
            else:
                result[field_name] = [] if field != "request_body_json" and field != "auth_details" else {}

        return result


# ===== 单例 =====
_service: Optional[APIKnowledgeService] = None


def get_api_knowledge_service() -> APIKnowledgeService:
    global _service
    if _service is None:
        _service = APIKnowledgeService()
    return _service
