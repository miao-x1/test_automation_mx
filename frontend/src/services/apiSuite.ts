/**
 * API 测试套件管理
 */
import request from './request';

// ========== 类型定义 ==========

export interface TestSuite {
  id: number;
  name: string;
  description?: string;
  suite_type: string;
  status: string;
  case_ids: number[];
  cases?: {
    id: number;
    case_id?: string;
    title: string;
    priority: string;
    status: string;
    last_run_status?: string;
  }[];
  env: string;
  base_url?: string;
  headers?: Record<string, string>;
  variables?: Record<string, unknown>;
  concurrency: number;
  fail_strategy: string;
  retry_count: number;
  last_run_at?: string;
  run_count: number;
  created_at?: string;
}

export interface SuiteExecution {
  id: number;
  execution_id: number;
  status: string;
  total: number;
  passed: number;
  failed: number;
  duration?: number;
  created_at?: string;
}

// ========== 套件管理 ==========

export async function saveSuite(data: {
  id?: number;
  name: string;
  description?: string;
  suite_type?: string;
  case_ids: number[];
  env?: string;
  base_url?: string;
  headers?: Record<string, string>;
  variables?: Record<string, unknown>;
  concurrency?: number;
  fail_strategy?: string;
  retry_count?: number;
}): Promise<{ id: number; name: string; suite_type: string; case_count: number }> {
  return request.post('/api-test/suite/save', data);
}

export async function listSuites(params?: {
  suite_type?: string;
  page?: number;
  page_size?: number;
}): Promise<{
  total: number;
  items: TestSuite[];
}> {
  return request.get('/api-test/suite/list', { params });
}

export async function getSuite(suiteId: number): Promise<TestSuite> {
  return request.get(`/api-test/suite/${suiteId}`);
}

export async function deleteSuite(suiteId: number): Promise<void> {
  return request.delete(`/api-test/suite/${suiteId}`);
}

export async function runSuite(suiteId: number): Promise<{
  execution_id: number;
  suite_id: number;
  case_count: number;
  status: string;
}> {
  return request.post(`/api-test/suite/${suiteId}/run`);
}

export async function getSuiteExecutions(suiteId: number, params?: {
  page?: number;
  page_size?: number;
}): Promise<{
  total: number;
  items: SuiteExecution[];
}> {
  return request.get(`/api-test/suite/${suiteId}/executions`, { params });
}
