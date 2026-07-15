import request from './request';

// ============ 图数据库 ============

export interface GraphNode {
  id: string;
  label: string;
  type: string; // page | element | testcase | script
  properties: Record<string, any>;
}

export interface GraphEdge {
  source: string;
  target: string;
  type: string;
  label: string;
  properties?: Record<string, any>;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  statistics: Record<string, any>;
  available?: boolean;
}

/** 构建图谱 */
export const buildGraph = (full = true, cleanFirst = true) =>
  request.post('/graph/build', { full, clean_first: cleanFirst });

/** 构建任务图谱 */
export const buildTaskGraph = (taskId: number) =>
  request.post(`/graph/build/${taskId}`);

/** 增量同步任务 */
export const syncTaskGraph = (taskId: number) =>
  request.post(`/graph/sync/${taskId}`);

/** 获取图谱可视化数据 */
export const getGraphData = (types?: string, limit = 500) =>
  request.get<GraphData>('/graph/data', { params: { types, limit } });

/** 图谱统计 */
export const getGraphStat = () =>
  request.get('/graph/stat');

/** 搜索图谱节点 */
export const searchGraphNodes = (keyword: string, limit = 30) =>
  request.get('/graph/query', { params: { keyword, limit } });

/** 最短路径查询 */
export const getShortestPath = (fromId: string, toId: string) =>
  request.get('/graph/path', { params: { from_id: fromId, to_id: toId } });

/** 获取所有页面节点 */
export const getGraphPages = (limit = 100) =>
  request.get('/graph/pages', { params: { limit } });

/** 获取页面详情 */
export const getPageDetail = (pageId: string) =>
  request.get(`/graph/pages/${encodeURIComponent(pageId)}`);

/** 获取页面导航路径 */
export const getPagePaths = (pageId: string, maxDepth = 3) =>
  request.get(`/graph/pages/${encodeURIComponent(pageId)}/path`, { params: { max_depth: maxDepth } });

/** 获取所有用例节点 */
export const getGraphCases = (limit = 100) =>
  request.get('/graph/cases', { params: { limit } });

/** 获取用例详情 */
export const getCaseFlow = (caseId: string) =>
  request.get(`/graph/cases/${encodeURIComponent(caseId)}`);

/** 获取所有脚本节点 */
export const getGraphScripts = (limit = 100) =>
  request.get('/graph/scripts', { params: { limit } });

/** 图谱统计（兼容旧接口） */
export const getGraphStatistics = () =>
  request.get('/graph/statistics');

/** Neo4j状态检查 */
export const checkGraphStatus = () =>
  request.get('/graph/status');

/** 获取节点一阶邻居（按需展开） */
export const getNodeNeighbors = (nodeId: string, relTypes?: string[]) =>
  request.get(`/graph/neighbors/${encodeURIComponent(nodeId)}`, {
    params: relTypes ? { rel_types: relTypes.join(',') } : {},
  });

/** 获取业务流列表 */
export const getBusinessFlows = () =>
  request.get('/graph/business-flows');

/** Graph推理页面路径 */
export const inferGraphFlow = (requirement: string, keywords?: string[], steps?: string[]) =>
  request.post('/graph/infer', { requirement, keywords, steps });
