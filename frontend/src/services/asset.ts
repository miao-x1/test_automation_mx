/**
 * 测试资产服务
 *
 * 统一管理所有测试类型的资产
 */
import request from './request';

export interface TestAsset {
  id: number;
  name: string;
  asset_type: string;  // web/api/performance/android
  task_id?: number;
  input_config?: string;
  exec_config?: string;
  script_content?: string;
  script_language?: string;
  script_path?: string;
  version: number;
  status: string;
  kb_status: string;
  source: string;
  reuse_count: number;
  user_id: number;
  created_by?: number;
  created_at?: string;
  updated_at?: string;
}

export interface ProviderInfo {
  type: string;
  name: string;
  config_schema: Record<string, any>;
  default_config: Record<string, any>;
}

/**
 * 获取所有Provider
 */
export async function listProviders(): Promise<ProviderInfo[]> {
  const res: any = await request.get('/assets/v2/providers');
  if (res.code === 200) return res.data;
  throw new Error(res.message || '获取Provider失败');
}

/**
 * 获取Provider配置Schema
 */
export async function getProviderSchema(providerType: string): Promise<ProviderInfo> {
  const res: any = await request.get(`/assets/v2/providers/${providerType}/schema`);
  if (res.code === 200) return res.data;
  throw new Error(res.message || '获取Schema失败');
}

/**
 * 创建测试资产
 */
export async function createAsset(data: Partial<TestAsset>): Promise<TestAsset> {
  const res: any = await request.post('/assets/v2/', data);
  if (res.code === 200 && res.data) return res.data;
  throw new Error(res.message || '创建失败');
}

/**
 * 获取测试资产列表
 */
export async function listAssets(params?: {
  asset_type?: string;
  task_id?: number;
  status?: string;
  skip?: number;
  limit?: number;
}): Promise<{ total: number; items: TestAsset[] }> {
  const res: any = await request.get('/assets/v2/list', { params });
  if (res.code === 200) return res.data;
  throw new Error(res.message || '获取失败');
}

/**
 * 获取测试资产详情
 */
export async function getAsset(assetId: number): Promise<TestAsset> {
  const res: any = await request.get(`/assets/v2/${assetId}`);
  if (res.code === 200) return res.data;
  throw new Error(res.message || '获取失败');
}

/**
 * 更新测试资产
 */
export async function updateAsset(assetId: number, data: Partial<TestAsset>): Promise<TestAsset> {
  const res: any = await request.put(`/assets/v2/${assetId}`, data);
  if (res.code === 200) return res.data;
  throw new Error(res.message || '更新失败');
}

/**
 * 删除测试资产
 */
export async function deleteAsset(assetId: number): Promise<void> {
  const res: any = await request.delete(`/assets/v2/${assetId}`);
  if (res.code !== 200) throw new Error(res.message || '删除失败');
}

/**
 * 批量删除测试资产
 */
export async function batchDeleteAssets(ids: number[]): Promise<void> {
  const res: any = await request.post('/assets/v2/batch-delete', ids);
  if (res.code !== 200) throw new Error(res.message || '批量删除失败');
}

/**
 * 测试类型配置标签映射
 */
export const TASK_TYPE_LABELS: Record<string, string> = {
  web: 'Web UI 测试',
  api: 'API 接口测试',
  performance: '性能测试',
  android: 'Android 测试',
};

export const TASK_TYPE_COLORS: Record<string, string> = {
  web: 'blue',
  api: 'green',
  performance: 'orange',
  android: 'purple',
};
