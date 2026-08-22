/**
 * API 接口管理 - 前端服务层
 *
 * 对应后端路由前缀: /api/endpoints
 * 由于 request.ts 中 baseURL 已配置为 '/api', 本文件路径前缀为 '/endpoints'
 *
 * 覆盖接口:
 *   1. CRUD       - createEndpoint / listEndpoints / getEndpoint / updateEndpoint / deleteEndpoint
 *   2. 状态管理    - publishEndpoint / changeStatus
 *   3. 版本管理    - listVersions / getVersion / rollbackToVersion
 *   4. 统计       - getStats
 *   5. 批量导入    - batchImport
 */
import request from './request';

// ============================================================
// 类型定义 (与后端 schemas/api_endpoint.py 对齐)
// ============================================================

export type HTTPMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH' | 'HEAD' | 'OPTIONS';
export type EndpointStatus = 'draft' | 'active' | 'deprecated' | 'archived';
export type EndpointSource = 'manual' | 'swagger' | 'postman' | 'har' | 'import' | 'ai';
export type AuthType = 'none' | 'basic' | 'bearer' | 'api_key' | 'oauth2' | 'custom';

export interface HeaderItem {
  key: string;
  value: string;
  desc?: string;
}

export interface ParamItem {
  name: string;
  location?: 'query' | 'path' | 'header' | 'cookie';
  type?: 'string' | 'integer' | 'boolean' | 'number' | 'array' | 'object';
  required?: boolean;
  default?: string | null;
  desc?: string;
  example?: string | null;
}

export interface BodySpec {
  content_type?: 'application/json' | 'form-data' | 'x-www-form-urlencoded' | 'raw';
  raw?: string | null;
  json_schema?: Record<string, unknown> | null;
  form_fields?: Array<Record<string, unknown>> | null;
  example?: unknown;
}

export interface ResponseSpec {
  status_code?: number;
  headers?: HeaderItem[] | null;
  body_schema?: Record<string, unknown> | null;
  example?: unknown;
  desc?: string;
}

export interface AuthSpec {
  type?: AuthType;
  details?: Record<string, unknown> | null;
}

// ============================================================
// 子表数据结构 (后端重构后: headers / body / parameters 拆分为独立子表)
// ============================================================

export interface ApiHeaderItem {
  id?: number;
  api_id?: number;
  key: string;
  value: string | null;
  required: boolean;
  sort_order: number;
}

export interface ApiBodyItem {
  id?: number;
  api_id?: number;
  body_type: string;
  schema_json: string | object | null;
  example_json: string | object | null;
  raw_text: string | null;
}

export interface ApiParameterItem {
  id?: number;
  api_id?: number;
  location: string;
  name: string;
  type: string;
  required: boolean;
  default_value: string | null;
  description: string | null;
  example: string | null;
  sort_order: number;
}

// 接口详情
export interface ApiEndpoint {
  id: number;
  name: string;
  method: HTTPMethod;
  path: string;
  summary?: string | null;
  description?: string | null;
  tags: string[];
  module?: string | null;
  status: EndpointStatus;
  source: EndpointSource;
  headers: HeaderItem[];
  params: ParamItem[];
  body?: BodySpec | null;
  response?: ResponseSpec | null;
  auth: AuthSpec;
  // 子表数据 (后端重构后优先使用,旧 JSON 字段保留以兼容)
  api_headers?: ApiHeaderItem[];
  api_body?: ApiBodyItem | null;
  api_parameters?: ApiParameterItem[];
  version: number;
  user_id?: number | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
}

// 列表项 (精简字段)
export interface ApiEndpointListItem {
  id: number;
  name: string;
  method: HTTPMethod;
  path: string;
  summary?: string | null;
  module?: string | null;
  status: EndpointStatus;
  source: EndpointSource;
  version: number;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface ApiEndpointListResponse {
  total: number;
  page: number;
  page_size: number;
  items: ApiEndpointListItem[];
}

export interface ApiEndpointStats {
  total: number;
  by_status: Record<string, number>;
  by_method: Record<string, number>;
  by_module: Record<string, number>;
}

export interface ApiEndpointVersionItem {
  id: number;
  endpoint_id: number;
  version: number;
  change_log?: string | null;
  is_current: boolean;
  created_by?: number | null;
  created_at: string;
}

export interface ApiEndpointVersionDetail extends ApiEndpointVersionItem {
  snapshot: Record<string, unknown>;
}

export interface BatchImportResult {
  total: number;
  imported: number;
  skipped: number;
  failed: number;
  errors: string[];
  imported_ids: number[];
}

// 创建/更新请求
export interface EndpointCreateInput {
  name: string;
  method: HTTPMethod | string;
  path: string;
  summary?: string;
  description?: string;
  tags?: string[];
  module?: string;
  status?: EndpointStatus;
  source?: EndpointSource;
  headers?: HeaderItem[];
  params?: ParamItem[];
  body?: BodySpec;
  response?: ResponseSpec;
  auth?: AuthSpec;
}

export type EndpointUpdateInput = Partial<EndpointCreateInput>;

export interface EndpointListParams {
  keyword?: string;
  method?: string;
  module?: string;
  status?: string;
  tags?: string[];
  page?: number;
  page_size?: number;
}

// ============================================================
// API 调用
// ============================================================

// ---- CRUD ----

export async function createEndpoint(data: EndpointCreateInput): Promise<ApiEndpoint> {
  return request.post('/endpoints', data);
}

export async function listEndpoints(params: EndpointListParams = {}): Promise<ApiEndpointListResponse> {
  const query: Record<string, unknown> = {
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  };
  if (params.keyword) query.keyword = params.keyword;
  if (params.method) query.method = params.method;
  if (params.module) query.module = params.module;
  if (params.status) query.status = params.status;
  if (params.tags && params.tags.length) query.tags = params.tags.join(',');
  return request.get('/endpoints/list', { params: query });
}

export async function getEndpoint(id: number): Promise<ApiEndpoint> {
  return request.get(`/endpoints/${id}`);
}

export async function updateEndpoint(id: number, data: EndpointUpdateInput): Promise<ApiEndpoint> {
  return request.put(`/endpoints/${id}`, data);
}

export async function deleteEndpoint(id: number): Promise<void> {
  return request.delete(`/endpoints/${id}`);
}

// ---- 状态管理 ----

export async function publishEndpoint(id: number, changeLog: string = ''): Promise<ApiEndpoint> {
  return request.post(`/endpoints/${id}/publish`, { change_log: changeLog });
}

export async function changeEndpointStatus(id: number, newStatus: EndpointStatus): Promise<ApiEndpoint> {
  return request.put(`/endpoints/${id}/status`, undefined, {
    params: { new_status: newStatus },
  });
}

// ---- 版本管理 ----

export async function listEndpointVersions(id: number): Promise<ApiEndpointVersionItem[]> {
  return request.get(`/endpoints/${id}/versions`);
}

export async function getEndpointVersion(id: number, version: number): Promise<ApiEndpointVersionDetail> {
  return request.get(`/endpoints/${id}/versions/${version}`);
}

export async function rollbackEndpoint(id: number, version: number): Promise<ApiEndpoint> {
  return request.post(`/endpoints/${id}/rollback/${version}`);
}

// ---- 统计 ----

export async function getEndpointStats(): Promise<ApiEndpointStats> {
  return request.get('/endpoints/stats');
}

// ---- 批量导入 ----

export async function batchImportEndpoints(
  endpoints: EndpointCreateInput[],
  source: EndpointSource = 'import',
): Promise<BatchImportResult> {
  return request.post('/endpoints/batch-import', endpoints, { params: { source } });
}
