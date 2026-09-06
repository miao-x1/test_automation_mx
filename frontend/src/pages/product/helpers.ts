import { browserApiUrl } from '@/utils/apiUrl';
import { friendlyStep } from './testModes';

export type UserStep = {
  key: string;
  label: string;
  status: 'wait' | 'process' | 'finish' | 'error' | 'skip';
  detail?: string;
};

const TECH_WORDS: Array<[RegExp, string]> = [
  [/\bAgent\b/gi, 'AI'],
  [/\bPlaywright\b/gi, '浏览器测试'],
  [/\bLocator\b/gi, '页面元素'],
  [/\bRAG\b/gi, '历史参考'],
  [/\bEmbedding\b/gi, '语义匹配'],
  [/\bSSE\b/gi, '实时进度'],
  [/Tool Call/gi, '操作步骤'],
  [/Test Run/gi, '测试任务'],
  [/Test Result/gi, '测试结果'],
];

export function userCopy(text?: string): string {
  if (!text) return '';
  return TECH_WORDS.reduce((acc, [from, to]) => acc.replace(from, to), text);
}

export function unwrap(res: any): any {
  return res?.data ?? res;
}

export function isPageUrl(value: string): boolean {
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

export async function consumeSse(
  response: Response,
  onEvent: (msg: Record<string, any>) => void,
  timeoutMs = 300000,
): Promise<void> {
  const reader = response.body?.getReader();
  if (!reader) throw new Error('无法读取测试进度');
  const decoder = new TextDecoder();
  let buffer = '';
  const started = Date.now();
  while (true) {
    if (Date.now() - started > timeoutMs) {
      try { await reader.cancel(); } catch { /* ignore */ }
      throw new Error('测试超时，已停止等待');
    }
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data:')) continue;
      try {
        onEvent(JSON.parse(line.slice(5).trim()));
      } catch {
        /* ignore broken chunks */
      }
    }
  }
}

export async function postSse(
  path: string,
  body: unknown,
  onEvent: (msg: Record<string, any>) => void,
  timeoutMs = 300000,
): Promise<void> {
  const response = await fetch(browserApiUrl(path), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(body ?? {}),
  });
  if (!response.ok) {
    throw new Error(`请求失败 (${response.status})`);
  }
  await consumeSse(response, onEvent, timeoutMs);
}

export async function getSse(
  path: string,
  onEvent: (msg: Record<string, any>) => void,
  timeoutMs = 180000,
): Promise<void> {
  const response = await fetch(browserApiUrl(path), {
    method: 'GET',
    credentials: 'include',
  });
  if (!response.ok) {
    throw new Error(`请求失败 (${response.status})`);
  }
  await consumeSse(response, onEvent, timeoutMs);
}

export const ANALYZE_STEPS: UserStep[] = [
  { key: 'analyze_image', label: '页面元素识别', status: 'wait' },
  { key: 'parse_requirement', label: '理解测试要求', status: 'wait' },
  { key: 'classify_type', label: '确认测试内容', status: 'wait' },
  { key: 'generate_cases', label: '生成测试步骤', status: 'wait' },
  { key: 'generate_script', label: '准备测试执行', status: 'wait' },
];

export const EXECUTE_STEPS: UserStep[] = [
  { key: 'open', label: '页面加载', status: 'wait' },
  { key: 'run', label: '正在执行测试', status: 'wait' },
  { key: 'verify', label: '正在验证测试结果', status: 'wait' },
];

export function applyAnalyzeEvent(steps: UserStep[], msg: Record<string, any>): UserStep[] {
  const sname = String(msg.step_name || '');
  const evt = String(msg.event || '');
  const idx = steps.findIndex((s) => s.key === sname);
  const next = steps.map((s) => ({ ...s }));
  const label = friendlyStep(sname, userCopy(msg.data?.description || msg.message));
  if (idx >= 0) {
    if (evt === 'step_start') next[idx] = { ...next[idx], status: 'process', detail: label };
    if (evt === 'step_success') next[idx] = { ...next[idx], status: 'finish', detail: label || '完成' };
    if (evt === 'step_failed') next[idx] = { ...next[idx], status: 'error', detail: userCopy(msg.error || msg.data?.error) };
    if (evt === 'step_skipped') next[idx] = { ...next[idx], status: 'skip', detail: '已跳过' };
  }
  return next;
}

export function applyExecuteEvent(steps: UserStep[], msg: Record<string, any>): UserStep[] {
  const raw = String(msg.step || msg.event || '');
  const message = userCopy(msg.message || '');
  const next = steps.map((s) => ({ ...s }));
  const mark = (key: string, status: UserStep['status'], detail?: string) => {
    const idx = next.findIndex((s) => s.key === key);
    if (idx >= 0) next[idx] = { ...next[idx], status, detail };
  };
  if (raw.includes('开始') || raw.includes('准备')) {
    mark('open', 'process', message || '正在打开页面');
  } else if (raw === '执行完成' || raw === 'flow_success' || raw === 'done') {
    mark('open', 'finish');
    mark('run', 'finish');
    mark('verify', 'finish', message || '验证完成');
  } else if (raw === '执行异常' || raw === 'flow_failed') {
    mark('run', 'error', message || '执行失败');
    mark('verify', 'error');
  } else {
    if (next[0].status === 'wait' || next[0].status === 'process') mark('open', 'finish', '页面加载完成');
    mark('run', 'process', message || '正在测试页面');
  }
  return next;
}

export function parseCases(raw: unknown): any[] {
  if (!raw) return [];
  let data = raw;
  if (typeof raw === 'string') {
    try {
      data = JSON.parse(raw);
    } catch {
      return [];
    }
  }
  if (Array.isArray(data)) return data;
  if (Array.isArray((data as any)?.cases)) return (data as any).cases;
  if (data && typeof data === 'object' && ((data as any).title || (data as any).name)) {
    return [data];
  }
  return [];
}

export function extractPageUrl(requirement?: string): string {
  if (!requirement) return '';
  const match = requirement.match(/https?:\/\/[^\s，。]+/);
  return match?.[0] || '';
}

export function passRate(passed: number, failed: number, skipped = 0): number {
  const total = passed + failed + skipped;
  if (total <= 0) return 0;
  return Math.round((passed / total) * 1000) / 10;
}

export function flattenResultCases(detail: any): Array<{
  key: string;
  title: string;
  status: 'pass' | 'fail' | 'skip';
  expected?: string;
  actual?: string;
  reason?: string;
  steps?: string;
  analysis?: string;
}> {
  const analysis = detail?.analysis || {};
  const cases: any[] = analysis.cases || [];
  const rows: ReturnType<typeof flattenResultCases> = [];
  cases.forEach((c: any, idx: number) => {
    const sub = c.assertion_result?.results;
    if (Array.isArray(sub) && sub.length) {
      sub.forEach((st: any, j: number) => {
        rows.push({
          key: `${idx}-${j}`,
          title: st.name || c.title || `步骤 ${j + 1}`,
          status: st.passed === false || st.status === 'FAIL' ? 'fail' : st.skipped ? 'skip' : 'pass',
          expected: st.expected || c.expected,
          actual: st.actual || st.error,
          reason: st.error || c.error,
          steps: formatSteps(c.steps),
          analysis: analysis.suggestion || analysis.root_cause,
        });
      });
      return;
    }
    const statusRaw = String(c.status || '').toUpperCase();
    rows.push({
      key: String(idx),
      title: c.title || c.name || c.case_id || `测试项 ${idx + 1}`,
      status: statusRaw.includes('FAIL') ? 'fail' : statusRaw.includes('SKIP') ? 'skip' : 'pass',
      expected: Array.isArray(c.expected) ? c.expected.join('；') : c.expected,
      actual: c.actual || c.error,
      reason: c.error,
      steps: formatSteps(c.steps),
      analysis: analysis.suggestion || analysis.root_cause,
    });
  });
  if (rows.length === 0 && (detail?.success_count || detail?.failed_count)) {
    const passed = detail.success_count || 0;
    const failed = detail.failed_count || 0;
    for (let i = 0; i < passed; i += 1) {
      rows.push({ key: `p-${i}`, title: `通过项 ${i + 1}`, status: 'pass' });
    }
    for (let i = 0; i < failed; i += 1) {
      rows.push({
        key: `f-${i}`,
        title: `失败项 ${i + 1}`,
        status: 'fail',
        reason: detail.error_message,
      });
    }
  }
  return rows;
}

function formatSteps(steps: unknown): string {
  if (!Array.isArray(steps)) return typeof steps === 'string' ? steps : '';
  return steps
    .map((s, i) => `${i + 1}. ${s.action || s.description || s.step || JSON.stringify(s)}`)
    .join('\n');
}
