import request from './request';

export interface UIElement {
  id: number;
  name: string;
  type: string;
  text: string | null;
  source: 'vision' | 'dom' | 'merge';
  locator: string | null;
  xpath: string | null;
  css_selector: string | null;
  element_id: string | null;
  element_class: string | null;
  element_name: string | null;
  placeholder: string | null;
  href: string | null;
  aria_label: string | null;
  role: string | null;
  data_testid: string | null;
  page_url: string | null;
  confidence: number | null;
}

export interface Task {
  id: number;
  task_name: string;
  status: 'pending' | 'processing' | 'success' | 'failed';
  input_mode: 'image' | 'url';
  page_url: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  images: Array<{
    id: number;
    original_filename: string;
    file_path: string;
    file_size: number;
    file_type: string;
  }>;
  analysis_result: {
    id: number;
    agent_type: string;
    page_type: string | null;
    elements_json: string | null;
    interactions_json: string | null;
    analysis_summary: string | null;
  } | null;
  script: {
    id: number;
    script_type: string;
    script_content: string;
    script_language: string;
  } | null;
  ui_elements: UIElement[];
  page_elements: Array<{
    id: number;
    tag_name: string;
    element_text: string | null;
    element_id: string | null;
    element_class: string | null;
    element_name: string | null;
    placeholder: string | null;
    href: string | null;
    aria_label: string | null;
    role: string | null;
    xpath: string | null;
    css_selector: string | null;
  }>;
}

export interface TaskListResponse {
  total: number;
  items: Task[];
}

// 上传图片并创建任务（统一入口，使用原生fetch避免axios的Content-Type问题）
export async function uploadAndCreateTask(formData: FormData) {
  const response = await fetch('/api/tasks/upload', {
    method: 'POST',
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) throw new Error(`上传失败 (${response.status})`);
  const res = await response.json();
  return res;
}

// URL模式创建任务（统一入口）
export function createTaskByUrl(url: string, task_name?: string) {
  return request.post('/tasks/create', { url, task_name });
}

// 获取任务列表
export function getTaskList(skip = 0, limit = 20) {
  return request.get('/tasks/', { params: { skip, limit } });
}

// 获取任务详情
export function getTask(id: number) {
  return request.get(`/tasks/${id}`);
}

// 删除任务
export function deleteTask(id: number) {
  return request.delete(`/tasks/${id}`);
}

// 重新执行任务
export function rerunTask(id: number) {
  return request.post(`/tasks/${id}/rerun`);
}

// 下载脚本
export function downloadScript(id: number) {
  window.open(`/api/tasks/${id}/download`, '_blank');
}

// 更新脚本内容
export function updateScript(taskId: number, scriptContent: string) {
  return request.put(`/tasks/${taskId}/script`, { script_content: scriptContent });
}

// ============ 执行管理 ============

export interface ExecutionRecord {
  id: number;
  task_id: number;
  status: 'pending' | 'running' | 'success' | 'failed';
  start_time: string | null;
  end_time: string | null;
  duration: number | null;
  success_count: number;
  failed_count: number;
  error_message: string | null;
  log_content: string | null;
  report_path: string | null;
  screenshot_path: string | null;
  created_at: string;
}

// 执行脚本
export function executeScript(taskId: number) {
  return request.post(`/executions/${taskId}/execute`);
}

// 获取执行记录
export function getExecution(executionId: number) {
  return request.get(`/executions/${executionId}`);
}

// 获取任务的执行记录列表
export function getTaskExecutions(taskId: number) {
  return request.get(`/executions/task/${taskId}/list`);
}

// 获取执行日志
export function getExecutionLogs(executionId: number) {
  return request.get(`/executions/${executionId}/logs`, { responseType: 'text' });
}

// 获取报告URL
export function getReportUrl(executionId: number) {
  return `/api/executions/${executionId}/report`;
}

// 获取截图URL
export function getScreenshotUrl(executionId: number) {
  return `/api/executions/${executionId}/screenshot`;
}
