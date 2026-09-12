import request from './request';

export type LifecycleStage = {
  key: string;
  code: string;
  name: string;
  order: number;
  categories: string[];
  pillar?: string;
  pillar_name?: string;
  asset_count?: number;
  status?: string;
  updated_at?: string | null;
};

export type LifecyclePillar = {
  key: string;
  code: string;
  name: string;
  order: number;
  summary?: string;
  stage_keys?: string[];
  asset_count?: number;
  status?: string;
  updated_at?: string | null;
  stages?: LifecycleStage[];
};

export type LifecycleAsset = {
  id: number;
  asset_code: string;
  name: string;
  asset_type: string;
  category: string;
  stage: string;
  stage_name: string;
  project_id?: number | null;
  origin: string;
  source: string;
  created_by?: number | null;
  created_at?: string | null;
  updated_at?: string | null;
  status: string;
  version: number;
  tags: string[];
  reusable: boolean;
  summary?: string;
  description?: string;
  content?: string;
  relation_count: number;
  relations?: {
    upstream: LifecycleAsset[];
    downstream: LifecycleAsset[];
    similar: LifecycleAsset[];
    defects: LifecycleAsset[];
    cases: LifecycleAsset[];
    scripts: LifecycleAsset[];
    runs: LifecycleAsset[];
  };
};

const dataOf = (res: any) => res?.data ?? res;

export async function fetchLifecycleStages(projectId?: number | null) {
  return dataOf(await request.get('/asset-center/lifecycle/stages', {
    params: { project_id: projectId || undefined },
  }));
}

export async function fetchLifecycleAssets(params: Record<string, unknown>) {
  return dataOf(await request.get('/asset-center/lifecycle/assets', { params }));
}

export async function createLifecycleAsset(payload: Record<string, unknown>) {
  return dataOf(await request.post('/asset-center/lifecycle/assets', payload));
}

export async function getLifecycleAsset(id: number) {
  return dataOf(await request.get(`/asset-center/lifecycle/assets/${id}`));
}

export async function updateLifecycleAsset(id: number, payload: Record<string, unknown>) {
  return dataOf(await request.put(`/asset-center/lifecycle/assets/${id}`, payload));
}

export async function linkLifecycleAsset(id: number, targetId: number, relationType?: string) {
  return dataOf(await request.post(`/asset-center/lifecycle/assets/${id}/link`, {
    target_id: targetId,
    relation_type: relationType,
  }));
}

export async function reuseLifecycleAssets(keyword: string, stage?: string) {
  return dataOf(await request.get('/asset-center/lifecycle/reuse', {
    params: { keyword, stage },
  }));
}

export async function syncLifecycleAssets(projectId?: number | null) {
  return dataOf(await request.post('/asset-center/lifecycle/sync', null, {
    params: { project_id: projectId || undefined },
  }));
}
