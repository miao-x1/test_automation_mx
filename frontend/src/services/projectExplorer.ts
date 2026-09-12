import request from './request';

const dataOf = (res: any) => res?.data ?? res;

export type CodeHit = {
  id?: number;
  kind: string;
  name: string;
  path: string;
  module?: string;
  language?: string;
  line_start?: number;
  line_end?: number;
  signature?: string;
  snippet?: string;
};

export type AgentReply = {
  answer: string;
  workspace: string;
  project_id: number;
  intent?: string;
  path?: string;
  test_task_id?: number;
  locations: CodeHit[];
  memory_used: Array<{ kind: string; title: string; content?: string }>;
  brain?: { cards?: Array<{ title?: string }>; playbooks?: string[] };
  actions: any[];
};

export const PROJECT_AGENT_ASK = 'project-agent-ask';
export const PROJECT_AGENT_OPEN = 'project-agent-open';
export const PROJECT_MEMORY_CHANGED = 'project-memory-changed';

export function askProjectAgentFromAnywhere(question: string) {
  window.dispatchEvent(new CustomEvent(PROJECT_AGENT_ASK, { detail: { question } }));
}

export function openProjectAgent(question?: string) {
  window.dispatchEvent(new CustomEvent(PROJECT_AGENT_OPEN, { detail: { question: question || '' } }));
}

export function apiError(err: any, fallback = '操作失败') {
  const detail = err?.response?.data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const text = detail.map((item) => item?.msg || item?.message || '').filter(Boolean).join('；');
    if (text) return text;
  }
  return err?.message || fallback;
}

export async function importGithubRepo(projectId: number, repoUrl: string) {
  if (!repoUrl.trim()) throw new Error('请输入 Git 仓库地址');
  return dataOf(await request.post('/project-explorer/import/git', { project_id: projectId, repo_url: repoUrl.trim() }, { timeout: 90000 }));
}

export async function importGitRepo(projectId: number, repoUrl: string) {
  return importGithubRepo(projectId, repoUrl);
}

export async function importProjectArchive(projectId: number, file: File) {
  const form = new FormData();
  form.append('project_id', String(projectId));
  form.append('file', file);
  return dataOf(await request.post('/project-explorer/import/archive', form, { timeout: 90000 }));
}

export async function fetchProjectUnderstanding(projectId: number, refresh = false) {
  return dataOf(await request.get('/project-explorer/understanding', { params: { project_id: projectId, refresh } }));
}

export async function analyzeProject(projectId: number, mode: 'incremental' | 'full' = 'incremental') {
  return dataOf(await request.post('/project-explorer/analyze', { project_id: projectId, mode }, { timeout: 90000 }));
}

export async function previewGeneratedCases(projectId: number, query: string) {
  return dataOf(await request.post('/project-explorer/cases/preview', { project_id: projectId, query }));
}

export async function fetchProjectFile(projectId: number, path: string) {
  return dataOf(await request.get('/project-explorer/file', { params: { project_id: projectId, path } }));
}

export async function importSampleRepo(projectId: number) {
  return dataOf(await request.post('/project-explorer/import/sample', { project_id: projectId }));
}

export async function fetchProjectOverview(projectId: number) {
  return dataOf(await request.get('/project-explorer/overview', { params: { project_id: projectId } }));
}

export async function fetchProjectIndex(projectId: number, params: Record<string, unknown> = {}) {
  return dataOf(await request.get('/project-explorer/index', { params: { project_id: projectId, ...params } }));
}

export async function fetchProjectMemory(projectId: number) {
  return dataOf(await request.get('/project-explorer/memory', { params: { project_id: projectId } }));
}

export async function askProjectAgent(
  projectId: number,
  question: string,
  workspace: string,
  confirm = false,
  testTaskId?: number,
) {
  return dataOf(await request.post('/project-explorer/agent/ask', {
    project_id: projectId,
    question,
    workspace,
    confirm,
    test_task_id: testTaskId,
  })) as AgentReply;
}
