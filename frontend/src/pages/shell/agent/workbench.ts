import type { AgentReply, CodeHit } from '@/services/projectExplorer';

export type AgentMode = 'agent' | 'chat';
export type PanelStatus = 'idle' | 'thinking' | 'running' | 'waiting' | 'completed' | 'error' | 'cancelled';

export type ContextChip = {
  id: string;
  kind: 'context' | 'file' | 'asset' | 'api' | 'page' | 'result';
  label: string;
  workspace?: 'understand' | 'design' | 'execute';
};

export type AgentStep = {
  key: string;
  label: string;
  status: 'done' | 'run' | 'bad';
  detail?: { title: string; lines: string[] }[];
};

export type ResultCard = {
  title: string;
  stats: { label: string; value: string | number }[];
  buttons: { label: string; path: string }[];
};

export type Turn = {
  role: 'user' | 'assistant' | 'confirm';
  text: string;
  steps?: AgentStep[];
  cards?: ResultCard[];
  pendingQuestion?: string;
  failed?: boolean;
};

export const CONTEXT_OPTIONS: Array<{ key: string; label: string; workspace?: ContextChip['workspace'] }> = [
  { key: 'project', label: '当前项目' },
  { key: 'understand', label: '项目理解', workspace: 'understand' },
  { key: 'design', label: '测试设计', workspace: 'design' },
  { key: 'tasks', label: '测试任务', workspace: 'design' },
  { key: 'execute', label: '测试执行', workspace: 'execute' },
  { key: 'cases', label: '测试用例', workspace: 'design' },
  { key: 'results', label: '测试结果', workspace: 'execute' },
  { key: 'api', label: 'API', workspace: 'understand' },
  { key: 'page', label: '页面', workspace: 'understand' },
  { key: 'assets', label: '测试资产' },
];

export const SKILLS: Array<{ key: string; label: string; draft: string; write?: boolean }> = [
  { key: 'analyze', label: '测试分析', draft: '分析当前项目的测试风险' },
  { key: 'design', label: '测试设计', draft: '帮我设计当前项目的测试', write: true },
  { key: 'cases', label: '测试用例生成', draft: '根据当前项目生成测试用例', write: true },
  { key: 'defect', label: '缺陷分析', draft: '分析失败原因' },
  { key: 'auto', label: '自动化脚本生成', draft: '把测试用例转成自动化脚本', write: true },
  { key: 'report', label: '测试报告', draft: '生成测试报告', write: true },
  { key: 'code', label: '代码分析', draft: '最核心的代码文件是哪个？' },
];

const WRITE_HINTS = [
  '全面测试', '完整测试', '生成用例', '生成测试用例', '写用例', '出用例',
  '创建测试任务', '新建测试任务', '执行测试', '跑一下', '跑这些用例',
  '生成报告', '生成测试报告', '提缺陷', '生成缺陷', '生成bug',
  '转自动化', '生成脚本', '补充异常', '补充边界',
];

const ACTION_LABEL: Record<string, string> = {
  analyze_requirement: '分析需求',
  create_test_design: '写入测试设计',
  generate_cases: '生成测试用例',
  generated_cases: '生成测试用例',
  supplement_exception: '补充异常场景',
  supplement_boundary: '补充边界场景',
  check_coverage: '检查覆盖率',
  optimize_cases: '优化用例',
  to_automation: '转自动化脚本',
  full_test: '完成一站式测试',
  create_task: '创建测试任务',
  list_executions: '查询执行记录',
  create_bug: '写入缺陷',
  generate_report: '生成测试报告',
};

export function workspaceOf(pathname: string): 'understand' | 'design' | 'execute' {
  if (pathname.startsWith('/execute') || pathname.startsWith('/execution') || pathname.startsWith('/report')) return 'execute';
  if (pathname.startsWith('/design') || pathname.startsWith('/test-tasks') || pathname.startsWith('/task')) return 'design';
  return 'understand';
}

export function needsWriteConfirm(text: string, mode: AgentMode) {
  if (mode !== 'agent') return false;
  return WRITE_HINTS.some((token) => text.includes(token));
}

export function workspaceFromChips(chips: ContextChip[], fallback: 'understand' | 'design' | 'execute') {
  const hit = [...chips].reverse().find((item) => item.workspace);
  return hit?.workspace || fallback;
}

export function composeQuestion(text: string, chips: ContextChip[]) {
  const tags = chips.map((item) => `@${item.label}`).filter(Boolean);
  if (!tags.length) return text;
  return `${tags.join(' ')}\n${text}`;
}

export function statusLabel(status: PanelStatus) {
  if (status === 'thinking') return '正在分析…';
  if (status === 'running') return '正在执行…';
  if (status === 'waiting') return '等待你的确认';
  if (status === 'completed') return '已完成';
  if (status === 'error') return '执行失败';
  if (status === 'cancelled') return '已停止';
  return '在线';
}

export function stepsFromReply(reply: AgentReply): AgentStep[] {
  const steps: AgentStep[] = [];
  if (reply.path) {
    steps.push({ key: 'path', label: reply.path, status: 'done' });
  }
  if (reply.memory_used?.length) {
    steps.push({
      key: 'memory',
      label: '读取项目记忆',
      status: 'done',
      detail: [{
        title: '记忆',
        lines: reply.memory_used.map((item) => [item.kind, item.title].filter(Boolean).join(' ')).filter(Boolean),
      }],
    });
  }
  if (reply.locations?.length) {
    steps.push({
      key: 'code',
      label: '搜索相关代码',
      status: 'done',
      detail: [{
        title: '结果',
        lines: reply.locations.slice(0, 8).map((item) => formatHit(item)),
      }],
    });
  }
  if (reply.brain?.cards?.length || reply.brain?.playbooks?.length) {
    const lines = [
      ...(reply.brain?.cards || []).map((item) => item.title || '').filter(Boolean),
      ...(reply.brain?.playbooks || []),
    ];
    steps.push({
      key: 'brain',
      label: '参考测试知识',
      status: 'done',
      detail: lines.length ? [{ title: '知识', lines }] : undefined,
    });
  }
  (reply.actions || []).forEach((action, index) => {
    const label = ACTION_LABEL[action?.type] || action?.type;
    if (!label) return;
    const lines: string[] = [];
    if (action.test_task_id) lines.push(`测试任务 #${action.test_task_id}`);
    if (Array.isArray(action.cases)) lines.push(`用例 ${action.cases.length} 条`);
    if (action.coverage?.score != null) lines.push(`覆盖率 ${action.coverage.score}%`);
    if (Array.isArray(action.items)) lines.push(`执行记录 ${action.items.length} 条`);
    steps.push({
      key: `action-${index}`,
      label,
      status: 'done',
      detail: lines.length ? [{ title: '结果', lines }] : undefined,
    });
  });
  return steps;
}

export function cardsFromReply(reply: AgentReply): ResultCard[] {
  const cards: ResultCard[] = [];
  const actions = reply.actions || [];
  const taskId = reply.test_task_id || actions.find((item) => item?.test_task_id)?.test_task_id;
  const caseCount = actions.reduce((sum, item) => sum + (Array.isArray(item?.cases) ? item.cases.length : 0), 0);
  const coverage = actions.find((item) => item?.coverage)?.coverage;
  const executions = actions.find((item) => item?.type === 'list_executions');

  if (actions.some((item) => ['generate_cases', 'generated_cases', 'supplement_exception', 'supplement_boundary'].includes(item?.type))) {
    cards.push({
      title: '测试用例已生成',
      stats: [{ label: '用例', value: caseCount }],
      buttons: [
        ...(taskId ? [{ label: '查看测试任务', path: `/test-tasks/${taskId}` }] : []),
        { label: '查看测试设计', path: '/design/cases' },
      ],
    });
  }
  if (actions.some((item) => item?.type === 'create_test_design' || item?.type === 'analyze_requirement')) {
    cards.push({
      title: '测试设计完成',
      stats: [
        ...(caseCount ? [{ label: '用例', value: caseCount }] : []),
        ...(taskId ? [{ label: '任务', value: `#${taskId}` }] : []),
      ],
      buttons: [
        { label: '查看测试设计', path: '/design' },
        ...(taskId ? [{ label: '打开测试任务', path: `/test-tasks/${taskId}` }] : [{ label: '创建测试任务', path: '/test-tasks' }]),
      ],
    });
  }
  if (actions.some((item) => item?.type === 'full_test' || item?.type === 'create_task')) {
    cards.push({
      title: actions.some((item) => item?.type === 'full_test') ? '一站式测试完成' : '测试任务已创建',
      stats: [
        ...(taskId ? [{ label: '任务', value: `#${taskId}` }] : []),
        ...(caseCount ? [{ label: '用例', value: caseCount }] : []),
        ...(coverage?.score != null ? [{ label: '覆盖率', value: `${coverage.score}%` }] : []),
      ],
      buttons: [
        ...(taskId ? [{ label: '打开测试任务', path: `/test-tasks/${taskId}` }] : []),
        { label: '测试任务列表', path: '/test-tasks' },
      ],
    });
  }
  if (coverage && !cards.length) {
    cards.push({
      title: '覆盖检查完成',
      stats: [{ label: '覆盖率', value: `${coverage.score ?? '-'}%` }],
      buttons: [{ label: '查看测试关联', path: '/understand/coverage' }],
    });
  }
  if (executions) {
    const items = executions.items || [];
    cards.push({
      title: '执行记录',
      stats: [{ label: '记录', value: items.length }],
      buttons: [
        { label: '查看执行结果', path: '/execute' },
        { label: '分析失败原因', path: '/execute' },
      ],
    });
  }
  if (actions.some((item) => item?.type === 'to_automation')) {
    cards.push({
      title: '自动化草稿已写入',
      stats: [],
      buttons: [{ label: '查看测试设计', path: '/design' }],
    });
  }
  if (actions.some((item) => item?.type === 'generate_report')) {
    cards.push({
      title: '测试报告已写入',
      stats: [],
      buttons: [{ label: '查看报告', path: '/report' }],
    });
  }
  if (actions.some((item) => item?.type === 'create_bug')) {
    cards.push({
      title: '缺陷已写入',
      stats: [],
      buttons: [
        ...(taskId ? [{ label: '打开测试任务', path: `/test-tasks/${taskId}` }] : []),
        { label: '查看测试任务', path: '/test-tasks' },
      ],
    });
  }
  if (!cards.length && reply.locations?.length) {
    const first = reply.locations[0];
    cards.push({
      title: '代码定位',
      stats: [{ label: '命中', value: reply.locations.length }],
      buttons: first?.path ? [{ label: '查看代码', path: `/understand/code?path=${encodeURIComponent(first.path)}` }] : [],
    });
  }
  return cards;
}

function formatHit(item: CodeHit) {
  const loc = `${item.path || ''}:${item.line_start || 1}`;
  return [item.name, loc].filter(Boolean).join(' · ');
}
