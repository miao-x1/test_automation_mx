/**
 * 三层测试用例自动化系统 API 服务
 */
import request from './request';

// L1: 需求分析
export async function analyzeRequirement(params: {
  project_id?: string;
  title?: string;
  source_type: string;
  raw_text?: string;
  url?: string;
  use_rag?: boolean;
}): Promise<{ task_id: number; status: string; compile_level: string }> {
  return request.post('/three-layer/analyze', params);
}

// L2: 用例编译
export async function compileCases(params: {
  project_id?: string;
  title?: string;
  source_type: string;
  raw_text?: string;
  url?: string;
  use_rag?: boolean;
  case_types?: string[];
  max_cases?: number;
}): Promise<{ task_id: number; status: string; compile_level: string }> {
  return request.post('/three-layer/compile', params);
}

// L3: 脚本生成
export async function generateScripts(params: {
  project_id?: string;
  title?: string;
  source_type: string;
  raw_text?: string;
  url?: string;
  use_rag?: boolean;
  case_types?: string[];
  max_cases?: number;
  framework?: string;
  base_url?: string;
}): Promise<{ task_id: number; status: string; compile_level: string }> {
  return request.post('/three-layer/generate', params);
}

// 执行脚本
export async function executeScript(params: {
  task_id: number;
  framework?: string;
}): Promise<any> {
  return request.post('/three-layer/execute', params);
}

// 任务列表
export async function listThreeLayerTasks(params?: {
  skip?: number;
  limit?: number;
}): Promise<{ items: any[]; total: number }> {
  return request.get('/three-layer/tasks', { params });
}

// 任务详情
export async function getThreeLayerTask(taskId: number): Promise<any> {
  return request.get(`/three-layer/tasks/${taskId}`);
}

// 编译结果
export async function getTaskResult(taskId: number): Promise<{
  task_id: number;
  level: string;
  status: string;
  features?: any[];
  cases?: any[];
  scripts?: any[];
  full_code?: string;
  run_command?: string;
}> {
  return request.get(`/three-layer/tasks/${taskId}/result`);
}
