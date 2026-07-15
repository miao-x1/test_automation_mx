/**
 * 用例中心 API 服务
 */
import request from './request';

export interface CaseTask {
  id: number;
  title: string;
  source_type: string;
  status: string;
  case_count: number;
  error_message: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseTaskDetail extends CaseTask {
  source_file: string | null;
  source_url: string | null;
  raw_input: string | null;
  requirement_context: string | null;
  case_set: string | null;
  version: number;
}

export interface CaseContent {
  id: number;
  case_task_id: number;
  title: string;
  case_type: string;
  precondition: string;
  steps: string;
  expected: string;
  priority: string;
  tags: string;
  version: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CaseExport {
  id: number;
  case_task_id: number;
  export_type: string;
  file_path: string | null;
  status: string;
  case_count?: number;
  config: string | null;
  error_message: string | null;
  created_at: string | null;
}

export interface MindmapData {
  name: string;
  children: MindmapNode[];
}

export interface MindmapNode {
  name: string;
  children?: MindmapNode[];
  priority?: string;
  case_type?: string;
}

// 用例生成（SSE）- 使用fetch手动解析，不使用EventSource
export function generateCasesSSE(_params: {
  title?: string;
  source_type: string;
  raw_text?: string;
  url?: string;
  case_types?: string[];
  max_cases?: number;
  file?: File;
}): null {
  return null;
}

export async function generateCases(params: {
  title?: string;
  source_type: string;
  raw_text?: string;
  url?: string;
  case_types?: string[];
  max_cases?: number;
}): Promise<{ task_id: number; status: string; message: string }> {
  return request.post('/case/generate/sync', params);
}

// 获取任务列表
export async function listCaseTasks(params?: {
  skip?: number;
  limit?: number;
  status?: string;
  source_type?: string;
}): Promise<{ items: CaseTask[]; total: number }> {
  return request.get('/case/tasks', { params });
}

// 获取任务详情
export async function getCaseTask(taskId: number): Promise<CaseTaskDetail> {
  return request.get(`/case/tasks/${taskId}`);
}

// 删除任务
export async function deleteCaseTask(taskId: number): Promise<void> {
  return request.delete(`/case/tasks/${taskId}`);
}

// 获取用例列表
export async function listCases(params: {
  task_id: number;
  skip?: number;
  limit?: number;
  case_type?: string;
  priority?: string;
}): Promise<{ items: CaseContent[]; total: number }> {
  return request.get(`/case/tasks/${params.task_id}/cases`, {
    params: { skip: params.skip, limit: params.limit, case_type: params.case_type, priority: params.priority },
  });
}

// 更新用例
export async function updateCase(caseId: number, data: Partial<CaseContent>): Promise<CaseContent> {
  return request.put(`/case/cases/${caseId}`, data);
}

// 删除用例
export async function deleteCase(caseId: number): Promise<void> {
  return request.delete(`/case/cases/${caseId}`);
}

// 导出用例
export async function exportCases(taskId: number, params: {
  export_type: string;
  case_ids?: number[];
}): Promise<CaseExport> {
  return request.post(`/case/tasks/${taskId}/export`, params);
}

// 获取导出记录
export async function getExport(exportId: number): Promise<CaseExport> {
  return request.get(`/case/exports/${exportId}`);
}

// 获取思维导图
export async function getMindmap(taskId: number): Promise<{ id: number; task_id: number; mindmap_data: MindmapData; format: string }> {
  return request.get(`/case/tasks/${taskId}/mindmap`);
}

// 生成思维导图
export async function generateMindmap(taskId: number): Promise<{ task_id: number; mindmap_data: MindmapData; message: string }> {
  return request.post(`/case/tasks/${taskId}/mindmap`);
}
