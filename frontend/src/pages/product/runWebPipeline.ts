import request from '@/services/request';
import {
  ANALYZE_STEPS,
  EXECUTE_STEPS,
  applyAnalyzeEvent,
  applyExecuteEvent,
  getSse,
  parseCases,
  postSse,
  unwrap,
  userCopy,
  type UserStep,
} from './helpers';
import { getCurrentProjectId } from './projectStore';

export type PipelineCallbacks = {
  onSteps: (steps: UserStep[]) => void;
  onLog: (line: string) => void;
  onCases: (cases: any[]) => void;
};

function stamp(text: string) {
  return `${new Date().toLocaleTimeString()}  ${text}`;
}

export async function runAnalyzePipeline(input: {
  requirement: string;
  imagePaths?: string[];
  documentPaths?: string[];
  taskType?: string;
  execute: boolean;
  callbacks: PipelineCallbacks;
}): Promise<{ requirementId: number; executionId: number | null; result: any | null; cases: any[] }> {
  const { callbacks } = input;
  let steps: UserStep[] = [...ANALYZE_STEPS];
  callbacks.onSteps(steps);
  callbacks.onLog(stamp('创建测试任务'));

  const created: any = await request.post('/requirement/create', {
    requirement: input.requirement,
    task_type: input.taskType || 'web',
    script_format: 'playwright',
    image_paths: input.imagePaths || [],
    document_paths: input.documentPaths || [],
    project_id: getCurrentProjectId() || undefined,
    test_scope: { kind: input.taskType || 'web' },
  });
  const createdData = unwrap(created);
  const reqId = createdData?.id;
  if (!reqId) throw new Error(created?.message || '创建测试任务失败');
  callbacks.onLog(stamp(`任务已创建 #${reqId}`));

  let analyzeFailed = false;
  let analyzeOk = false;
  let flowError = '';
  const collected: any[] = [];

  await postSse(`/requirement/analyze/${reqId}`, {}, (msg) => {
    const line = userCopy(msg.message || msg.data?.description || msg.step_name || msg.event || '');
    if (line) callbacks.onLog(stamp(line));
    steps = applyAnalyzeEvent(steps, msg);
    callbacks.onSteps([...steps]);
    const evt = String(msg.event || '');
    const sname = String(msg.step_name || '');
    const output = msg.data?.output;
    if (sname === 'generate_cases' && output?.cases && Array.isArray(output.cases)) {
      collected.push(...output.cases);
      callbacks.onCases([...collected]);
    }
    if (evt === 'step_failed' || evt === 'flow_failed') {
      analyzeFailed = true;
      flowError = userCopy(msg.error || msg.data?.error || output?.error || '分析失败');
    }
    if (evt === 'step_success' && sname === 'generate_script' && (output?.status === 'FAILED' || output?.error)) {
      analyzeFailed = true;
      flowError = userCopy(output?.error || output?.message || '测试准备失败');
    }
    if (evt === 'flow_success' && !analyzeFailed) analyzeOk = true;
  });

  if (!analyzeOk || analyzeFailed) {
    throw new Error(flowError || '分析未完成');
  }

  const detail = unwrap(await request.get(`/requirement/${reqId}`));
  const cases = collected.length ? collected : parseCases(detail?.generated_case);
  callbacks.onCases(cases);

  if (!input.execute) {
    callbacks.onLog(stamp('视觉分析完成，本次未打开浏览器执行'));
    return { requirementId: reqId, executionId: null, result: { analysis: { cases }, status: 'success', success_count: cases.length, failed_count: 0 }, cases };
  }

  const linkedTaskId = detail?.task_id;
  const script = detail?.generated_script || '';
  if (!linkedTaskId || !script) {
    throw new Error('测试步骤已生成，但还不能执行。请检查模型配置后重试。');
  }

  steps = [
    ...steps.map((s) => (s.status === 'wait' ? { ...s, status: 'skip' as const } : s)),
    ...EXECUTE_STEPS,
  ];
  callbacks.onSteps([...steps]);
  callbacks.onLog(stamp('开始执行测试'));

  const execRes: any = await request.post(`/executions/${linkedTaskId}/execute`, {});
  const execId = unwrap(execRes)?.execution_id;
  if (!execId) throw new Error(execRes?.message || '未能开始执行');

  let execDone = false;
  await getSse(`/executions/${execId}/stream`, (msg) => {
    const line = userCopy(msg.message || msg.step || msg.event || '');
    if (line) callbacks.onLog(stamp(line));
    steps = applyExecuteEvent(steps, msg);
    callbacks.onSteps([...steps]);
    const raw = String(msg.step || msg.event || '');
    if (['执行完成', '执行异常', 'flow_success', 'flow_failed', 'done'].includes(raw)) {
      execDone = true;
    }
  });
  if (!execDone) callbacks.onLog(stamp('执行流已结束'));

  const execDetail = unwrap(await request.get(`/executions/${execId}`));
  if (!execDetail || ['waiting', 'pending', 'running'].includes(String(execDetail.status || ''))) {
    throw new Error(execDetail?.error_message || '测试没有正常结束');
  }
  callbacks.onLog(stamp('测试完成'));
  return { requirementId: reqId, executionId: execId, result: execDetail, cases };
}
