/**
 * API 测试执行管理
 */
import request from './request';

// ========== 类型定义 ==========

export interface RunExecutionParams {
  case_ids?: number[];
  task_id?: number;
  env?: string;
  base_url?: string;
  headers?: Record<string, string>;
  variables?: Record<string, unknown>;
}

export interface RunCaseJsonParams {
  cases: Record<string, unknown>[];
  env?: string;
  base_url?: string;
  headers?: Record<string, string>;
  variables?: Record<string, unknown>;
}

export interface ExecutionStatus {
  execution_id: number;
  task_id: number;
  status: string;
  trigger_source: string;
  duration: number | null;
  success_count: number | null;
  failed_count: number | null;
  error_message: string | null;
  created_at: string | null;
  analysis: {
    total: number;
    passed: number;
    failed: number;
    duration_ms: number;
    cases: import('./apiReport').CaseResult[];
  } | null;
}

export interface ExecutionListItem {
  execution_id: number;
  task_id: number;
  status: string;
  trigger_source: string;
  duration: number | null;
  success_count: number | null;
  failed_count: number | null;
  created_at: string | null;
}

// ========== 执行管理 ==========

export async function runExecution(params: RunExecutionParams): Promise<{
  execution_id: number;
  status: string;
  case_count: number;
}> {
  return request.post('/api-test/execution/run', params);
}

export async function runExecutionJson(params: RunCaseJsonParams): Promise<{
  execution_id: number;
  status: string;
  case_count: number;
}> {
  return request.post('/api-test/execution/run/json', params);
}

export async function getExecutionStatus(executionId: number): Promise<ExecutionStatus> {
  return request.get(`/api-test/execution/${executionId}`);
}

export async function listExecutions(params?: {
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<{
  total: number;
  page: number;
  page_size: number;
  items: ExecutionListItem[];
}> {
  return request.get('/api-test/execution/list', { params });
}

export async function retryExecution(executionId: number): Promise<{
  execution_id: number;
  status: string;
  case_count: number;
}> {
  return request.post(`/api-test/execution/retry/${executionId}`);
}
