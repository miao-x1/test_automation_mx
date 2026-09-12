export const UNDERSTAND_NAV = [
  { key: '', label: '概览', icon: '▣' },
  { key: 'pages', label: '页面', icon: '▤' },
  { key: 'features', label: '功能', icon: '◇' },
  { key: 'modules', label: '模块', icon: '▦' },
  { key: 'apis', label: '接口', icon: '⇄' },
  { key: 'code', label: '代码', icon: '</>' },
  { key: 'flows', label: '业务流程', icon: '↗' },
  { key: 'coverage', label: '测试关联', icon: '✓' },
  { key: 'agent', label: '项目助手', icon: '✦' },
];

export const STATUS_TEXT: Record<string, string> = {
  ready: '已分析',
  partial: '部分完成',
  empty: '未分析',
  analyzing: '分析中',
};

export const SECTION_LABEL: Record<string, string> = {
  '': '概览',
  pages: '页面',
  features: '功能',
  modules: '模块',
  apis: '接口',
  code: '代码',
  flows: '业务流程',
  coverage: '测试关联',
  agent: '项目助手',
};

export function matchKeyword(item: any, keyword: string) {
  if (!keyword.trim()) return true;
  const blob = JSON.stringify(item).toLowerCase();
  return keyword.trim().toLowerCase().split(/\s+/).every((word) => blob.includes(word));
}

export function searchUnderstanding(data: any, keyword: string) {
  const q = keyword.trim().toLowerCase();
  if (!q || !data) return [];
  const hits: Array<{ kind: string; title: string; desc: string; to: string }> = [];
  const push = (kind: string, title: string, desc: string, to: string) => {
    if (`${title} ${desc}`.toLowerCase().includes(q)) hits.push({ kind, title, desc, to });
  };
  (data.features || []).forEach((item: any) => push('功能', item.name, item.module || '', `/understand/features?id=${encodeURIComponent(item.id)}`));
  (data.pages || []).forEach((item: any) => push('页面', item.name, item.route || '', `/understand/pages?id=${encodeURIComponent(item.id)}`));
  (data.apis || []).forEach((item: any) => push('API', item.name, item.feature || '', `/understand/apis?id=${encodeURIComponent(item.id)}`));
  (data.files || []).forEach((item: any) => push('文件', item.path, item.feature || '', `/understand/code?path=${encodeURIComponent(item.path)}`));
  (data.modules || []).forEach((item: any) => push('模块', item.name, item.duty || '', `/understand/modules?id=${encodeURIComponent(item.id)}`));
  (data.features || []).forEach((item: any) => (item.cases || []).forEach((row: any) => {
    push('测试', row.name || row.code, item.name, '/understand/coverage');
  }));
  return hits.slice(0, 12);
}

export function buildFileTree(files: Array<{ path: string }>) {
  const root: any = { name: '', children: {}, files: [] };
  files.forEach((file) => {
    const parts = (file.path || '').split('/').filter(Boolean);
    let node = root;
    parts.forEach((part, index) => {
      if (index === parts.length - 1) {
        node.files.push({ name: part, path: file.path });
        return;
      }
      node.children[part] = node.children[part] || { name: part, children: {}, files: [] };
      node = node.children[part];
    });
  });
  return root;
}

export function coverageTone(rate: number, missing = 0) {
  if (rate >= 80) return 'ok';
  if (rate > 0 || missing > 0) return 'warn';
  return 'empty';
}

export function groupStack(project: any) {
  const raw = [...(project?.stack || [])];
  const groups: Record<string, string[]> = { Frontend: [], Backend: [], Data: [], AI: [] };
  raw.forEach((item) => {
    const key = item.toLowerCase();
    if (['react', 'vue', 'typescript/javascript', 'typescript', 'javascript', 'antd', 'ant design'].some((x) => key.includes(x))) groups.Frontend.push(item);
    else if (['fastapi', 'python', 'django', 'sqlalchemy', 'go', 'java'].some((x) => key.includes(x))) groups.Backend.push(item);
    else if (['mysql', 'redis', 'postgres', 'milvus', 'neo4j', 'sql'].some((x) => key.includes(x))) groups.Data.push(item);
    else if (['ai', 'llm', 'agent', 'deepseek', 'qwen'].some((x) => key.includes(x))) groups.AI.push(item);
    else groups.Backend.push(item);
  });
  if (project?.frontend && !groups.Frontend.includes(project.frontend)) groups.Frontend.push(project.frontend);
  if (project?.backend && !groups.Backend.includes(project.backend)) groups.Backend.push(project.backend);
  if (project?.database && project.database !== '-') groups.Data.push(project.database);
  return Object.entries(groups).filter(([, items]) => items.length);
}
