/**
 * 测试用例中心 - 共享配置（Case First）
 */

export const assetTypeConfig: Record<string, { color: string; label: string }> = {
  api: { color: 'blue', label: 'API测试' },
  web: { color: 'green', label: 'Web测试' },
  android: { color: 'orange', label: 'Android测试' },
  manual: { color: 'purple', label: '通用用例' },
};

export const statusConfig: Record<string, { color: string; label: string; badge: 'default' | 'processing' | 'success' | 'warning' | 'error' }> = {
  draft: { color: 'default', label: '草稿', badge: 'default' },
  reviewed: { color: 'purple', label: '已审查', badge: 'processing' },
  published: { color: 'success', label: '已发布', badge: 'success' },
  executed: { color: 'green', label: '已执行', badge: 'success' },
  failed: { color: 'error', label: '失败', badge: 'error' },
};

export const sourceConfig: Record<string, { color: string; label: string }> = {
  ai: { color: 'purple', label: 'AI生成' },
  manual: { color: 'blue', label: '手动创建' },
  swagger: { color: 'cyan', label: 'Swagger' },
  import: { color: 'geekblue', label: '导入' },
  reused: { color: 'gold', label: '复用' },
};

export interface AssetItem {
  id: number;
  title: string;
  asset_type: string;
  status: string;
  source_type?: string;
  source?: string;
  priority: string;
  tags?: string | string[];
  session_id?: number;
  published: boolean;
  executable: boolean;
  version: number;
  has_draft?: boolean;
  has_published?: boolean;
  created_at?: string;
  updated_at?: string;
}

/**
 * 直接执行单条用例（统一执行入口）
 *
 * 使用 POST /execution/run/asset（Execution First）
 * 旧接口 /assets/v2/execution/run/case 已废弃
 */
export async function runCase(caseId: number, env: string = 'test', baseUrl: string = 'http://localhost:8080'): Promise<{ execution_id: number; status: string }> {
  const res = await fetch('/api/execution/run/asset', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ asset_id: caseId, env, base_url: baseUrl, async_exec: true }),
  });
  const data = await res.json();
  const d = data.data || data;
  if (d.execution_id) {
    return { execution_id: d.execution_id, status: d.status || 'queued' };
  }
  throw new Error(d.detail || '执行失败');
}

/**
 * 执行套件（统一执行入口）
 *
 * 使用 POST /execution/run/suite（Execution First）
 * 旧接口 /assets/v2/execution/run/suite 已废弃
 */
export async function runSuite(suiteId: number, env: string = 'test'): Promise<{ execution_id: number; suite_id: number; case_count: number; status: string }> {
  const res = await fetch('/api/execution/run/suite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ suite_id: suiteId, env }),
  });
  const data = await res.json();
  const d = data.data || data;
  if (d.execution_id) {
    return { execution_id: d.execution_id, suite_id: d.suite_id || suiteId, case_count: d.case_count || 0, status: d.status || 'queued' };
  }
  throw new Error(d.detail || '执行失败');
}
