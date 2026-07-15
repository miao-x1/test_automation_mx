/**
 * 页面关联服务
 *
 * API:
 *   GET  /api/page-relation/task/{taskId}   — 获取任务的页面关联
 *   POST /api/page-relation/discover        — 自动发现关联页面
 *   POST /api/page-relation/                — 手动创建关联
 *   DELETE /api/page-relation/{id}          — 删除关联
 *   POST /api/page-relation/build-flow      — 构建完整流程
 *   GET  /api/page-relation/history         — 获取历史页面流程
 */
import request from './request';

export interface PageRelationItem {
  id: number;
  task_id: number;
  source_page: string;
  source_page_title: string | null;
  target_page: string;
  target_page_title: string | null;
  relation_type: string;
  confidence: number;
  trigger: string | null;
  trigger_locator: string | null;
  sort_order: number;
  metadata_json: any;
  created_at: string;
  updated_at: string;
}

export interface RelatedPage {
  page_id: string;
  title: string;
  url: string;
  confidence: number;
  actions?: string[];
  state_vars?: Record<string, any>;
  elements?: any[];
}

export interface PageTransition {
  from_page: string;
  to_page: string;
  trigger: string;
  trigger_locator: string;
  confidence: number;
}

export interface PageFlow {
  page_flow: Array<{
    page_id: string;
    title: string;
    url: string;
    order: number;
    actions: string[];
    state_vars: Record<string, any>;
    elements?: any[];
  }>;
  transitions: PageTransition[];
  entry_url: string;
  variables: Record<string, any>;
}

export interface HistoryFlow {
  task_id: number;
  task_name: string;
  page_count: number;
  page_names: string[];
  created_at: string;
}

/** 获取任务的页面关联 */
export async function getTaskRelations(taskId: number): Promise<PageRelationItem[]> {
  const res: any = await request.get(`/page-relation/task/${taskId}`);
  return res.data || [];
}

/** 自动发现关联页面 */
export async function discoverPages(params: {
  requirement: string;
  keywords?: string[];
  steps?: string[];
  target_url?: string;
}): Promise<{ pages: RelatedPage[]; relations: any[]; source: string }> {
  const res: any = await request.post('/page-relation/discover', params);
  return res.data || { pages: [], relations: [], source: 'keyword' };
}

/** 手动创建页面关联 */
export async function createRelation(data: {
  task_id: number;
  source_page: string;
  source_page_title?: string;
  target_page: string;
  target_page_title?: string;
  relation_type?: string;
  confidence?: number;
  trigger?: string;
  trigger_locator?: string;
  sort_order?: number;
}): Promise<PageRelationItem> {
  const res: any = await request.post('/page-relation/', data);
  return res.data;
}

/** 删除页面关联 */
export async function deleteRelation(id: number): Promise<void> {
  await request.delete(`/page-relation/${id}`);
}

/** 构建完整页面流程 */
export async function buildFlow(params: {
  requirement: string;
  task_id?: number;
  target_url?: string;
}): Promise<PageFlow> {
  const res: any = await request.post('/page-relation/build-flow', params);
  return res.data || { page_flow: [], transitions: [], entry_url: '', variables: {} };
}

/** 获取历史页面流程 */
export async function getHistoryFlows(limit?: number): Promise<HistoryFlow[]> {
  const res: any = await request.get('/page-relation/history', { params: { limit: limit || 10 } });
  return res.data || [];
}
