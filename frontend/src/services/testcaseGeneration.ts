/**
 * 测试用例生成 API 服务
 *
 * 对接后端 /api/v1/testcase/* 端点
 * 阶段四新增：编辑持久化、删除、重新生成、Agent消息日志
 */
import api from './request';

// ===== 类型定义 =====

export interface GenerateRequest {
  requirement: string;
  task_id?: string;
  source_type?: string;
  document_context?: string;
  image_description?: string;
  image_data?: string;
  workflow_name?: string;
}

export interface GenerateResponse {
  session_id: string;
  task_id: string;
  status: string;
  workflow: string;
  requirement_id: number;
  total_points: number;
  total_cases: number;
  avg_score: number;
  duration: number;
  error: string;
}

export interface TestCaseItem {
  id: number;
  point_id: number;
  case_name: string;
  precondition: string;
  steps: Array<{
    step_no?: number;
    action?: string;
    description?: string;
    target?: string;
    value?: string;
    expected?: string;
  }>;
  expected_result: string;
  priority: string;
  type: string;
  status: string;
  review_score: number;
  review_result: string;
  review_suggestions: string[];
}

export interface TestCaseResult {
  requirement: Record<string, any> | null;
  test_points: Array<{
    id: number;
    name: string;
    description: string;
    priority: string;
    type: string;
    scenario: string;
    case_count: number;
  }>;
  test_cases: TestCaseItem[];
  total: number;
}

export interface MindMapNode {
  name: string;
  children: MindMapNode[];
  priority?: string;
  status?: string;
}

export interface MindMapResponse {
  task_id: string;
  mindmap: MindMapNode;
  format: string;
  version: number;
}

/** 更新测试用例请求 */
export interface UpdateTestCaseRequest {
  case_name?: string;
  precondition?: string;
  steps?: Array<Record<string, any>>;
  expected_result?: string;
  priority?: string;
  type?: string;
  status?: string;
}

/** 更新测试用例响应 */
export interface UpdateTestCaseResponse {
  status: string;
  case_id: number;
  version: number;
  message: string;
}

/** 删除测试用例响应 */
export interface DeleteTestCaseResponse {
  status: string;
  case_id: number;
  message: string;
}

/** 重新生成响应 */
export interface RegenerateResponse {
  status: string;
  task_id: string;
  message: string;
}

/** Agent消息记录 */
export interface AgentMessageItem {
  id: number;
  message_type: string;
  sender: string;
  receiver: string | null;
  action: string | null;
  content: Record<string, any> | null;
  result: Record<string, any> | null;
  status: string;
  error: string | null;
  duration: number;
  step: string;
  created_at: string | null;
}

/** Agent消息列表响应 */
export interface AgentMessagesResponse {
  task_id: string;
  messages: AgentMessageItem[];
  total: number;
}

// ===== API 方法 =====

/** 开始测试用例生成 */
export async function generateTestCases(request: GenerateRequest): Promise<GenerateResponse> {
  const response = await api.post('/api/v1/testcase/generate', request);
  return response.data;
}

/** 查询测试用例生成结果 */
export async function getTestCases(taskId: string): Promise<TestCaseResult> {
  const response = await api.get(`/api/v1/testcase/${taskId}`);
  return response.data;
}

/** 获取思维导图数据 */
export async function getMindMap(taskId: string): Promise<MindMapResponse> {
  const response = await api.get(`/api/v1/testcase/mindmap/${taskId}`);
  return response.data;
}

/**
 * 更新测试用例（阶段四新增）
 * 调用 PUT /api/v1/test-case/{case_id}
 */
export async function updateTestCase(caseId: number, request: UpdateTestCaseRequest): Promise<UpdateTestCaseResponse> {
  const response = await api.put(`/api/v1/test-case/${caseId}`, request);
  return response.data;
}

/**
 * 删除测试用例（阶段四新增）
 * 调用 DELETE /api/v1/test-case/{case_id}
 */
export async function deleteTestCase(caseId: number): Promise<DeleteTestCaseResponse> {
  const response = await api.delete(`/api/v1/test-case/${caseId}`);
  return response.data;
}

/**
 * 重新生成测试用例（阶段四新增）
 * 调用 POST /api/v1/test-case/regenerate/{task_id}
 */
export async function regenerateTestCases(taskId: string): Promise<RegenerateResponse> {
  const response = await api.post(`/api/v1/test-case/regenerate/${taskId}`);
  return response.data;
}

/**
 * 获取Agent执行消息日志（阶段四新增）
 * 调用 GET /api/v1/test-case/{task_id}/messages
 */
export async function getAgentMessages(taskId: string): Promise<AgentMessagesResponse> {
  const response = await api.get(`/api/v1/test-case/${taskId}/messages`);
  return response.data;
}
