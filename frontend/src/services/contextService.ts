/**
 * 三层上下文 API 服务
 *
 * 对接后端 /api/v1/context/* 端点
 */
import api from './request';

// ===== 类型定义 =====

export interface RouteRequest {
  task_id?: string;
  task_type?: string;
  requirement?: string;
  business_module?: string;
  keywords?: string[];
  page_names?: string[];
  api_names?: string[];
  execute?: boolean;
}

export interface RetrievalPlan {
  mysql: {
    tables: string[];
    filters: Record<string, any>;
    fields: string[];
    limit: number;
  };
  milvus: {
    queries: string[];
    collections: string[];
    entity_types: string[];
    top_k: number;
    score_threshold: number;
  };
  neo4j: {
    node_labels: string[];
    node_names: string[];
    relation_types: string[];
    depth: number;
    start_nodes: Array<{ label: string; name: string }>;
  };
  reason: string;
  task_type: string;
}

export interface ContextPreview {
  task_id: string;
  plan: RetrievalPlan;
  mysql_data: Record<string, any>;
  vector_results: Record<string, any>;
  graph_results: Record<string, any>;
  fused_context: Record<string, any>;
  sources: string[];
  summary: string;
  duration: number;
}

// ===== API 方法 =====

/** 预览路由计划 */
export async function previewRoute(request: RouteRequest): Promise<{ task_id: string; plan: RetrievalPlan; reason: string }> {
  const response = await api.post('/api/v1/context/route', request);
  return response.data;
}

/** 执行检索并返回融合上下文 */
export async function executeRetrieve(request: RouteRequest): Promise<ContextPreview> {
  const response = await api.post('/api/v1/context/retrieve', request);
  return response.data;
}

/** 查看任务使用的AI上下文 */
export async function getContextPreview(taskId: string): Promise<ContextPreview> {
  const response = await api.get(`/api/v1/context/preview/${taskId}`);
  return response.data;
}

/** 获取三层系统统计 */
export async function getContextStats(): Promise<Record<string, any>> {
  const response = await api.get('/api/v1/context/stats');
  return response.data;
}
