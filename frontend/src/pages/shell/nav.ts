export type ProjectNavChild = { key: string; label: string; path: string; icon?: string };

export type ProjectNavGroup = {
  key: string;
  label: string;
  path?: string;
  icon?: string;
  children: ProjectNavChild[];
};

export type AppNavKey = 'manage' | 'workspace' | 'account';

export function appNavOfPath(pathname: string): AppNavKey {
  if (pathname === '/projects' || pathname.startsWith('/projects')) return 'manage';
  if (
    pathname.startsWith('/profile')
    || pathname.startsWith('/system')
    || pathname.startsWith('/workspace')
  ) return 'account';
  return 'workspace';
}

export const FLOW_NAV: ProjectNavChild[] = [
  { key: 'understand', label: '项目理解', path: '/understand', icon: '◎' },
  { key: 'requirements', label: '需求分析', path: '/understand/requirements', icon: '▣' },
  { key: 'design', label: '测试设计', path: '/design', icon: '✎' },
  { key: 'tasks', label: '测试用例', path: '/test-tasks', icon: '☰' },
  { key: 'prepare', label: '测试准备', path: '/prepare', icon: '▦' },
  { key: 'execute', label: '测试执行', path: '/execute', icon: '▷' },
  { key: 'defects', label: '缺陷管理', path: '/defects', icon: '⚠' },
  { key: 'verify', label: '缺陷验证', path: '/verify', icon: '✓' },
  { key: 'regression', label: '回归测试', path: '/regression', icon: '↺' },
  { key: 'reports', label: '测试报告', path: '/report', icon: '▤' },
];

export const ASSET_NAV: ProjectNavChild[] = [
  { key: 'files', label: '文件', path: '/understand/code', icon: '▢' },
  { key: 'apis', label: '接口', path: '/understand/apis', icon: '⌁' },
  { key: 'data', label: '测试数据', path: '/design/data', icon: '▦' },
];

export const PROJECT_NAV: ProjectNavGroup[] = [
  { key: 'flow', label: '项目工作台', children: FLOW_NAV },
  { key: 'assets', label: '资产', children: ASSET_NAV },
];

export function navGroupOfPath(pathname: string): string {
  if (pathname.startsWith('/understand/requirements')) return 'requirements';
  if (pathname.startsWith('/understand/code')) return 'files';
  if (pathname.startsWith('/understand/apis')) return 'apis';
  if (pathname.startsWith('/understand') || pathname.startsWith('/workbench') || pathname.startsWith('/knowledge')) return 'understand';
  if (pathname.startsWith('/design/data')) return 'data';
  if (pathname.startsWith('/design')) return 'design';
  if (pathname.startsWith('/test-tasks') || pathname.startsWith('/task')) return 'tasks';
  if (pathname.startsWith('/prepare')) return 'prepare';
  if (pathname.startsWith('/defects')) return 'defects';
  if (pathname.startsWith('/verify')) return 'verify';
  if (pathname.startsWith('/regression')) return 'regression';
  if (pathname.startsWith('/report')) return 'reports';
  if (pathname.startsWith('/execute') || pathname.startsWith('/execution') || pathname.startsWith('/performance')) return 'execute';
  if (pathname.startsWith('/asset/endpoints')) return 'apis';
  if (pathname.startsWith('/asset')) return 'files';
  return 'understand';
}

export function navChildOfPath(pathname: string): string {
  if (pathname.startsWith('/understand/requirements')) return 'requirements';
  if (pathname === '/understand' || pathname === '/understand/') return 'overview';
  if (pathname.startsWith('/understand/pages')) return 'tech';
  if (pathname.startsWith('/understand/features')) return 'features';
  if (pathname.startsWith('/understand/modules')) return 'architecture';
  if (pathname.startsWith('/understand/apis')) return 'apis';
  if (pathname.startsWith('/understand/code')) return 'tech';
  if (pathname.startsWith('/understand/flows')) return 'business';
  if (pathname.startsWith('/understand/coverage')) return 'overview';
  if (pathname.startsWith('/design/')) {
    const section = pathname.replace('/design/', '').split('/')[0];
    if (section === 'cases') return 'objects';
    return section || 'overview';
  }
  if (pathname.startsWith('/design')) return 'overview';
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
