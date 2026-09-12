export type ProjectNavChild = { key: string; label: string; path: string };

export type ProjectNavGroup = {
  key: string;
  label: string;
  path: string;
  icon?: string;
  children?: ProjectNavChild[];
};

export type AppNavKey = 'manage' | 'workspace' | 'knowledge';

export function appNavOfPath(pathname: string): AppNavKey {
  if (pathname.startsWith('/knowledge')) return 'knowledge';
  if (pathname === '/projects' || pathname.startsWith('/projects')) return 'manage';
  return 'workspace';
}

export const PROJECT_NAV: ProjectNavGroup[] = [
  {
    key: 'understand',
    label: '项目理解',
    path: '/understand',
    children: [
      { key: 'overview', label: '概览', path: '/understand' },
      { key: 'pages', label: '页面', path: '/understand/pages' },
      { key: 'features', label: '功能', path: '/understand/features' },
      { key: 'modules', label: '模块', path: '/understand/modules' },
      { key: 'apis', label: '接口', path: '/understand/apis' },
      { key: 'code', label: '代码', path: '/understand/code' },
      { key: 'flows', label: '业务流程', path: '/understand/flows' },
    ],
  },
  {
    key: 'design',
    label: '测试设计',
    path: '/design',
    children: [
      { key: 'scenarios', label: '测试场景', path: '/design/scenarios' },
      { key: 'cases', label: '测试用例', path: '/design/cases' },
      { key: 'data', label: '测试数据', path: '/design/data' },
    ],
  },
  {
    key: 'tasks',
    label: '测试任务',
    path: '/test-tasks',
    children: [{ key: 'list', label: '任务列表', path: '/test-tasks' }],
  },
  {
    key: 'execute',
    label: '测试执行',
    path: '/execute',
    children: [
      { key: 'runs', label: '执行记录', path: '/execute' },
      { key: 'reports', label: '测试报告', path: '/report' },
    ],
  },
];

export function navGroupOfPath(pathname: string): string {
  if (pathname.startsWith('/understand')) return 'understand';
  if (pathname.startsWith('/design')) return 'design';
  if (pathname.startsWith('/test-tasks') || pathname.startsWith('/task')) return 'tasks';
  if (
    pathname.startsWith('/execute')
    || pathname.startsWith('/execution')
    || pathname.startsWith('/report')
    || pathname.startsWith('/performance')
  ) return 'execute';
  if (pathname.startsWith('/workbench')) return 'workbench';
  return 'workbench';
}

export function navChildOfPath(pathname: string): string {
  if (pathname === '/understand' || pathname === '/understand/') return 'overview';
  if (pathname.startsWith('/understand/pages')) return 'pages';
  if (pathname.startsWith('/understand/features')) return 'features';
  if (pathname.startsWith('/understand/modules')) return 'modules';
  if (pathname.startsWith('/understand/apis')) return 'apis';
  if (pathname.startsWith('/understand/code')) return 'code';
  if (pathname.startsWith('/understand/flows')) return 'flows';
  if (pathname.startsWith('/design/data')) return 'data';
  if (pathname.startsWith('/design/cases')) return 'cases';
  if (pathname.startsWith('/design')) return 'scenarios';
  if (pathname.startsWith('/test-tasks')) return 'list';
  if (pathname.startsWith('/report')) return 'reports';
  if (pathname.startsWith('/execute') || pathname.startsWith('/execution')) return 'runs';
  return '';
}

export function formatAgo(value?: string | null) {
  if (!value) return '尚未更新';
  const time = new Date(value).getTime();
  if (!Number.isFinite(time)) return value;
  const delta = Date.now() - time;
  if (delta < 60_000) return '刚刚';
  if (delta < 3_600_000) return `${Math.floor(delta / 60_000)}分钟前`;
  if (delta < 86_400_000) return `${Math.floor(delta / 3_600_000)}小时前`;
  if (delta < 172_800_000) return '昨天';
  return value.replace('T', ' ').slice(0, 16);
}
