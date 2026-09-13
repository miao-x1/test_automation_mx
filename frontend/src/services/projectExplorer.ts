import request from './request';
import { collectImportableFiles } from '@/utils/projectZip';

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
export const PROJECT_REQUIREMENT_CHANGED = 'project-requirement-changed';
export const PROJECT_DESIGN_CHANGED = 'project-design-changed';

export type TestDesignDocument = {
  status: 'empty' | 'draft' | 'confirmed' | string;
  requirement_status?: string;
  requirement_completeness?: number;
  completeness?: number;
  counts?: {
    objects?: number;
    scenarios?: number;
    methods?: number;
    data?: number;
    open_questions?: number;
    high_priority?: number;
  };
  interaction?: {
    mode?: string;
    summary?: string;
    questions?: Array<{ id?: string; question: string; skippable?: boolean }>;
  };
  scope?: {
    core?: Array<{ item?: string; req_ids?: string[]; reason?: string }>;
    related?: Array<{ item?: string; req_ids?: string[]; reason?: string }>;
    regression?: Array<{ item?: string; req_ids?: string[]; reason?: string }>;
    out_of_scope?: Array<{ item?: string; req_ids?: string[]; reason?: string }>;
  };
  objects?: any[];
  scenarios?: any[];
  methods?: any[];
  flows?: any[];
  states?: any[];
  permissions?: any[];
  data?: any[];
  environment?: any[];
  priorities?: any[];
  coverage?: any[];
  risks?: any[];
  gaps?: any[];
  questions?: any[];
  task_input?: string;
  case_input?: {
    objects?: any[];
    scenarios?: any[];
    data?: any[];
    gaps?: any[];
  };
  plan?: {
    headline?: string;
    ready?: boolean;
    name?: string;
    aspects?: string[];
    methods?: string[];
    boundaries?: string[];
    roles?: string[];
    states?: string[];
    objects?: number;
    scenarios?: number;
    data_fields?: number;
    priorities?: Record<string, number>;
    next?: string;
  };
  requirement_brief?: {
    available?: boolean;
    status?: string;
    completeness?: number;
    name?: string;
    goal?: string;
    users?: string;
    in_scope?: string;
    out_of_scope?: string;
    requirements?: Array<{ id?: string; text?: string }>;
    modules?: string[];
    functions?: any[];
    rules?: any[];
    roles?: any[];
    exceptions?: any[];
    gaps?: any[];
    risks?: any[];
    data_fields?: number;
  };
  source_index?: Record<string, { kind?: string; id?: string; title?: string; text?: string; module?: string }>;
  user_notes?: string;
  llm_used?: boolean;
  llm_error?: string | null;
  updated_at?: string | null;
  confirmed_at?: string | null;
};

export type EvidenceKind = 'explicit' | 'inferred' | 'missing';

export type EvidenceField = {
  text?: string;
  evidence_kind?: EvidenceKind;
  sources?: string[];
  evidence?: string;
};

export type RequirementDocument = {
  status: 'empty' | 'draft' | 'confirmed' | string;
  source_text?: string;
  source_files?: Array<{ name: string; chars: number }>;
  completeness?: number;
  counts?: {
    requirements?: number;
    functions?: number;
    rules?: number;
    open_questions?: number;
    high_risks?: number;
  };
  interaction?: {
    mode?: string;
    summary?: string;
    questions?: Array<{ id?: string; question: string; skippable?: boolean }>;
  };
  requirements?: Array<{ id: string; text: string; source?: string }>;
  overview?: Record<string, EvidenceField>;
  functions?: any[];
  rules?: any[];
  roles?: any[];
  flows?: any[];
  data?: any[];
  exceptions?: any[];
  gaps?: any[];
  ambiguities?: any[];
  risks?: any[];
  test_focus?: string[];
  user_notes?: string;
  answers?: Array<{ id?: string; question?: string; answer?: string }>;
  design_input?: string;
  llm_used?: boolean;
  llm_error?: string | null;
  updated_at?: string | null;
  confirmed_at?: string | null;
};

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

export async function importProjectFolder(projectId: number, files: File[]) {
  const picked = collectImportableFiles(files);
  if (!picked.length) throw new Error('这个文件夹里没有可导入的文件');
  const form = new FormData();
  form.append('project_id', String(projectId));
  form.append('paths_json', JSON.stringify(picked.map((item) => item.path)));
  picked.forEach((item) => form.append('files', item.file));
  return dataOf(await request.post('/project-explorer/import/folder', form, { timeout: 120000 }));
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

export async function fetchRequirementAnalysis(projectId: number) {
  return dataOf(await request.get('/project-explorer/requirement-analysis', { params: { project_id: projectId } })) as RequirementDocument;
}

export async function analyzeRequirementText(projectId: number, text: string, answers?: Array<{ id?: string; question?: string; answer?: string }>) {
  return dataOf(await request.post('/project-explorer/requirement-analysis', {
    project_id: projectId,
    text,
    answers,
  }, { timeout: 180000 })) as RequirementDocument;
}

export async function analyzeRequirementUpload(projectId: number, text: string, files: File[]) {
  const form = new FormData();
  form.append('project_id', String(projectId));
  form.append('text', text);
  files.forEach((file) => form.append('files', file));
  return dataOf(await request.post('/project-explorer/requirement-analysis/upload', form, { timeout: 180000 })) as RequirementDocument;
}

export async function saveRequirementAnalysis(projectId: number, document: Partial<RequirementDocument>) {
  return dataOf(await request.patch('/project-explorer/requirement-analysis', {
    project_id: projectId,
    document,
  })) as RequirementDocument;
}

export async function fetchTestDesign(projectId: number) {
  return dataOf(await request.get('/project-explorer/test-design', { params: { project_id: projectId } })) as TestDesignDocument;
}

export async function generateTestDesign(projectId: number, answers?: Array<{ id?: string; question?: string; answer?: string }>) {
  return dataOf(await request.post('/project-explorer/test-design', {
    project_id: projectId,
    answers,
  }, { timeout: 180000 })) as TestDesignDocument;
}

export async function saveTestDesign(projectId: number, document: Partial<TestDesignDocument>) {
  return dataOf(await request.patch('/project-explorer/test-design', {
    project_id: projectId,
    document,
  })) as TestDesignDocument;
}

export async function confirmTestDesign(projectId: number) {
  return dataOf(await request.post('/project-explorer/test-design/confirm', {
    project_id: projectId,
  })) as TestDesignDocument;
}

export async function confirmRequirementAnalysis(projectId: number) {
  return dataOf(await request.post('/project-explorer/requirement-analysis/confirm', {
    project_id: projectId,
  })) as RequirementDocument;
}

export async function askProjectAgent(
  projectId: number,
  question: string,
  workspace: string,
  confirm = false,
  testTaskId?: number,
  extra?: { signal?: AbortSignal },
) {
  return dataOf(await request.post('/project-explorer/agent/ask', {
    project_id: projectId,
    question,
    workspace,
    confirm,
    test_task_id: testTaskId,
  }, extra?.signal ? { signal: extra.signal, timeout: 90000 } : { timeout: 90000 })) as AgentReply;
}
