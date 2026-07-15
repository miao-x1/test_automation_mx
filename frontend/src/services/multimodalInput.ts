/**
 * 多模态输入服务
 *
 * API接口：
 * - POST /multimodal-input/upload_images — 上传图片
 * - POST /multimodal-input/upload_script — 上传脚本
 * - POST /multimodal-input/parse — 解析多模态输入
 * - POST /multimodal-input/fuse — 融合解析结果
 * - POST /multimodal-input/parse_and_fuse — 一键解析融合
 * - GET  /multimodal-input/recommend — 获取推荐模式
 * - GET  /multimodal-input/{input_id} — 获取输入详情
 * - POST /requirement/generate_multimodal — 多模态一键生成
 * - POST /requirement/generate_multimodal_and_execute — 多模态一键生成并执行
 */
import request from './request';

// ==================== 类型定义 ====================

/** 输入模式 */
export type InputMode = 'text' | 'image' | 'url' | 'script' | 'mixed';

/** 推荐模式 */
export type RecommendedMode = 'text' | 'vision' | 'dom' | 'reuse';

/** 解析结果 */
export interface ParseResult {
  source: string;
  success: boolean;
  intent: string;
  summary: string;
  steps: string[];
  keywords: string[];
  target_url: string;
  elements: Array<{ name: string; type: string; action: string }>;
  extra: Record<string, unknown>;
}

/** 融合结果 */
export interface FusedResult {
  intent: string;
  summary: string;
  steps: string[];
  keywords: string[];
  target_url: string;
  elements: Array<Record<string, unknown>>;
  unified_requirement: string;
  sources: string[];
  confidence: number;
  extra?: Record<string, unknown>;
}

/** 多模态输入详情 */
export interface MultiModalInputDetail {
  id: number;
  requirement_id: number | null;
  mode: InputMode;
  text: string | null;
  images: string[];
  urls: string[];
  script_path: string | null;
  script_content: string | null;
  script_language: string | null;
  page_ids: number[];
  recommended_mode: RecommendedMode | null;
  recommended_reason: string | null;
  parsed_result: ParseResult[];
  fused_result: FusedResult | null;
  unified_requirement: string | null;
  created_at: string | null;
}

// ==================== API函数 ====================

/** 上传图片（使用原生fetch，避免axios的Content-Type问题） */
export async function uploadImages(files: File[]): Promise<{ image_paths: string[] }> {
  const formData = new FormData();
  files.forEach(f => formData.append('files', f));
  const response = await fetch('/api/multimodal-input/upload_images', {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) throw new Error(`上传失败 (${response.status})`);
  const res = await response.json();
  return res.data;
}

/** 上传脚本（使用原生fetch，避免axios的Content-Type问题） */
export async function uploadScript(file: File): Promise<{
  script_path: string;
  script_content: string;
  script_language: string;
  filename: string;
}> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch('/api/multimodal-input/upload_script', {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) throw new Error(`上传失败 (${response.status})`);
  const res = await response.json();
  return res.data;
}

/** 解析多模态输入 */
export async function parseInput(params: {
  text?: string;
  images?: string[];
  urls?: string[];
  script_content?: string;
  script_language?: string;
  page_ids?: number[];
}): Promise<{
  input_id: number;
  mode: InputMode;
  recommended_mode: RecommendedMode;
  recommended_reason: string;
  parse_results: ParseResult[];
  active_modes: string[];
}> {
  const res: any = await request.post('/multimodal-input/parse', params);
  return res.data;
}

/** 一键解析融合 */
export async function parseAndFuse(params: {
  text?: string;
  images?: string[];
  urls?: string[];
  script_content?: string;
  script_language?: string;
  page_ids?: number[];
}): Promise<{
  input_id: number;
  mode: InputMode;
  recommended_mode: RecommendedMode;
  recommended_reason: string;
  active_modes: string[];
  fused: FusedResult;
  unified_requirement: string;
}> {
  const res: any = await request.post('/multimodal-input/parse_and_fuse', params);
  return res.data;
}

/** 获取推荐模式 */
export async function getRecommendation(params: {
  text?: string;
  has_images?: boolean;
  has_urls?: boolean;
  has_script?: boolean;
}): Promise<{
  recommended_mode: RecommendedMode;
  recommended_reason: string;
}> {
  const res: any = await request.get('/multimodal-input/recommend', { params });
  return res.data;
}

/** 获取输入详情 */
export async function getInputDetail(inputId: number): Promise<MultiModalInputDetail> {
  const res: any = await request.get(`/multimodal-input/${inputId}`);
  return res.data;
}
