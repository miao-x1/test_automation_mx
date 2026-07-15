/**
 * 脚本上传服务
 */
import request from './request';

export interface ParsedScript {
  script_type: string;
  language: string;
  name: string;
  description: string;
  target_url: string;
  steps: Array<Record<string, any>>;
  imports: string[];
  functions: string[];
  selectors: Array<Record<string, any>>;
  assertions: string[];
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface ValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
  score: number;
}

export interface UploadResult {
  filename: string;
  saved_path: string;
  content: string;
  parsed: ParsedScript;
  validation: ValidationResult;
}

export interface ExecuteResult {
  task_id: number;
  success: boolean;
  output: string;
  error: string;
  duration: number;
  exit_code: number;
  script_type: string;
  validation: ValidationResult;
}

/** 上传脚本文件（使用原生fetch，避免axios的Content-Type问题） */
export async function uploadScript(file: File): Promise<UploadResult> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch('/api/script-upload/upload', {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({ detail: `上传失败 (${response.status})` }));
    throw new Error(err.detail || `上传失败 (${response.status})`);
  }
  const res = await response.json();
  return res.data;
}

export async function parseScript(content: string, filename: string = ''): Promise<{
  parsed: ParsedScript;
  validation: ValidationResult;
}> {
  const formData = new FormData();
  formData.append('content', content);
  formData.append('filename', filename);
  const res: any = await request.post('/script-upload/parse', formData);
  return res.data;
}

export async function executeScript(params: {
  content: string;
  script_type: string;
  language?: string;
  task_id?: number;
  timeout?: number;
}): Promise<ExecuteResult> {
  const res: any = await request.post('/script-upload/execute', params);
  return res.data;
}
