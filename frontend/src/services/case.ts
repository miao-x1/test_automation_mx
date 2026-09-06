/**
 * 用例中心 API 服务
 */
import request from './request';
import { browserApiUrl } from '../utils/apiUrl';
import { assertUploadAllowed, formatUploadError } from '../utils/uploadGuard';

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

export type CaseSSEEvent = {
  event: 'start' | 'progress' | 'data' | 'error' | 'complete';
  progress?: number;
  message?: string;
  status?: string;
  task_id?: number;
  case_count?: number;
};

function normalizeCaseEvent(raw: Record<string, unknown>): CaseSSEEvent {
  const status = String(raw.status || raw.event || '');
  let event: CaseSSEEvent['event'] = 'progress';
  if (raw.event === 'start' || status === 'start') event = 'start';
  else if (raw.event === 'complete' || status === 'completed') event = 'complete';
  else if (raw.event === 'error' || status === 'failed') event = 'error';
  else if (raw.event === 'data') event = 'data';
  return {
    event,
    progress: typeof raw.progress === 'number' ? raw.progress : undefined,
    message: typeof raw.message === 'string' ? raw.message : undefined,
    status: status || undefined,
    task_id: typeof raw.task_id === 'number' ? raw.task_id : undefined,
    case_count: typeof raw.case_count === 'number' ? raw.case_count : undefined,
  };
}

/** 用例生成（SSE）：对接 POST /case/generate */
export async function generateCasesSSE(
  params: {
    title?: string;
    source_type: string;
    raw_text?: string;
    url?: string;
    case_types?: string[];
    max_cases?: number;
    file?: File;
  },
  onEvent?: (event: CaseSSEEvent) => void,
  onError?: (error: Error) => void,
  onComplete?: (event: CaseSSEEvent) => void,
): Promise<void> {
  if (!params.raw_text?.trim() && !params.url?.trim() && !params.file) {
    const err = new Error('请输入需求文本、URL 或上传文件');
    onError?.(err);
    throw err;
  }
  if (params.file) {
    await assertUploadAllowed(params.file);
  }

  const form = new FormData();
  form.append('title', params.title || '');
  form.append('source_type', params.source_type || 'text');
  form.append('raw_text', params.raw_text || '');
  form.append('url', params.url || '');
  form.append('case_types', (params.case_types || ['functional', 'error', 'boundary']).join(','));
  form.append('max_cases', String(params.max_cases || 20));
  if (params.file) form.append('file', params.file);

  try {
    const response = await fetch(browserApiUrl('/case/generate'), {
      method: 'POST',
      body: form,
      credentials: 'include',
    });
    if (!response.ok) {
      const errText = await response.text();
      throw new Error(formatUploadError({ response: { data: safeJson(errText) }, message: errText || `HTTP ${response.status}` }));
    }
    const reader = response.body?.getReader();
    if (!reader) throw new Error('SSE流不可用');

    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        try {
          const raw = JSON.parse(line.slice(5).trim());
          const evt = normalizeCaseEvent(raw);
          onEvent?.(evt);
          if (evt.event === 'error') {
            const err = new Error(evt.message || '用例生成失败');
            onError?.(err);
            return;
          }
          if (evt.event === 'complete') {
            onComplete?.(evt);
            return;
          }
        } catch {
          // 忽略非 JSON 心跳
        }
      }
    }
    onComplete?.({ event: 'complete', message: '流结束' });
  } catch (err) {
    const error = err instanceof Error ? err : new Error(formatUploadError(err));
    onError?.(error);
    throw error;
  }
}

function safeJson(text: string): { detail?: string } {
  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
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
