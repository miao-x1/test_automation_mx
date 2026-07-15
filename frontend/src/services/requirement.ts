import request from './request';

// ============ 需求驱动测试 ============

export interface RequirementTask {
  id: number;
  requirement: string;
  status: string;
  intent: string | null;
  task_id: number | null;
  execution_id: number | null;
  error_message: string | null;
  created_at: string | null;
}

// 生成测试脚本（不执行）
export function generateScript(requirement: string) {
  return request.post('/requirement/generate', { requirement, execute: false });
}

// 生成并执行测试脚本
export function generateAndExecute(requirement: string) {
  return request.post('/requirement/generate_and_execute', { requirement, execute: true });
}

// 获取需求任务列表
export function getRequirementTasks(limit: number = 20) {
  return request.get('/requirement/list', { params: { limit } });
}

// 获取需求任务详情
export function getRequirementTask(taskId: number) {
  return request.get(`/requirement/${taskId}`);
}

// ============ RAG扩展接口 ============

// 索引历史测试用例
export function indexCases() {
  return request.post('/rag/index/cases');
}

// 索引历史脚本
export function indexScripts() {
  return request.post('/rag/index/scripts');
}
