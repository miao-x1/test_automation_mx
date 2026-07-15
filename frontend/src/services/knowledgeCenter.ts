/**
 * Knowledge Center API 服务
 *
 * 知识库管理接口：
 *  - 知识导入（上传文件 → KnowledgePipeline → R2R + Milvus + MySQL）
 *  - 集合管理
 *  - 文档管理
 *  - Chunk查看
 *  - Embedding状态
 *  - Graph查看
 *  - 重建操作
 *  - 搜索测试（全文/语义/混合）
 *  - AI检索配置（ContextRouter 状态）
 */
import request from './request';

// ===== 知识导入 =====

export function uploadKnowledge(file: File, params: {
  project_id?: string;
  source_type?: string;
  title?: string;
}) {
  const formData = new FormData();
  formData.append('file', file);
  if (params.project_id) formData.append('project_id', params.project_id);
  if (params.source_type) formData.append('source_type', params.source_type);
  if (params.title) formData.append('title', params.title);
  return request.post('/knowledge/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  });
}

export function getKnowledgeHealth() {
  return request.get('/knowledge/health');
}

// ===== AI检索配置（ContextRouter） =====

export function getContextRouterHealth() {
  return request.get('/context/health');
}

export function getContextTypes() {
  return request.get('/context/types');
}

export function retrieveContext(data: {
  query: string;
  context_type: string;
  top_k?: number;
  filters?: any;
  project_id?: string;
}) {
  return request.post('/context/retrieve', data);
}

// ===== 总览统计 =====

export function getCenterStats() {
  return request.get('/knowledge-center/stats');
}

// ===== 集合管理 =====

export function listCollections() {
  return request.get('/knowledge-center/collections');
}

export function getCollectionDetail(entityType: string) {
  return request.get(`/knowledge-center/collections/${entityType}`);
}

export function clearCollection(entityType: string) {
  return request.delete(`/knowledge-center/collections/${entityType}`);
}

// ===== 文档管理 =====

export function listDocuments(params?: {
  project_id?: string;
  source_type?: string;
  status?: string;
  keyword?: string;
  limit?: number;
  offset?: number;
}) {
  return request.get('/knowledge-center/documents', { params });
}

export function getDocumentDetail(sourceId: number) {
  return request.get(`/knowledge-center/documents/${sourceId}`);
}

export function deleteDocument(sourceId: number) {
  return request.delete(`/knowledge-center/documents/${sourceId}`);
}

// ===== Chunk 查看 =====

export function listChunks(sourceId: number, params?: { chunk_type?: string; limit?: number }) {
  return request.get(`/knowledge-center/chunks/${sourceId}`, { params });
}

export function getChunkDetail(chunkId: number) {
  return request.get(`/knowledge-center/chunks/detail/${chunkId}`);
}

// ===== Embedding 状态 =====

export function getEmbeddingStatus(sourceId: number) {
  return request.get(`/knowledge-center/embedding-status/${sourceId}`);
}

// ===== Graph 查看 =====

export function getGraphOverview() {
  return request.get('/knowledge-center/graph/overview');
}

export function getGraphNodes(params?: { label?: string; limit?: number }) {
  return request.get('/knowledge-center/graph/nodes', { params });
}

export function getGraphRelations(params: { label: string; entity_id: string; depth?: number }) {
  return request.get('/knowledge-center/graph/relations', { params });
}

// ===== 重建操作 =====

export function rebuildEmbedding(sourceId: number) {
  return request.post(`/knowledge-center/rebuild-embedding/${sourceId}`);
}

export function rechunkDocument(sourceId: number, chunkSize: number = 500) {
  return request.post(`/knowledge-center/rechunk/${sourceId}`, null, {
    params: { chunk_size: chunkSize },
  });
}

export function reindexDocument(sourceId: number, chunkSize: number = 500) {
  return request.post(`/knowledge-center/reindex/${sourceId}`, null, {
    params: { chunk_size: chunkSize },
  });
}

// ===== 搜索测试 =====

export function fulltextSearch(data: { keyword: string; source_type?: string; limit?: number }) {
  const formData = new FormData();
  formData.append('keyword', data.keyword);
  if (data.source_type) formData.append('source_type', data.source_type);
  if (data.limit) formData.append('limit', String(data.limit));
  return request.post('/knowledge-center/search/fulltext', formData);
}

export function semanticSearch(data: { query: string; entity_types?: string; top_k?: number }) {
  const formData = new FormData();
  formData.append('query', data.query);
  if (data.entity_types) formData.append('entity_types', data.entity_types);
  if (data.top_k) formData.append('top_k', String(data.top_k));
  return request.post('/knowledge-center/search/semantic', formData);
}

export function hybridSearch(data: { keyword: string; query: string; entity_types?: string[]; top_k?: number }) {
  return request.post('/knowledge-center/search/hybrid', {
    keyword: data.keyword,
    query: data.query,
    entity_types: data.entity_types || ['chunk'],
    top_k: data.top_k || 10,
  });
}
