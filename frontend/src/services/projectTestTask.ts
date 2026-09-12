import request from './request';

const dataOf = (res: any) => res?.data ?? res;

export type TestCaseRow = {
  id?: number;
  case_code?: string;
  module?: string;
  scenario?: string;
  case_name?: string;
  precondition?: string;
  steps?: Array<{ no?: number; action?: string; data?: string }> | string[];
  test_data?: string;
  expected_result?: string;
  priority?: string;
  type?: string;
  tags?: string[];
  status?: string;
};

export type TestTaskWorkspace = {
  id: number;
  project_id: number;
  name: string;
  focus?: string;
  status?: string;
  requirement_text?: string;
  analysis?: any;
  strategy?: any;
  cases?: TestCaseRow[];
  case_count?: number;
  executions?: any[];
  defects?: any[];
  reports?: any[];
  scripts?: any[];
  data_assets?: any[];
  brain?: any;
  operations?: Record<string, string>;
};

export async function listTestTasks(projectId: number) {
  return dataOf(await request.get('/test-tasks', { params: { project_id: projectId } })) as TestTaskWorkspace[];
}

export async function createTestTask(projectId: number, name: string, requirementText = '', focus = '') {
  return dataOf(await request.post('/test-tasks', {
    project_id: projectId,
    name,
    requirement_text: requirementText,
    focus,
  })) as TestTaskWorkspace;
}

export async function fetchTestTask(projectId: number, taskId: number) {
  return dataOf(await request.get(`/test-tasks/${taskId}`, { params: { project_id: projectId } })) as TestTaskWorkspace;
}

export async function updateTestTask(projectId: number, taskId: number, payload: Record<string, unknown>) {
  return dataOf(await request.patch(`/test-tasks/${taskId}`, payload, { params: { project_id: projectId } }));
}

export async function listTaskCases(projectId: number, taskId: number) {
  return dataOf(await request.get(`/test-tasks/${taskId}/cases`, { params: { project_id: projectId } })) as TestCaseRow[];
}

export async function createTaskCase(projectId: number, taskId: number, payload: TestCaseRow) {
  return dataOf(await request.post(`/test-tasks/${taskId}/cases`, payload, { params: { project_id: projectId } }));
}

export async function updateTaskCase(projectId: number, taskId: number, caseId: number, payload: TestCaseRow) {
  return dataOf(await request.put(`/test-tasks/${taskId}/cases/${caseId}`, payload, { params: { project_id: projectId } }));
}

export async function deleteTaskCase(projectId: number, taskId: number, caseId: number) {
  return dataOf(await request.delete(`/test-tasks/${taskId}/cases/${caseId}`, { params: { project_id: projectId } }));
}

export async function exportTaskCases(projectId: number, taskId: number) {
  return dataOf(await request.get(`/test-tasks/${taskId}/cases/export`, { params: { project_id: projectId } }));
}

export async function operateTestTask(projectId: number, taskId: number, op: string, extra: Record<string, unknown> = {}) {
  return dataOf(await request.post(`/test-tasks/${taskId}/operations`, { op, ...extra }, { params: { project_id: projectId } }));
}
