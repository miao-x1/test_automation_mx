/**
 * AI 接口调试服务
 *
 * 后端路由前缀: /api/api-debug
 * 接口分组:
 *   1. 执行接口   - POST /execute
 *   2. AI 分析    - POST /analyze/{record_id}  POST /analyze/inline
 *   3. 健康检查   - GET  /health
 *   4. 记录查询   - GET  /records/list  GET /records/{id}  DELETE /records/{id}
 *   5. 错误模式   - GET  /patterns
 */
import request from './request';

// ============================================================
// 类型定义
// ============================================================

export type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';

export interface ExecuteRequest {
  method: HttpMethod;
  url: string;
  headers?: Record<string, string>;
  params?: Record<string, any>;
  body?: any;
  auth?: {
    type: 'none' | 'bearer' | 'basic' | 'api_key';
    token?: string;
    username?: string;
    password?: string;
    key_name?: string;
    key_value?: string;
  };
  timeout?: number;
  api_id?: number;
  case_id?: number;
  env?: string;
  auto_analyze?: boolean;
}

export interface ExecuteResult {
  status: 'success' | 'failed' | 'error' | 'timeout' | 'pending';
  record_id: number;
  request: {
    method: string;
    url: string;
    headers: Record<string, string>;
    params: Record<string, any>;
    body: any;
    auth?: any;
  };
  response?: {
    status_code: number;
    headers: Record<string, string>;
    body: any;
    size: number;
  };
  status_code?: number;
  duration: number;
  error?: string;
  analysis?: AnalysisResult;
}

export interface AnalysisResult {
  status: 'success' | 'degraded' | 'error' | 'skipped';
  record_id?: number;
  problem_cause: string;
  solution: string;
  fix_suggestion: string;
  confidence: number;
  category?: string;
  source: 'llm' | 'rule_engine';
  elapsed_ms: number;
  message?: string;
}

export interface ExecutionRecord {
  id: number;
  api_id?: number;
  case_id?: number;
  execution_id?: number;
  method: string;
  url: string;
  headers?: any;
  params?: any;
  body?: any;
  auth?: any;
  status_code?: number;
  response_headers?: any;
  response_body?: any;
  response_size?: number;
  status: string;
  duration: number;
  error?: string;
  analysis_status: string;
  analysis_result?: any;
  analyzed_at?: string;
  env?: string;
  trigger_source?: string;
  client_ip?: string;
  created_at?: string;
}

export interface ExecutionRecordList {
  total: number;
  page: number;
  page_size: number;
  items: ExecutionRecord[];
}

export interface DebugHealth {
  status: string;
  agent: string;
  capabilities: string[];
  patterns_count: number;
  llm_available: boolean;
  supported_actions: string[];
}

export interface ErrorPattern {
  id: string;
  keywords: string[];
  problem_cause: string;
  confidence: number;
}

// ============================================================
// API 调用
// ============================================================

/** 执行 HTTP 请求 */
export async function executeRequest(data: ExecuteRequest): Promise<ExecuteResult> {
  const resp = await request.post('/api-debug/execute', data);
  return resp.data;
}

/** AI 分析执行记录 */
export async function analyzeRecord(recordId: number, force = false): Promise<AnalysisResult> {
  const resp = await request.post(`/api-debug/analyze/${recordId}`, null, {
    params: { force },
  });
  return resp.data;
}

/** 直接分析(不落库) */
export async function analyzeInline(payload: {
  request?: any;
  response?: any;
  error?: string;
  status?: string;
}): Promise<AnalysisResult> {
  const resp = await request.post('/api-debug/analyze/inline', payload);
  return resp.data;
}

/** Agent 健康检查 */
export async function debugHealthCheck(): Promise<DebugHealth> {
  const resp = await request.get('/api-debug/health');
  return resp.data;
}

/** 执行记录列表 */
export async function listExecutionRecords(params: {
  api_id?: number;
  case_id?: number;
  status?: string;
  status_code?: number;
  method?: string;
  keyword?: string;
  page?: number;
  page_size?: number;
}): Promise<ExecutionRecordList> {
  const resp = await request.get('/api-debug/records/list', { params });
  return resp.data;
}

/** 执行记录详情 */
export async function getExecutionRecord(recordId: number): Promise<ExecutionRecord> {
  const resp = await request.get(`/api-debug/records/${recordId}`);
  return resp.data;
}

/** 删除执行记录 */
export async function deleteExecutionRecord(recordId: number): Promise<void> {
  await request.delete(`/api-debug/records/${recordId}`);
}

/** 错误模式列表 */
export async function listErrorPatterns(): Promise<{ total: number; patterns: ErrorPattern[] }> {
  const resp = await request.get('/api-debug/patterns');
  return resp.data;
}
