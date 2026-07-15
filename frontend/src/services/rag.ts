import request from './request';

// ============ RAG知识库 ============

export interface RAGCollection {
  name: string;
  row_count: number;
  type: string;
}

export interface RAGStats {
  collections: RAGCollection[];
  total_count: number;
  status: string;
}

export interface SearchResult {
  id: number;
  score: number;
  task_id: number;
  page_name: string;
  element_name: string;
  element_type: string;
  locator: string;
  description: string;
}

// 索引指定任务的元素
export function indexTask(taskId: number) {
  return request.post(`/rag/index/${taskId}`);
}

// 索引所有元素
export function indexAll() {
  return request.post('/rag/index/all');
}

// 增量索引全部集合（元素+用例+脚本）
export function indexIncremental() {
  return request.post('/rag/index/incremental');
}

// 索引历史测试用例
export function indexCases() {
  return request.post('/rag/index/cases');
}

// 索引历史脚本
export function indexScripts() {
  return request.post('/rag/index/scripts');
}

// 获取知识库统计
export function getRAGStats() {
  return request.get('/rag/stats');
}

// 清空指定集合
export function clearCollection(collectionName: string) {
  return request.post('/rag/clear', { confirm: true, collection_name: collectionName });
}

// 清空所有集合
export function clearAllCollections() {
  return request.post('/rag/clear_all');
}

// 查看集合内容
export function getCollectionData(collectionName: string, page: number = 1, pageSize: number = 20) {
  return request.get(`/rag/collection/${collectionName}?page=${page}&page_size=${pageSize}`);
}

// 重置Milvus连接
export function resetMilvus() {
  return request.post('/rag/reset');
}
