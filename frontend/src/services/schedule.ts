/**
 * 定时任务服务
 */
import request from './request';

export interface ScheduleTaskItem {
  id: number;
  name: string;
  description: string | null;
  schedule_type: 'once' | 'daily' | 'cron';
  cron_expression: string | null;
  execute_time: string | null;
  execute_date: string | null;
  start_time: string | null;
  end_time: string | null;
  timeout: number;
  max_retries: number;
  retry_interval: number;
  notify_on_success: boolean;
  notify_on_failure: boolean;
  notify_channels: string | null;
  requirement_id: number | null;
  task_config: string | null;
  status: 'active' | 'paused' | 'expired' | 'disabled';
  last_run_at: string | null;
  last_run_status: string | null;
  next_run_at: string | null;
  run_count: number;
  fail_count: number;
  created_at: string;
}

export interface ScheduleRunLogItem {
  id: number;
  schedule_task_id: number;
  schedule_name?: string;
  execution_id: number | null;
  run_number: number;
  status: string;
  trigger_type: string;
  operator: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration: number | null;
  retry_count: number;
  result_summary: string | null;
  error_message: string | null;
  logs: string | null;
  task_id: number | null;
  created_at: string;
  // 详情接口额外字段
  schedule_type?: string | null;
  task_config?: string | null;
  execution_detail?: any;
}

export interface CreateScheduleTaskParams {
  name: string;
  description?: string;
  schedule_type: 'once' | 'daily' | 'cron';
  cron_expression?: string;
  execute_time?: string;
  execute_date?: string;
  start_time?: string;
  end_time?: string;
  timeout?: number;
  max_retries?: number;
  retry_interval?: number;
  notify_on_success?: boolean;
  notify_on_failure?: boolean;
  notify_channels?: string;
  requirement_id?: number;
  task_config?: { requirement: string; target_url?: string; script_format?: string };
}

export async function listScheduleTasks(params?: { status?: string; page?: number; page_size?: number }) {
  const res: any = await request.get('/schedule', { params });
  return res.data;
}

export async function createScheduleTask(data: CreateScheduleTaskParams) {
  const res: any = await request.post('/schedule', data);
  return res.data;
}

export async function updateScheduleTask(id: number, data: Partial<CreateScheduleTaskParams>) {
  const res: any = await request.put(`/schedule/${id}`, data);
  return res.data;
}

export async function deleteScheduleTask(id: number) {
  const res: any = await request.delete(`/schedule/${id}`);
  return res;
}

export async function pauseScheduleTask(id: number) {
  const res: any = await request.post(`/schedule/${id}/pause`);
  return res;
}

export async function resumeScheduleTask(id: number) {
  const res: any = await request.post(`/schedule/${id}/resume`);
  return res;
}

export async function triggerScheduleTask(id: number) {
  const res: any = await request.post(`/schedule/${id}/trigger`);
  return res;
}

export async function getRunHistory(id: number, params?: { page?: number; page_size?: number }) {
  const res: any = await request.get(`/schedule/${id}/runs`, { params });
  return res.data;
}

// ==================== 全局历史记录 ====================

export async function listScheduleHistory(params?: {
  status?: string;
  trigger_type?: string;
  schedule_id?: number;
  keyword?: string;
  page?: number;
  page_size?: number;
}) {
  const res: any = await request.get('/schedule/history/list', { params });
  return res.data;
}

export async function getScheduleHistoryDetail(id: number) {
  const res: any = await request.get(`/schedule/history/${id}`);
  return res.data;
}

export async function retryScheduleHistory(id: number) {
  const res: any = await request.post(`/schedule/history/${id}/retry`);
  return res.data;
}
