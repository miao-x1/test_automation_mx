/**
 * API 测试报告管理
 */
import request from './request';

// ========== 类型定义 ==========

export interface StepResult {
  step_index: number;
  action: string;
  url: string;
  status_code?: number;
  elapsed_ms?: number;
  error?: string;
}

export interface CaseResult {
  case_id: string;
  title: string;
  status: string;
  duration_ms: number;
  steps?: StepResult[];
  assertion_result?: {
    passed: boolean;
    results: AssertionDetail[];
    passed_count: number;
    failed_count: number;
  };
  error?: string;
}

export interface AssertionDetail {
  type: string;
  path: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
  message: string;
}

export interface ExecutionReport {
  execution_id: number;
  status: string;
  env: string;
  total: number;
  passed: number;
  failed: number;
  pass_rate: string;
  duration_ms: number;
  created_at: string | null;
  cases: CaseResult[];
  html?: string;
  markdown?: string;
}

// ========== 报告管理 ==========

export async function getExecutionReport(
  executionId: number,
  format: string = 'json',
): Promise<ExecutionReport> {
  return request.get(`/api-test/execution/${executionId}/report`, { params: { format } });
}

export async function exportReport(
  executionId: number,
  format: 'html' | 'markdown',
): Promise<Blob> {
  return request.get(`/api-test/execution/${executionId}/report/export`, {
    params: { format },
    responseType: 'blob',
  });
}
