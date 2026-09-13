import request from './request';

export const PROJECT_PIPELINE_CHANGED = 'project-pipeline-changed';

const dataOf = (res: any) => res?.data ?? res;

export async function fetchPipelineSnapshot(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/snapshot', { params: { project_id: projectId } }));
}

export async function fetchPipelineCases(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/cases', { params: { project_id: projectId } }));
}

export async function fetchPrep(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/prep', { params: { project_id: projectId } }));
}

export async function generatePrepData(projectId: number, count: number) {
  return dataOf(await request.post('/project-explorer/pipeline/prep/data', { project_id: projectId, count }, { timeout: 60000 }));
}

export async function generatePrepAccounts(projectId: number, count: number, roles?: string[]) {
  return dataOf(await request.post('/project-explorer/pipeline/prep/accounts', { project_id: projectId, count, roles }, { timeout: 60000 }));
}

export async function batchPrepAccounts(projectId: number, ids: string[], action: string) {
  return dataOf(await request.post('/project-explorer/pipeline/prep/accounts/batch', { project_id: projectId, ids, action }));
}

export async function exportPrepAccounts(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/prep/accounts/export', { params: { project_id: projectId } }));
}

export async function checkPrepEnv(projectId: number) {
  return dataOf(await request.post('/project-explorer/pipeline/prep/env-check', { project_id: projectId }, { timeout: 30000 }));
}

export async function fetchRuns(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/runs', { params: { project_id: projectId } }));
}

export async function createRunBatch(projectId: number, caseIds?: number[], env = '') {
  return dataOf(await request.post('/project-explorer/pipeline/runs', { project_id: projectId, case_ids: caseIds, env }));
}

export async function recordRunResults(projectId: number, batchId: string, updates: any[], executor = '') {
  return dataOf(await request.post('/project-explorer/pipeline/runs/results', { project_id: projectId, batch_id: batchId, updates, executor }));
}

export async function fetchDefects(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/defects', { params: { project_id: projectId } }));
}

export async function draftDefects(projectId: number, batchId?: string) {
  return dataOf(await request.post('/project-explorer/pipeline/defects/draft', { project_id: projectId, batch_id: batchId }));
}

export async function submitDefect(projectId: number, bug: any) {
  return dataOf(await request.post('/project-explorer/pipeline/defects', { project_id: projectId, bug }));
}

export async function verifyDefect(projectId: number, bugId: string, result: string, actual: string, evidence: string[] = []) {
  return dataOf(await request.post('/project-explorer/pipeline/defects/verify', { project_id: projectId, bug_id: bugId, result, actual, evidence }));
}

export async function fetchRegressions(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/regressions', { params: { project_id: projectId } }));
}

export async function recommendRegression(projectId: number, bugIds: string[]) {
  return dataOf(await request.post('/project-explorer/pipeline/regressions/recommend', { project_id: projectId, bug_ids: bugIds }));
}

export async function createRegression(projectId: number, bugIds: string[], version = '') {
  return dataOf(await request.post('/project-explorer/pipeline/regressions', { project_id: projectId, bug_ids: bugIds, version }));
}

export async function recordRegression(projectId: number, batchId: string, updates: any[]) {
  return dataOf(await request.post('/project-explorer/pipeline/regressions/results', { project_id: projectId, batch_id: batchId, updates }));
}

export async function fetchReports(projectId: number) {
  return dataOf(await request.get('/project-explorer/pipeline/reports', { params: { project_id: projectId } }));
}

export async function createReport(projectId: number) {
  return dataOf(await request.post('/project-explorer/pipeline/reports', { project_id: projectId }));
}
