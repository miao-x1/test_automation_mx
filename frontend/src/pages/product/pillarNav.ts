export type PillarKey = 'workspace' | 'understand' | 'design' | 'execute';

export type PillarLink = {
  title: string;
  desc: string;
  path: string;
};

export type PillarMeta = {
  key: PillarKey;
  code: string;
  name: string;
  path: string;
  summary: string;
  stageKeys: string[];
};

export const PILLARS: PillarMeta[] = [
  { key: 'workspace', code: '01', name: '工作空间', path: '/workspace', summary: '项目选择、环境、任务和整体状态', stageKeys: [] },
  { key: 'understand', code: '02', name: '项目理解', path: '/understand', summary: '系统探索、页面地图、功能与业务认知', stageKeys: ['01_analysis'] },
  { key: 'design', code: '03', name: '测试设计', path: '/design', summary: '测试计划、场景、用例、数据与脚本', stageKeys: ['02_plan', '03_design', '04_cases', '05_scripts'] },
  { key: 'execute', code: '04', name: '测试执行', path: '/execute', summary: '执行、缺陷、回归、报告与归档', stageKeys: ['06_execution', '07_defect', '08_regression', '09_report', '10_archive'] },
];

export const PILLAR_BY_STAGE: Record<string, PillarKey> = Object.fromEntries(
  PILLARS.flatMap((pillar) => pillar.stageKeys.map((stage) => [stage, pillar.key])),
) as Record<string, PillarKey>;

export const WORKSPACE_LINKS: PillarLink[] = [
  { title: '测试任务', desc: '专业测试人员的任务工作台，可只做局部工作', path: '/test-tasks' },
  { title: '测试环境', desc: '查看和配置当前可用的测试环境', path: '/system/environments' },
  { title: '测试资产总览', desc: '查看已沉淀的项目测试资产', path: '/asset/center' },
  { title: '进入项目理解', desc: '从系统探索和项目认知开始下一轮工作', path: '/understand' },
];

export const UNDERSTAND_LINKS: PillarLink[] = [
  { title: '页面理解', desc: '页面、路由、元素和页面行为', path: '/understand/pages' },
  { title: '功能理解', desc: '从页面升级到业务功能和完整调用链', path: '/understand/features' },
  { title: '接口理解', desc: '接口、调用方、后端实现和测试覆盖', path: '/understand/apis' },
  { title: '业务流程', desc: '把页面和接口串成真实用户路径', path: '/understand/flows' },
  { title: '测试关联', desc: '页面 / 功能 / API 与测试资产的覆盖关系', path: '/understand/coverage' },
];

export const DESIGN_LINKS: PillarLink[] = [
  { title: '测试计划与策略', desc: '把项目理解转成测试计划', path: '/asset/lifecycle/02_plan' },
  { title: '专业测试任务', desc: '进入某个功能任务，直接做分析、用例、脚本或报告', path: '/test-tasks' },
  { title: '场景、测试点与测试数据', desc: '测试场景、测试点和测试矩阵', path: '/asset/lifecycle/03_design' },
  { title: '测试用例', desc: '可执行的功能、接口和异常用例', path: '/asset/lifecycle/04_cases' },
  { title: '自动化测试脚本', desc: 'UI / API / Playwright 脚本', path: '/asset/lifecycle/05_scripts' },
  { title: '生成用例与脚本', desc: '基于已有项目理解增量生成测试设计', path: '/task/create' },
  { title: '测试资产中心', desc: '复用已有用例、数据和脚本', path: '/asset/center' },
  { title: '脚本库', desc: '管理和维护已有自动化脚本', path: '/asset/scripts' },
  { title: '设计工作台', desc: '用例草稿、评审与发布', path: '/asset/generate' },
];

export const EXECUTE_LINKS: PillarLink[] = [
  { title: '测试任务', desc: '进入待执行和进行中的测试任务工作台', path: '/test-tasks' },
  { title: '测试执行与记录', desc: '执行测试并查看执行记录', path: '/execution' },
  { title: '结果、截图与日志', desc: '执行结果、截图、视频和失败分析', path: '/asset/lifecycle/06_execution' },
  { title: '缺陷与复现', desc: '缺陷记录、复现和验证', path: '/asset/lifecycle/07_defect' },
  { title: '回归测试', desc: '回归执行和缺陷验证结果', path: '/asset/lifecycle/08_regression' },
  { title: '测试报告', desc: '结果统计、覆盖率和发布判断', path: '/report' },
  { title: '报告与发布风险', desc: '报告资产和发布风险评估', path: '/asset/lifecycle/09_report' },
  { title: '定时任务', desc: '已有的定时执行任务', path: '/execution/schedule' },
  { title: '性能测试', desc: '已有的性能验证任务', path: '/performance' },
];

export const HUB_LINKS: Record<Exclude<PillarKey, 'workspace'>, PillarLink[]> = {
  understand: UNDERSTAND_LINKS,
  design: DESIGN_LINKS,
  execute: EXECUTE_LINKS,
};

export function pillarOfPath(pathname: string): PillarKey {
  if (pathname.startsWith('/workspace')) return 'workspace';
  if (pathname.startsWith('/understand')) return 'understand';
  if (pathname.startsWith('/design')) return 'design';
  if (pathname.startsWith('/execute')) return 'execute';
  if (
    pathname.startsWith('/knowledge')
    || pathname.startsWith('/asset/pages')
    || pathname.startsWith('/asset/endpoints')
    || pathname.startsWith('/asset/center/analyze')
    || pathname.startsWith('/asset/lifecycle/01_analysis')
  ) return 'understand';
  if (
    pathname.startsWith('/test-tasks')
    || pathname.startsWith('/task/create')
    || pathname.startsWith('/dashboard')
    || pathname.startsWith('/asset/generate')
    || pathname.startsWith('/asset/draft')
    || pathname.startsWith('/asset/review')
    || pathname.startsWith('/asset/publish')
    || pathname.startsWith('/asset/history')
    || pathname.startsWith('/asset/scripts')
    || pathname.startsWith('/asset/center')
    || pathname.startsWith('/asset/lifecycle/02_plan')
    || pathname.startsWith('/asset/lifecycle/03_design')
    || pathname.startsWith('/asset/lifecycle/04_cases')
    || pathname.startsWith('/asset/lifecycle/05_scripts')
  ) return 'design';
  if (
    pathname.startsWith('/task')
    || pathname.startsWith('/execution')
    || pathname.startsWith('/performance')
    || pathname.startsWith('/report')
    || pathname.startsWith('/asset/lifecycle/06_')
    || pathname.startsWith('/asset/lifecycle/07_')
    || pathname.startsWith('/asset/lifecycle/08_')
    || pathname.startsWith('/asset/lifecycle/09_')
    || pathname.startsWith('/asset/lifecycle/10_')
  ) return 'execute';
  if (pathname.startsWith('/asset')) return 'design';
  return 'workspace';
}
