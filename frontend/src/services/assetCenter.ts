/**
 * 测试资产中心 - 前端服务层
 *
 * 对应后端路由前缀:
 *   /api/asset-center/assets        - 资产索引 CRUD + 状态 + 版本 + 统计
 *   /api/asset-center/relations     - 资产关系 CRUD + 影响面分析
 *   /api/asset-center/search        - 三源融合搜索 + 反查
 *   /api/asset-center/agents        - Agent 业务流(搜索→复用→优化)
 *
 * 由于 request.ts 中 baseURL 已配置为 '/api', 本文件路径前缀为 '/asset-center/...'
 *
 * 覆盖接口:
 *   1. 资产 CRUD    - createAsset / listAssets / getAsset / updateAsset / deleteAsset
 *   2. 状态管理      - publishAsset / changeAssetStatus / markAssetUsed
 *   3. 版本管理      - listAssetVersions / getAssetVersion / rollbackAsset
 *   4. 统计         - getAssetStats
 *   5. 关系 CRUD    - createRelation / listRelations / getRelation / updateRelation / deleteRelation
 *   6. 影响面分析    - analyzeImpact
 *   7. Neo4j 同步   - syncPendingToNeo4j
 *   8. 搜索         - searchAssets / findByRef / findByCodes
 *   9. Agent 业务流  - analyzeRequirement / searchAssetsAgent / evaluateReuse / optimizePlan / agentHealthCheck
 */
import request from './request';

// ============================================================
// 类型定义 (与后端 schemas/asset_registry.py 对齐)
// ============================================================

// ---- 枚举 ----

export type AssetType =
  | 'api_endpoint'
  | 'ui_element'
  | 'test_case'
  | 'test_asset'
  | 'script'
  | 'test_data'
  | 'test_report'
  | 'requirement';

export type AssetStatus = 'draft' | 'active' | 'deprecated' | 'archived';

export type AssetSource =
  | 'manual'
  | 'swagger'
  | 'postman'
  | 'har'
  | 'import'
  | 'ai';

export type RelationType =
  | 'DEPENDS_ON'
  | 'USED_BY'
  | 'IMPLEMENTS'
  | 'COVERS'
  | 'DERIVED_FROM'
  | 'VERIFIES'
  | 'CONTAINS'
  | 'CONFLICTS_WITH';

export type ChangeType = 'create' | 'update' | 'rollback' | 'status_change';

// ---- 资产引用 ----

export interface AssetRefItem {
  ref_type: string;
  ref_id: number;
  asset_id?: number | null;
  asset_code?: string | null;
  name?: string | null;
}

// ---- 资产详情 ----

export interface Asset {
  id: number;
  asset_code: string;
  name: string;
  asset_type: AssetType | string;
  ref_type: string;
  ref_id: number;
  summary?: string | null;
  description?: string | null;
  module?: string | null;
  tags: string[];
  status: AssetStatus | string;
  source: AssetSource | string;
  version: number;
  quality_score: number;
  reuse_count: number;
  last_used_at?: string | null;
  extra_metadata: Record<string, unknown>;
  user_id?: number | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
}

// 资产列表项 (精简字段)
export interface AssetListItem {
  id: number;
  asset_code: string;
  name: string;
  asset_type: AssetType | string;
  ref_type: string;
  ref_id: number;
  summary?: string | null;
  module?: string | null;
  status: AssetStatus | string;
  source: AssetSource | string;
  version: number;
  quality_score: number;
  reuse_count: number;
  tags: string[];
  last_used_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface AssetListResponse {
  total: number;
  page: number;
  page_size: number;
  items: AssetListItem[];
}

// ---- 资产版本 ----

export interface AssetVersionItem {
  id: number;
  asset_id: number;
  version: number;
  change_log?: string | null;
  change_type: ChangeType | string;
  is_current: boolean;
  published_by?: number | null;
  created_by?: number | null;
  created_at: string;
}

export interface AssetVersionListResponse {
  total: number;
  page: number;
  page_size: number;
  items: AssetVersionItem[];
}

export interface AssetVersionDetail extends AssetVersionItem {
  snapshot: Record<string, unknown>;
  diff_summary?: Record<string, unknown> | null;
}

// ---- 资产关系 ----

export interface AssetRelation {
  id: number;
  source_id: number;
  target_id: number;
  relation_type: RelationType | string;
  weight: number;
  metadata: Record<string, unknown>;
  neo4j_synced: boolean;
  neo4j_synced_at?: string | null;
  source_asset?: AssetRefItem | null;
  target_asset?: AssetRefItem | null;
  created_at: string;
  updated_at: string;
}

export interface AssetRelationListResponse {
  total: number;
  page: number;
  page_size: number;
  items: AssetRelation[];
}

// ---- 统计 ----

export interface AssetStats {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_module: Record<string, number>;
  by_source: Record<string, number>;
  avg_quality_score: number;
  total_relations: number;
  pending_neo4j_sync: number;
}

// ---- 搜索 ----

export interface MatchReason {
  source: 'mysql' | 'milvus' | 'neo4j' | string;
  field?: string | null;
  score: number;
  detail?: string | null;
}

export interface SearchHitItem {
  asset_id: number;
  asset_code: string;
  name: string;
  asset_type: string;
  status: string;
  module?: string | null;
  summary?: string | null;
  tags: string[];
  quality_score: number;
  reuse_count: number;
  mysql_score: number;
  vector_score?: number | null;
  relation_score?: number | null;
  final_score: number;
  match_reasons: MatchReason[];
}

export interface SearchResponse {
  query: string;
  total: number;
  hits: SearchHitItem[];
  elapsed_ms: number;
  sources_used: string[];
}

// ---- Agent 业务流输出 ----

export interface ReuseSuggestionItem {
  asset_id: number;
  asset_code: string;
  name: string;
  asset_type: string;
  reuse_score: number;
  coverage: number;
  field_match: number;
  quality: number;
  recency: number;
  history: number;
  suggestion: 'reuse' | 'adapt' | 'skip' | string;
  reason: string;
}

export interface ReuseDecision {
  requirement: string;
  can_reuse: boolean;
  suggestions: ReuseSuggestionItem[];
  missing_assets: string[];
  summary: string;
  degraded?: boolean;
}

export interface OptimizedPlan {
  reuse_assets: number[];
  adapt_assets: number[];
  new_assets: Array<Record<string, unknown>>;
  execution_order: string[];
  quality_score: number;
  summary: string;
}

export interface AnalyzeResult {
  status: 'success' | 'error' | string;
  requirement: string;
  search_results?: SearchHitItem[] | Record<string, unknown>[];
  reuse_decision?: ReuseDecision;
  optimized_plan?: OptimizedPlan | null;
  elapsed_ms: number;
  steps: Array<{
    step: string;
    status: string;
    duration_ms: number;
    [key: string]: unknown;
  }>;
  error?: string;
}

export interface AgentHealthStatus {
  status: string;
  agents: Array<{
    name: string;
    type: string;
    enabled: boolean;
  }>;
  orchestrator: string;
  flow: string;
}

// ---- 创建/更新请求 ----

export interface AssetCreateInput {
  asset_code?: string;
  name: string;
  asset_type: AssetType | string;
  ref_type: string;
  ref_id?: number;
  summary?: string;
  description?: string;
  module?: string;
  tags?: string[];
  source?: AssetSource | string;
  extra_metadata?: Record<string, unknown>;
}

export type AssetUpdateInput = {
  name?: string;
  summary?: string;
  description?: string;
  module?: string;
  tags?: string[];
  quality_score?: number;
  extra_metadata?: Record<string, unknown>;
};

export interface AssetListParams {
  keyword?: string;
  asset_type?: string;
  status?: string;
  module?: string;
  source?: string;
  tags?: string[];
  ref_type?: string;
  min_quality?: number;
  page?: number;
  page_size?: number;
}

export interface PublishInput {
  change_log?: string;
  change_type?: ChangeType | string;
}

export interface StateTransitionInput {
  target_status: AssetStatus | string;
  reason?: string;
}

export interface RelationCreateInput {
  source_id: number;
  target_id: number;
  relation_type: RelationType | string;
  weight?: number;
  metadata?: Record<string, unknown>;
}

export interface RelationUpdateInput {
  weight?: number;
  metadata?: Record<string, unknown>;
}

export interface RelationListParams {
  asset_id?: number;
  direction?: 'outgoing' | 'incoming';
  relation_type?: string;
  target_type?: string;
  page?: number;
  page_size?: number;
}

export interface SearchInput {
  query: string;
  asset_types?: string[];
  module?: string;
  tags?: string[];
  include_inactive?: boolean;
  limit?: number;
  use_vector?: boolean;
  use_relation?: boolean;
}

export interface AnalyzeInput {
  requirement: string;
  asset_types?: string[];
  module?: string;
  tags?: string[];
  limit?: number;
  use_vector?: boolean;
  use_relation?: boolean;
}

// ---- 通用操作结果 ----

export interface OperationResult {
  success: boolean;
  asset_id?: number;
  message: string;
  previous_status?: string;
  current_status?: string;
  new_version?: number;
}

export interface RelationOperationResult {
  success: boolean;
  relation_id: number;
  message: string;
  neo4j_synced: boolean;
}

export interface ImpactResult {
  root_asset: AssetRefItem;
  impacted: Array<{
    asset: AssetRefItem;
    path: Array<{
      relation_id: number;
      relation_type: string;
      direction: string;
    }>;
    depth: number;
  }>;
  total: number;
}

// ============================================================
// API 调用
// ============================================================

// ---- 资产 CRUD ----

export async function createAsset(data: AssetCreateInput): Promise<Asset> {
  return request.post('/asset-center/assets', data);
}

export async function listAssets(
  params: AssetListParams = {},
): Promise<AssetListResponse> {
  const query: Record<string, unknown> = {
    page: params.page ?? 1,
    page_size: params.page_size ?? 20,
  };
  if (params.keyword) query.keyword = params.keyword;
  if (params.asset_type) query.asset_type = params.asset_type;
  if (params.status) query.status = params.status;
  if (params.module) query.module = params.module;
  if (params.source) query.source = params.source;
  if (params.ref_type) query.ref_type = params.ref_type;
  if (typeof params.min_quality === 'number') query.min_quality = params.min_quality;
  if (params.tags && params.tags.length) query.tags = params.tags.join(',');
  return request.get('/asset-center/assets/list', { params: query });
}

export async function getAsset(id: number): Promise<Asset> {
  return request.get(`/asset-center/assets/${id}`);
}

export async function updateAsset(
  id: number,
  data: AssetUpdateInput,
): Promise<Asset> {
  return request.put(`/asset-center/assets/${id}`, data);
}

export async function deleteAsset(id: number): Promise<OperationResult> {
  return request.delete(`/asset-center/assets/${id}`);
}

// ---- 状态管理 ----

export async function publishAsset(
  id: number,
  input: PublishInput = {},
): Promise<Asset> {
  return request.post(`/asset-center/assets/${id}/publish`, {
    change_log: input.change_log ?? '',
    change_type: input.change_type ?? 'update',
  });
}

export async function changeAssetStatus(
  id: number,
  input: StateTransitionInput,
): Promise<Asset> {
  return request.put(`/asset-center/assets/${id}/status`, input);
}

export async function markAssetUsed(id: number): Promise<Asset> {
  return request.post(`/asset-center/assets/${id}/mark-used`);
}

// ---- 版本管理 ----

export async function listAssetVersions(
  id: number,
  params: { page?: number; page_size?: number } = {},
): Promise<AssetVersionListResponse> {
  return request.get(`/asset-center/assets/${id}/versions`, {
    params: {
      page: params.page ?? 1,
      page_size: params.page_size ?? 50,
    },
  });
}

export async function getAssetVersion(
  id: number,
  version: number,
): Promise<AssetVersionDetail> {
  return request.get(`/asset-center/assets/${id}/versions/${version}`);
}

export async function rollbackAsset(
  id: number,
  version: number,
): Promise<Asset> {
  return request.post(`/asset-center/assets/${id}/rollback/${version}`);
}

// ---- 统计 ----

export async function getAssetStats(): Promise<AssetStats> {
  return request.get('/asset-center/assets/stats');
}

// ---- 关系 CRUD ----

export async function createRelation(
  data: RelationCreateInput,
): Promise<AssetRelation> {
  return request.post('/asset-center/relations', data);
}

export async function listRelations(
  params: RelationListParams = {},
): Promise<AssetRelationListResponse> {
  const query: Record<string, unknown> = {
    page: params.page ?? 1,
    page_size: params.page_size ?? 50,
  };
  if (typeof params.asset_id === 'number') query.asset_id = params.asset_id;
  if (params.direction) query.direction = params.direction;
  if (params.relation_type) query.relation_type = params.relation_type;
  if (params.target_type) query.target_type = params.target_type;
  return request.get('/asset-center/relations/list', { params: query });
}

export async function getRelation(id: number): Promise<AssetRelation> {
  return request.get(`/asset-center/relations/${id}`);
}

export async function updateRelation(
  id: number,
  data: RelationUpdateInput,
): Promise<AssetRelation> {
  return request.put(`/asset-center/relations/${id}`, data);
}

export async function deleteRelation(
  id: number,
): Promise<RelationOperationResult> {
  return request.delete(`/asset-center/relations/${id}`);
}

// ---- 影响面分析 ----

export async function analyzeImpact(
  assetId: number,
  depth: number = 2,
): Promise<ImpactResult> {
  return request.get(`/asset-center/relations/impact/${assetId}`, {
    params: { depth },
  });
}

// ---- Neo4j 同步 (管理接口) ----

export async function syncPendingToNeo4j(
  batchSize: number = 100,
): Promise<{ total: number; synced: number; pending: number }> {
  return request.post('/asset-center/relations/neo4j/sync-pending', undefined, {
    params: { batch_size: batchSize },
  });
}

// ---- 搜索 ----

export async function searchAssets(data: SearchInput): Promise<SearchResponse> {
  return request.post('/asset-center/search', data);
}

export async function findByRef(
  refType: string,
  refId: number,
): Promise<Asset | null> {
  return request.get('/asset-center/search/by-ref', {
    params: { ref_type: refType, ref_id: refId },
  });
}

export async function findByCodes(codes: string[]): Promise<Asset[]> {
  return request.get('/asset-center/search/by-codes', {
    params: { codes: codes.join(',') },
  });
}

// ---- Agent 业务流 ----

export async function analyzeRequirement(
  data: AnalyzeInput,
): Promise<AnalyzeResult> {
  return request.post('/asset-center/agents/analyze', data);
}

export async function searchAssetsAgent(
  data: AnalyzeInput,
): Promise<SearchResponse | Record<string, unknown>> {
  return request.post('/asset-center/agents/search', {
    query: data.requirement,
    asset_types: data.asset_types,
    module: data.module,
    tags: data.tags,
    limit: data.limit,
    use_vector: data.use_vector,
    use_relation: data.use_relation,
  });
}

export async function evaluateReuse(
  requirement: string,
  searchResults: Array<Record<string, unknown>>,
): Promise<ReuseDecision> {
  return request.post('/asset-center/agents/evaluate', {
    requirement,
    search_results: searchResults,
  });
}

export async function optimizePlan(
  requirement: string,
  reuseDecision: Record<string, unknown>,
  searchResults?: Array<Record<string, unknown>>,
): Promise<{ optimized_plan: OptimizedPlan; quality_score: number; status: string }> {
  return request.post('/asset-center/agents/optimize', {
    requirement,
    reuse_decision: reuseDecision,
    search_results: searchResults ?? [],
  });
}

export async function agentHealthCheck(): Promise<AgentHealthStatus> {
  return request.get('/asset-center/agents/health');
}
