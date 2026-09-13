import request from './request';

const dataOf = (res: any) => res?.data ?? res;

export const PROJECT_CASES_CHANGED = 'project-cases-changed';

export type CaseStep = { stepNo?: number; action?: string; data?: string; expected?: string };

export type WorkbenchCase = {
  id: number;
  case_code?: string;
  case_name?: string;
  module?: string;
  type?: string;
  priority?: string;
  source_type?: string;
  source_label?: string;
  review_status?: string;
  precondition?: string;
  test_data?: string;
  steps?: CaseStep[];
  expected_result?: string;
  postconditions?: string;
  requirement_ids?: string[];
  test_design_ids?: string[];
  test_scenario_ids?: string[];
  tags?: string[];
  risk_level?: string;
  version?: number;
};

export async function fetchCaseContext(projectId: number) {
  return dataOf(await request.get('/project-explorer/cases/context', { params: { project_id: projectId } }));
}

export async function fetchCases(projectId: number) {
  return dataOf(await request.get('/project-explorer/cases', { params: { project_id: projectId } }));
}

export async function generateCases(projectId: number, payload: Record<string, unknown>) {
  return dataOf(await request.post('/project-explorer/cases/generate', { project_id: projectId, ...payload }, { timeout: 180000 }));
}

export async function generateCasesUpload(projectId: number, text: string, files: File[]) {
  const form = new FormData();
  form.append('project_id', String(projectId));
  form.append('text', text);
  files.forEach((file) => form.append('files', file));
  return dataOf(await request.post('/project-explorer/cases/generate-upload', form, { timeout: 180000 }));
}

export async function createCase(projectId: number, row: Partial<WorkbenchCase>) {
  return dataOf(await request.post('/project-explorer/cases', { project_id: projectId, case: row }));
}

export async function updateCase(projectId: number, caseId: number, row: Partial<WorkbenchCase>) {
  return dataOf(await request.put(`/project-explorer/cases/${caseId}`, { project_id: projectId, case: row }));
}

export async function reviewCases(projectId: number, ids: number[], reviewStatus: string, note = '') {
  return dataOf(await request.post('/project-explorer/cases/review', { project_id: projectId, ids, review_status: reviewStatus, note }));
}

export async function batchCases(projectId: number, ids: number[], patch: Record<string, unknown>) {
  return dataOf(await request.post('/project-explorer/cases/batch', { project_id: projectId, ids, patch }));
}

export async function fetchCaseCoverage(projectId: number) {
  return dataOf(await request.get('/project-explorer/cases/coverage', { params: { project_id: projectId } }));
}

export async function fetchCaseQuality(projectId: number) {
  return dataOf(await request.get('/project-explorer/cases/quality', { params: { project_id: projectId } }));
}

export async function exportCasesCsv(projectId: number, ids?: number[]) {
  return dataOf(await request.get('/project-explorer/cases/export', {
    params: { project_id: projectId, ids: ids?.join(',') },
  }));
}
