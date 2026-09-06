import request from './request';
import { browserApiUrl } from '@/utils/apiUrl';

export type Assessment = {
  id: number;
  project_id: number;
  creator_id?: number;
  name: string;
  target_url: string;
  environment_id?: number;
  rounds: number;
  scenario: string;
  status: string;
  score_total?: number | null;
  score_page?: number | null;
  score_resource?: number | null;
  score_network?: number | null;
  score_job?: number | null;
  score_regression?: number | null;
  report?: Record<string, any>;
  issues?: Array<{
    problem: string;
    metric: string;
    actual: unknown;
    reference: string;
    impact: string;
    advice: string;
  }>;
  advice?: { summary?: string } | string | null;
  error_message?: string | null;
  created_at?: string;
  finished_at?: string;
};

const dataOf = (res: any) => res?.data ?? res;

export async function listAssessments(projectId: number) {
  return dataOf(await request.get(`/projects/${projectId}/assessments`));
}

export async function createAssessment(projectId: number, payload: {
  name: string;
  target_url?: string;
  environment_id?: number;
  rounds?: number;
  scenario?: string;
}) {
  return dataOf(await request.post(`/projects/${projectId}/assessments`, payload));
}

export async function getAssessment(projectId: number, assessmentId: number) {
  return dataOf(await request.get(`/projects/${projectId}/assessments/${assessmentId}`));
}

export async function deleteAssessment(projectId: number, assessmentId: number) {
  return dataOf(await request.delete(`/projects/${projectId}/assessments/${assessmentId}`));
}

export async function runAssessment(projectId: number, assessmentId: number) {
  return dataOf(await request.post(`/projects/${projectId}/assessments/${assessmentId}/run`, {}, { timeout: 180000 }));
}

export async function runAssessmentStream(
  projectId: number,
  assessmentId: number,
  onStep: (step: string) => void,
): Promise<Assessment> {
  const resp = await fetch(browserApiUrl(`/projects/${projectId}/assessments/${assessmentId}/run/stream`), {
    method: 'POST',
    credentials: 'include',
    headers: { Accept: 'text/event-stream' },
  });
  if (!resp.ok) {
    throw new Error(resp.status === 403 ? '没有执行权限' : '测评执行失败');
  }
  const reader = resp.body?.getReader();
  if (!reader) {
    throw new Error('无法读取测评进度');
  }
  const decoder = new TextDecoder();
  let buffer = '';
  let result: Assessment | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split('\n\n');
    buffer = chunks.pop() || '';
    for (const chunk of chunks) {
      const line = chunk.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      try {
        const payload = JSON.parse(line.slice(6));
        if (payload.step) onStep(payload.step);
        if (payload.done && payload.data) result = payload.data;
      } catch {
        // ignore incomplete frames
      }
    }
  }
  if (!result) {
    throw new Error('测评没有返回结果');
  }
  return result;
}
