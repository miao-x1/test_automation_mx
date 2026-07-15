/**
 * Session V2 API Service
 *
 * 统一会话管理 API 客户端
 * - 创建会话
 * - 会话列表
 * - 恢复会话
 * - 添加制品
 * - 执行 GraphFlow
 * - 上传文件
 */
import request from './request';

// ===== 类型定义 =====

export interface SessionInfo {
  id: number;
  session_name: string;
  status: string;
  current_step: string | null;
  requirement_summary: string;
  input_mode: string;
  session_key: string | null;
  graphflow_task_id: string | null;
  total_tokens: number;
  total_duration: number;
  artifact_count: number;
  error_count: number;
  created_at: string | null;
  updated_at: string | null;
}

export interface CreateSessionParams {
  requirement?: string;
  input_mode?: string;
  session_name?: string;
  project_id?: string;
  config?: Record<string, unknown>;
  user_id?: number;
}

export interface ArtifactInfo {
  id: number;
  session_id: number;
  artifact_type: string;
  name: string;
  step: string | null;
  source_agent: string | null;
  created_at: string | null;
  file_path: string | null;
  file_size: number | null;
  content?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export interface SessionState {
  session: {
    id: number;
    session_name: string;
    status: string;
    current_step: string | null;
    requirement_text: string;
    requirement_summary: string;
    input_mode: string;
    session_key: string | null;
    graphflow_task_id: string | null;
    total_tokens: number;
    total_duration: number;
    artifact_count: number;
    error_count: number;
    config: Record<string, unknown>;
    created_at: string | null;
    updated_at: string | null;
  };
  artifacts: Record<string, ArtifactInfo[]>;
  agent_events: Array<{
    event_type: string;
    agent_name: string;
    step: string;
    status: string;
    model_name: string | null;
    total_tokens: number;
    duration: number;
    message: string;
    error_message: string;
    is_retry: boolean;
    is_final: boolean;
    created_at: string;
  }>;
  flow_results: Array<{
    step: string;
    agent_name: string;
    status: string;
    duration: number;
    output: string | null;
    error: string | null;
    created_at: string;
  }>;
  stats: {
    total_artifacts: number;
    total_events: number;
    total_flow_results: number;
    artifact_types: string[];
  };
}

export interface AddArtifactParams {
  artifact_type: string;
  name: string;
  content?: Record<string, unknown>;
  file_path?: string;
  file_size?: number;
  mime_type?: string;
  step?: string;
  source_agent?: string;
  tags?: string;
  metadata?: Record<string, unknown>;
}

// ===== API 方法 =====

/** 创建会话 */
export async function createSession(params: CreateSessionParams): Promise<SessionInfo> {
  const res = await request.post('/session/v2/create', params);
  return res.data;
}

/** 会话列表 */
export async function listSessions(params?: {
  user_id?: number;
  status?: string;
  skip?: number;
  limit?: number;
}): Promise<SessionInfo[]> {
  const res = await request.get('/session/v2/list', { params });
  return res.data;
}

/** 获取会话详情 */
export async function getSession(sessionId: number): Promise<SessionInfo> {
  const res = await request.get(`/session/v2/${sessionId}`);
  return res.data;
}

/** 恢复整个会话 */
export async function restoreSession(sessionId: number): Promise<SessionState> {
  const res = await request.get(`/session/v2/${sessionId}/restore`);
  return res.data;
}

/** 删除会话 */
export async function deleteSession(sessionId: number): Promise<void> {
  await request.delete(`/session/v2/${sessionId}`);
}

/** 执行 GraphFlow */
export async function runGraphflow(
  sessionId: number,
  params: { requirement?: string; context?: Record<string, unknown> }
): Promise<Record<string, unknown>> {
  const res = await request.post(`/session/v2/${sessionId}/run`, params);
  return res.data;
}

/** 添加制品 */
export async function addArtifact(
  sessionId: number,
  params: AddArtifactParams
): Promise<{ id: number }> {
  const res = await request.post(`/session/v2/${sessionId}/artifacts`, params);
  return res.data;
}

/** 获取制品列表 */
export async function getArtifacts(
  sessionId: number,
  params?: { artifact_type?: string; step?: string }
): Promise<ArtifactInfo[]> {
  const res = await request.get(`/session/v2/${sessionId}/artifacts`, { params });
  return res.data;
}

/** 获取会话统计 */
export async function getSessionStats(sessionId: number): Promise<Record<string, unknown>> {
  const res = await request.get(`/session/v2/${sessionId}/stats`);
  return res.data;
}

/** 上传文件 */
export async function uploadFile(
  sessionId: number,
  file: File,
  description?: string
): Promise<{ id: number; name: string; file_path: string; file_size: number }> {
  const formData = new FormData();
  formData.append('file', file);
  if (description) formData.append('description', description);
  const res = await request.post(`/session/v2/${sessionId}/upload`, formData);
  return res.data;
}
