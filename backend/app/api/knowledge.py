"""
Knowledge API - 统一知识服务接口

架构：
  入库流程：API → KnowledgePipeline → R2R（解析+切片）→ RAGPipeline（Embedding+三库写入）
  检索流程：API → ContextRouter → Milvus（主） / R2R（降级）

  R2R 职责：文档解析 + 切片（入库前预处理）
  项目职责：Embedding + MySQL + Milvus + Neo4j（入库后写入）

统一接口：
  POST /knowledge/upload       — 上传文件（R2R解析+切片 → 三库写入）
  POST /knowledge/upload/text   — 上传文本（R2R解析+切片 → 三库写入）
  POST /knowledge/search        — 语义搜索（ContextRouter → Milvus）
  POST /knowledge/retrieve      — 增强检索（ContextRouter → Milvus）
  GET  /knowledge/health         — 健康检查（含 R2R + Milvus 状态）
  GET  /knowledge/stats          — 知识库统计

所有接口需认证（require_auth）。
"""
import os
from typing import List, Optional
from fastapi import APIRouter, File, Form, UploadFile, HTTPException, Query, Depends
from pydantic import BaseModel as PydanticModel
from app.core.config import settings
from app.core.logger import log
from app.core.auth import require_auth
from app.models.user import User
from app.services.knowledge.client import get_knowledge_client
from app.services.knowledge.requirement_service import RequirementService
from app.services.knowledge.case_generate_service import CaseGenerateService
from app.services.knowledge.pipeline import get_knowledge_pipeline

router = APIRouter()


# ===== Request Models =====

class TextUploadRequest(PydanticModel):
    """文本上传请求"""
    text: str
    project_id: str = ""
    source_type: str = "text"
    title: str = ""


class SearchRequest(PydanticModel):
    """检索请求"""
    query: str
    project_id: str = ""
    top_k: int = 3
    filters: Optional[dict] = None


class CaseGenerateRequest(PydanticModel):
    """RAG增强用例生成请求"""
    project_id: str = ""
    title: str = ""
    source_type: str = "text"
    raw_text: str = ""
    url: str = ""
    knowledge_ids: Optional[List[int]] = None
    use_rag: bool = True
    case_types: List[str] = ["functional", "boundary", "error"]
    max_cases: int = 20


# ===== 统一接口：Upload =====

@router.post("/upload")
async def upload_file(
    project_id: str = Form(""),
    source_type: str = Form(""),
    title: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(require_auth),
):
    """
    上传文件到知识库（统一接口）

    架构变更：通过 KnowledgePipeline 双库同步
      1. R2R 上传（文档级知识库）
      2. RAGPipeline 入库（→Milvus + MySQL + Neo4j）

    流程：上传 → KnowledgePipeline → 解析 → Chunk → Embedding → Milvus + MySQL
    """
    from app.core.config import settings as cfg

    upload_dir = os.path.join(cfg.UPLOAD_DIR, "knowledge")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)

    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 通过 KnowledgePipeline 入库（R2R + RAGPipeline 双库同步）
    pipeline = get_knowledge_pipeline()
    result = await pipeline.ingest(
        file_path=file_path,
        source_type=source_type or "pdf",
        project_id=project_id,
        user_id=user.id,
        metadata={"title": title},
    )

    # 如果 KnowledgePipeline 完全失败，降级到本地 RequirementService
    if result.get("status") == "failed":
        log.warning(
            f"Knowledge upload | KnowledgePipeline 失败，降级到本地: "
            f"{result.get('errors', [])}"
        )
        result = await RequirementService.upload_file(
            file_path=file_path,
            project_id=project_id,
            source_type=source_type,
            title=title,
        )

    return result


@router.post("/upload/text")
async def upload_text(request: TextUploadRequest, user: User = Depends(require_auth)):
    """上传文本到知识库

    通过 KnowledgePipeline 入库：
      R2R（解析+切片）→ RAGPipeline（Embedding + MySQL + Milvus + Neo4j）
    """
    pipeline = get_knowledge_pipeline()
    result = await pipeline.ingest_text(
        content=request.text,
        source_type=request.source_type or "text",
        file_name=request.title or "manual_input",
        project_id=request.project_id,
        user_id=user.id,
    )

    # 降级到本地 RequirementService
    if result.get("status") == "failed":
        log.warning(f"Knowledge upload/text | KnowledgePipeline 失败，降级到本地")
        result = await RequirementService.upload_text(
            text=request.text,
            project_id=request.project_id,
            source_type=request.source_type,
            title=request.title,
        )

    return result


# ===== 统一接口：Search =====

@router.post("/search")
def search_knowledge(request: SearchRequest, user: User = Depends(require_auth)):
    """
    语义搜索（统一接口）

    通过 ContextRouter 路由到 Milvus 进行语义搜索。
    R2R 仅负责入库前预处理（解析+切片），不参与运行时检索。
    """
    from app.services.context_router import get_context_router, ContextType

    router = get_context_router()
    result = router.retrieve_sync(
        query=request.query,
        context_type=ContextType.DOCUMENT,
        top_k=request.top_k,
        filters=request.filters,
        project_id=request.project_id,
    )

    if not result or not result.get("results"):
        log.info(f"Knowledge search | 查询无结果 | query={request.query[:50]}")
        result = result or {"results": [], "total": 0}

    return result


# ===== 统一接口：Retrieve =====

@router.post("/retrieve")
def retrieve_knowledge(request: SearchRequest, user: User = Depends(require_auth)):
    """
    增强检索（RAG 模式，统一接口）

    通过 ContextRouter 路由到 Milvus 进行检索。
    R2R 仅负责入库前预处理（解析+切片），不参与运行时检索。
    """
    from app.services.context_router import get_context_router, ContextType

    router = get_context_router()
    result = router.retrieve_sync(
        query=request.query,
        context_type=ContextType.DOCUMENT,
        top_k=request.top_k,
        filters=request.filters,
        project_id=request.project_id,
    )

    if not result or not result.get("results"):
        log.info(f"Knowledge retrieve | 检索无结果 | query={request.query[:50]}")
        result = result or {"results": [], "total": 0}

    return result


# ===== 列表 & 状态 =====

@router.get("/list")
def list_knowledge(
    project_id: str = Query(""),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    user: User = Depends(require_auth),
):
    """列出知识文档"""
    return RequirementService.list_knowledge(
        project_id=project_id,
        skip=skip,
        limit=limit,
    )


@router.get("/{knowledge_id}/status")
def get_knowledge_status(knowledge_id: int, user: User = Depends(require_auth)):
    """查询知识索引状态"""
    result = RequirementService.get_knowledge_status(knowledge_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.delete("/{knowledge_id}")
def delete_knowledge(knowledge_id: int, user: User = Depends(require_auth)):
    """删除知识文档"""
    result = RequirementService.delete_knowledge(knowledge_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ===== 统计 =====

@router.get("/stats")
def knowledge_stats(user: User = Depends(require_auth)):
    """知识库统计（用于前端知识中心）"""
    try:
        result = RequirementService.list_knowledge(
            project_id="",
            skip=0,
            limit=100,
        )
        if isinstance(result, dict):
            items = result.get("items", [])
            total = result.get("total", len(items))
        elif isinstance(result, list):
            items = result
            total = len(result)
        else:
            items = []
            total = 0

        # 按来源类型与状态聚合统计
        status_counts = {}
        source_type_counts = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            status = item.get("status", "unknown")
            source_type = item.get("source_type", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1

        return {
            "total": total,
            "status_breakdown": status_counts,
            "source_type_breakdown": source_type_counts,
        }
    except Exception as e:
        log.error(f"Knowledge stats error: {e}")
        return {
            "total": 0,
            "status_breakdown": {},
            "source_type_breakdown": {},
            "error": str(e),
        }


# ===== 健康检查 =====

@router.get("/health")
def knowledge_health(user: User = Depends(require_auth)):
    """知识服务健康检查（含 R2R + Milvus + Neo4j 状态）"""
    # R2R 健康
    client = get_knowledge_client()
    r2r_result = client.health()

    # ContextRouter 健康检查（含 Milvus + Neo4j）
    try:
        from app.services.context_router import get_context_router
        router = get_context_router()
        ctx_health = router.health_check()
    except Exception as e:
        ctx_health = {"error": str(e)}

    return {
        "provider": settings.KNOWLEDGE_PROVIDER,
        "r2r": {
            "status": r2r_result.get("status", "unknown"),
            "base_url": settings.R2R_BASE_URL,
        },
        "milvus": ctx_health.get("milvus", {}),
        "neo4j": ctx_health.get("neo4j", {}),
        "context_router": {
            "status": "healthy",
            "request_count": ctx_health.get("request_count", 0),
        },
    }


# ===== Case Generation (RAG Enhanced) =====

@router.post("/cases/generate")
async def generate_cases(request: CaseGenerateRequest, user: User = Depends(require_auth)):
    """
    RAG 增强用例生成

    流程：解析需求 → RAG 检索 → 生成 → 保存
    """
    result = await CaseGenerateService.generate(
        project_id=request.project_id,
        title=request.title,
        source_type=request.source_type,
        raw_text=request.raw_text,
        url=request.url,
        knowledge_ids=request.knowledge_ids,
        use_rag=request.use_rag,
        case_types=request.case_types,
        max_cases=request.max_cases,
    )
    return result


@router.get("/cases/{generation_id}")
def get_generation(generation_id: int, user: User = Depends(require_auth)):
    """获取生成结果"""
    result = CaseGenerateService.get_generation(generation_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result
