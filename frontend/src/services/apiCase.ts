/**
 * API 测试用例管理 & 目录管理
 */
import request from './request';

// ========== 类型定义 ==========

export interface Step {
  action: string;
  url: string;
  headers?: Record<string, string>;
  body?: Record<string, unknown>;
  params?: Record<string, string>;
  extract?: { key: string; path: string }[];
  timeout?: number;
  continue_on_fail?: boolean;
}

export interface Assertion {
  type: string;
  path: string;
  expected?: unknown;
  pattern?: string;
}

export interface Extract {
  key: string;
  path: string;
}

export interface ApiCase {
  id: number;
  case_id?: string;
  title: string;
  description?: string;
  folder_id?: number;
  priority: string;
  status: string;
  tags?: string;
  precondition?: string;
  steps: Step[];
  assertions: Assertion[];
  extracts: Extract[];
  env_override?: Record<string, unknown>;
  version: number;
  last_run_status?: string;
  run_count: number;
  created_at?: string;
  updated_at?: string;
}

export interface ApiCaseFolder {
  id: number;
  name: string;
  description?: string;
  sort_order: number;
  case_count: number;
  children?: ApiCaseFolder[];
}

// ========== 用例管理 ==========

export async function saveCase(data: {
  id?: number;
  title: string;
  case_id?: string;
  description?: string;
  folder_id?: number;
  priority?: string;
  status?: string;
  tags?: string;
  precondition?: string;
  steps: Step[];
  assertions: Assertion[];
  extracts?: Extract[];
  env_override?: Record<string, unknown>;
}): Promise<{ id: number; case_id?: string; title: string; status: string; version: number }> {
  return request.post('/api-test/cases/save', data);
}

export async function listCases(params?: {
  folder_id?: number;
  priority?: string;
  status?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<{
  total: number;
  page: number;
  page_size: number;
  items: ApiCase[];
}> {
  return request.get('/api-test/cases/list', { params });
}

export async function getCase(caseId: number): Promise<ApiCase> {
  return request.get(`/api-test/cases/${caseId}`);
}

export async function deleteCase(caseId: number): Promise<void> {
  return request.delete(`/api-test/cases/${caseId}`);
}

export async function copyCase(caseId: number): Promise<{ id: number; case_id?: string; title: string }> {
  return request.post(`/api-test/cases/copy/${caseId}`);
}

export async function importFromAI(taskId: number): Promise<{
  id: number;
  title: string;
  steps_count: number;
  assertions_count: number;
}> {
  return request.post(`/api-test/import/ai/${taskId}`);
}

export async function importFromSwagger(data: {
  content: string;
  base_url?: string;
}): Promise<{
  imported: number;
  cases: { id: number; title: string }[];
}> {
  return request.post('/api-test/import/swagger', data);
}

// ========== 目录管理 ==========

export async function saveFolder(data: {
  id?: number;
  name: string;
  parent_id?: number;
  description?: string;
  sort_order?: number;
}): Promise<{ id: number; name: string; parent_id?: number }> {
  return request.post('/api-test/folders/save', data);
}

export async function getFolderTree(): Promise<ApiCaseFolder[]> {
  const res: any = await request.get('/api-test/folders/tree');
  return res?.data || res || [];
}

export async function deleteFolder(folderId: number): Promise<void> {
  return request.delete(`/api-test/folders/${folderId}`);
}
