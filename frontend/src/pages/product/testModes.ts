export type WebModeId = 'explore' | 'functional' | 'regression' | 'full';

export type WebMode = {
  id: WebModeId;
  title: string;
  description: string;
  requirement: string;
};

export const WEB_MODES: WebMode[] = [
  {
    id: 'explore',
    title: '快速探索',
    description: '先分析页面主要功能，再验证关键路径是否可用。',
    requirement: '根据当前页面自动分析主要功能，并生成可执行的测试步骤。',
  },
  {
    id: 'functional',
    title: '功能测试',
    description: '按你描述的业务，验证登录、表单、查询等功能。',
    requirement: '重点检查按钮、输入框、表单提交、搜索、筛选、登录注册、增删改查、页面跳转和弹窗操作是否可用。',
  },
  {
    id: 'regression',
    title: '回归测试',
    description: '覆盖页面已有关键流程，适合发版前检查。',
    requirement: '按回归方式覆盖页面关键流程，验证已有功能没有被破坏。',
  },
  {
    id: 'full',
    title: '全量测试',
    description: '尽量覆盖页面主要交互，耗时更长。',
    requirement: '尽量覆盖当前页面的主要交互、跳转和异常提示，生成较完整的可执行测试。',
  },
];

export function buildWebRequirement(mode: WebMode, url: string, extra: string): string {
  const page = url.trim() ? `打开 ${url.trim()} 。` : '';
  const user = extra.trim();
  if (mode.id === 'explore' && user) {
    return `${page}${user}`;
  }
  return `${page}${user ? `${user}。` : ''}${mode.requirement}`;
}

export function buildVisualRequirement(url: string, extra: string): string {
  const page = url.trim() ? `打开 ${url.trim()} 。` : '';
  const user = extra.trim() || '根据上传的页面截图分析界面元素、布局、文案和可见性问题。';
  return `${page}${user}`;
}

export const USER_STEP_LABELS: Record<string, string> = {
  analyze_image: '识别页面元素',
  parse_requirement: '理解测试要求',
  classify_type: '确认测试内容',
  reuse_check: '查找可复用步骤',
  rag_retrieve: '参考历史测试',
  discover_relations: '分析页面关系',
  graph_reason: '整理测试路径',
  generate_cases: '生成测试步骤',
  review_cases: '检查测试步骤',
  generate_script: '准备测试执行',
};

export function friendlyStep(stepName: string, fallback = '正在处理'): string {
  return USER_STEP_LABELS[stepName] || fallback;
}
