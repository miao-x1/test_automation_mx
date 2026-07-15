/**
 * 需求输入统一服务
 *
 * 对接后端 /api/v1/requirement-input/ 接口
 * 支持多模态输入：文本/图片/PDF/Word/视频/Swagger/数据库Schema
 */

import request from './request';

const BASE = '/api/v1/requirement-input';

/** 附加上下文 */
export interface RequirementContext {
  system_name?: string;
  business_background?: string;
  test_scope?: string;
  credentials?: string;
  notes?: string;
  special_requirements?: string;
}

/** 解析请求 */
export interface ParseRequest {
  text?: string;
  image_paths?: string[];
  pdf_paths?: string[];
  word_paths?: string[];
  video_paths?: string[];
  swagger_content?: string;
  schema_content?: string;
  urls?: string[];
  context?: RequirementContext;
  task_id?: string;
  user_id?: number;
  auto_generate?: boolean;
}

/** 页面信息 */
export interface PageInfo {
  url: string;
  title: string;
  page_type: string;
  description: string;
  elements: Record<string, any>[];
}

/** UI元素信息 */
export interface ElementInfo {
  name: string;
  element_type: string;
  locator: string;
  text: string;
  action: string;
  required: boolean;
}

/** 业务流程 */
export interface BusinessFlow {
  flow_name: string;
  steps: Record<string, any>[];
  preconditions: string[];
  postconditions: string[];
}

/** 测试点 */
export interface TestPoint {
  name: string;
  description: string;
  category: string;
  priority: string;
  test_data: Record<string, any>;
}

/** 约束条件 */
export interface Constraint {
  type: string;
  description: string;
  source: string;
}

/** RequirementContext 响应 */
export interface RequirementContextData {
  task_id: string;
  session_key: string;
  source_types: string[];
  source_files: string[];
  summary: string;
  intent: string;
  raw_requirement: string;
  pages: PageInfo[];
  elements: ElementInfo[];
  business_flow: BusinessFlow[];
  test_points: TestPoint[];
  constraints: Constraint[];
  metadata: Record<string, any>;
}

/** 解析响应 */
export interface ParseResponse {
  status: string;
  context: RequirementContextData;
  source_types: string[];
  summary: string;
  intent: string;
  pages_count: number;
  elements_count: number;
  test_points_count: number;
  business_flows_count: number;
  constraints_count: number;
  duration: number;
  error: string;
}

/** 上传响应 */
export interface UploadResponse {
  status: string;
  file_path: string;
  file_type: string;
  file_name: string;
  file_size: number;
  error: string;
}

/**
 * 解析多模态需求输入
 */
export async function parseRequirementInput(req: ParseRequest): Promise<ParseResponse> {
  const res = await request.post(`${BASE}/parse`, req);
  return res.data;
}

/**
 * 上传需求文件
 */
export async function uploadRequirementFile(
  file: File,
  fileCategory: string = 'auto'
): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('file_category', fileCategory);

  const res = await request.post(`${BASE}/upload`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return res.data;
}

/**
 * 解析需求并直接生成测试用例（SSE流式）
 */
export async function parseAndGenerate(req: ParseRequest): Promise<ReadableStream<Uint8Array>> {
  const token = localStorage.getItem('access_token') || '';
  const response = await fetch(`${BASE}/generate`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    credentials: 'include',
    body: JSON.stringify(req),
  });

  if (!response.body) {
    throw new Error('SSE流不可用');
  }

  return response.body;
}

/** 来源类型标签 */
export const SOURCE_TYPE_LABELS: Record<string, string> = {
  text: '文本',
  pdf: 'PDF文档',
  image: '图片',
  video: '视频',
  swagger: 'Swagger',
  schema: '数据库Schema',
  word: 'Word文档',
};

/** 来源类型颜色 */
export const SOURCE_TYPE_COLORS: Record<string, string> = {
  text: 'blue',
  pdf: 'red',
  image: 'green',
  video: 'purple',
  swagger: 'orange',
  schema: 'cyan',
  word: 'magenta',
};

/** 测试点优先级颜色 */
export const PRIORITY_COLORS: Record<string, string> = {
  high: 'red',
  medium: 'orange',
  low: 'blue',
};

/** 测试点类别标签 */
export const CATEGORY_LABELS: Record<string, string> = {
  functional: '功能测试',
  boundary: '边界测试',
  error: '异常测试',
  security: '安全测试',
  performance: '性能测试',
};
