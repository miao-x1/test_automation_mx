/**
 * 企业级 Agent Runtime 服务
 *
 * 后端路由前缀: /runtime
 * 接口分组:
 *   1. 任务管理  - POST /tasks, GET /tasks, GET /tasks/{id}, ...
 *   2. SSE 流    - GET /stream/{task_id}
 *   3. WebSocket - WS /ws/{task_id}
 *   4. 调度管理  - POST /schedule, GET /schedules
 *   5. 统计信息  - GET /stats, GET /workers, GET /health
 */
import request from './request';

// ============================================================
// 类型定义
// ============================================================

export type TaskStatus = 'pending' | 'running' | 'success' | 'failed' | 'timeout' | 'cancelled';
export type TaskPriority = 'low' | 'normal' | 'high' | 'urgent';
export type DispatcherMode = 'standalone' | 'distributed';

export interface TaskState {
  task_id: string;
  task_type: string;
  agent_name: string;
  action: string;
  payload: Record<string, any>;
  status: TaskStatus;
  priority: TaskPriority;
  retry_count: number;
  max_retries: number;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
  result?: any;
  error?: string | null;
  events_count: number;
  user_id?: number | null;
  session_id?: string | null;
  timeout_seconds: number;
  worker_id?: string | null;
}

export interface TaskResult {
  task_id: string;
  status: string;
  result?: any;
  error?: string | null;
  events_count: number;
  duration_ms: number;
  worker_id?: string | null;
  retry_count: number;
}

export interface SubmitTaskRequest {
  agent_name: string;
  action?: string;
  payload?: Record<string, any>;
  priority?: TaskPriority;
  timeout_seconds?: number;
  max_retries?: number;
  task_type?: string;
  wait?: boolean;
}

export interface ScheduleTaskRequest {
  agent_name: string;
  action?: string;
  payload?: Record<string, any>;
  delay_seconds?: number;
  cron_expression?: string;
  max_runs?: number | null;
}

export interface ScheduledTask {
  schedule_id: string;
  agent_name: string;
  action: string;
  schedule_type: 'immediate' | 'delayed' | 'scheduled' | 'dependent';
  delay_seconds: number;
  cron_expression: string;
  after_task_ids: string[];
  next_run_at?: number | null;
  last_run_at?: number | null;
  run_count: number;
  max_runs?: number | null;
  enabled: boolean;
}

export interface WorkerStats {
  worker_id: string;
  is_busy: boolean;
  current_task?: string | null;
  tasks_done: number;
  tasks_failed: number;
  total_duration_ms: number;
  avg_duration_ms: number;
}

export interface WorkerPoolStats {
  size: number;
  started: boolean;
  busy_workers: number;
  idle_workers: number;
  running_tasks: number;
  workers: WorkerStats[];
}

export interface DispatcherStats {
  mode: DispatcherMode;
  started: boolean;
  queue_size: number;
  total_tasks: number;
  completed_results: number;
  pending_futures: number;
  status_counts: Record<string, number>;
  worker_pool?: string | null;
}

export interface CollectorStats {
  active_tasks: number;
  completed_tasks: number;
  total_subscribers: number;
  max_history: number;
  stream_publisher?: string | null;
}

export interface StreamPublisherStats {
  events_published: number;
  sse_tasks: number;
  sse_clients_total: number;
  ws_tasks: number;
  ws_clients_total: number;
  sse_clients_history: number;
  ws_clients_history: number;
}

export interface SchedulerStats {
  started: boolean;
  total_schedules: number;
  enabled_schedules: number;
  by_type: Record<string, number>;
  dispatcher?: string | null;
}

export interface RuntimeStats {
  dispatcher: DispatcherStats;
  worker_pool: WorkerPoolStats;
  collector: CollectorStats;
  stream_publisher: StreamPublisherStats;
  scheduler: SchedulerStats;
}

export interface RuntimeHealth {
  status: 'healthy' | 'unhealthy';
  mode?: DispatcherMode;
  started?: boolean;
  queue_size?: number;
  error?: string;
}

export interface SSEEvent {
  event: string;
  task_id?: string;
  [key: string]: any;
}

// ============================================================
// 任务管理
// ============================================================

/** 提交任务 */
export async function submitTask(data: SubmitTaskRequest): Promise<{ task_id: string } | TaskResult> {
  const resp = await request.post('/runtime/tasks', data);
  return resp.data;
}

/** 查询任务状态 */
export async function getTaskStatus(taskId: string): Promise<TaskState> {
  const resp = await request.get(`/runtime/tasks/${taskId}`);
  return resp.data;
}

/** 列出任务 */
export async function listTasks(params?: {
  status?: TaskStatus;
  limit?: number;
}): Promise<TaskState[]> {
  const resp = await request.get('/runtime/tasks', { params });
  return resp.data;
}

/** 获取任务结果 */
export async function getTaskResult(taskId: string): Promise<TaskResult> {
  const resp = await request.get(`/runtime/tasks/${taskId}/result`);
  return resp.data;
}

/** 取消任务 */
export async function cancelTask(taskId: string): Promise<void> {
  await request.post(`/runtime/tasks/${taskId}/cancel`);
}

/** 重试任务 */
export async function retryTask(taskId: string): Promise<void> {
  await request.post(`/runtime/tasks/${taskId}/retry`);
}

// ============================================================
// 调度管理
// ============================================================

/** 调度任务 */
export async function scheduleTask(data: ScheduleTaskRequest): Promise<{ schedule_id: string; type: string }> {
  const resp = await request.post('/runtime/schedule', data);
  return resp.data;
}

/** 列出调度任务 */
export async function listSchedules(enabledOnly?: boolean): Promise<ScheduledTask[]> {
  const resp = await request.get('/runtime/schedules', { params: { enabled_only: enabledOnly } });
  return resp.data;
}

/** 取消调度 */
export async function cancelSchedule(scheduleId: string): Promise<void> {
  await request.delete(`/runtime/schedules/${scheduleId}`);
}

// ============================================================
// 统计与健康
// ============================================================

/** Runtime 健康检查 */
export async function getRuntimeHealth(): Promise<RuntimeHealth> {
  const resp = await request.get('/runtime/health');
  return resp.data;
}

/** Runtime 完整统计 */
export async function getRuntimeStats(): Promise<RuntimeStats> {
  const resp = await request.get('/runtime/stats');
  return resp.data;
}

/** Worker 池统计 */
export async function getWorkerStats(): Promise<WorkerPoolStats> {
  const resp = await request.get('/runtime/workers');
  return resp.data;
}

// ============================================================
// 历史任务查询
// ============================================================

export interface HistoryTask {
  id: number;
  task_id: string;
  parent_task_id?: string | null;
  task_type: string;
  agent_name: string;
  action: string;
  status: TaskStatus;
  priority: TaskPriority;
  retry_count: number;
  max_retries: number;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  duration_ms?: number | null;
  timeout_seconds: number;
  worker_id?: string | null;
  user_id?: number | null;
  session_id?: string | null;
  error?: string | null;
  events_count: number;
}

export interface HistoryQueryParams {
  status?: TaskStatus;
  agent_name?: string;
  hours?: number;
  limit?: number;
  offset?: number;
}

export interface HistoryQueryResult {
  tasks: HistoryTask[];
  total: number;
  limit: number;
  offset: number;
}

/** 查询历史任务 */
export async function queryHistory(params: HistoryQueryParams): Promise<HistoryQueryResult> {
  const resp = await request.get('/runtime/history', { params });
  return resp.data;
}

/** 查询历史任务详情 */
export async function getHistoryTask(taskId: string): Promise<HistoryTask> {
  const resp = await request.get(`/runtime/history/${taskId}`);
  return resp.data;
}

// ============================================================
// 指标统计
// ============================================================

export interface RuntimeMetrics {
  hours: number;
  total: number;
  by_status: Record<string, number>;
  success_rate: number;
  avg_duration_ms: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  throughput: number;
  by_agent: Record<string, {
    total: number;
    success: number;
    failed: number;
    total_duration_ms: number;
    success_rate: number;
    avg_duration_ms: number;
  }>;
  hourly: Array<{
    hour: string;
    total: number;
    success: number;
    failed: number;
  }>;
}

/** 获取指标统计 */
export async function getRuntimeMetrics(
  hours?: number,
  agentName?: string,
): Promise<RuntimeMetrics> {
  const resp = await request.get('/runtime/metrics', {
    params: { hours, agent_name: agentName },
  });
  return resp.data;
}

/**
 * 创建 SSE 事件流连接
 *
 * 使用方式:
 *   const close = createSSEStream('task_xxx', (event) => {
 *     console.log('收到事件:', event);
 *   });
 *   // 关闭连接
 *   close();
 */
export function createSSEStream(
  taskId: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (error: Event) => void,
): () => void {
  // 注意: EventSource 不支持自定义 header,使用 cookie 认证
  const url = `/api/runtime/stream/${taskId}`;
  const eventSource = new EventSource(url);

  eventSource.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      onEvent(data);
    } catch {
      onEvent({ event: 'message', raw: e.data, task_id: taskId });
    }
  };

  // 监听特定事件类型
  const eventTypes = ['start', 'progress', 'end', 'error', 'done', 'ping'];
  eventTypes.forEach((type) => {
    eventSource.addEventListener(type, (e: any) => {
      try {
        const data = e.data ? JSON.parse(e.data) : {};
        onEvent({ ...data, event: type, task_id: taskId });
      } catch {
        onEvent({ event: type, task_id: taskId });
      }
      if (type === 'done') {
        eventSource.close();
      }
    });
  });

  eventSource.onerror = (e) => {
    if (onError) onError(e);
    eventSource.close();
  };

  // 返回关闭函数
  return () => {
    eventSource.close();
  };
}

/**
 * 创建 WebSocket 连接
 *
 * 使用方式:
 *   const ws = createWebSocket('task_xxx', (event) => {
 *     console.log('收到事件:', event);
 *   });
 *   // 关闭连接
 *   ws.close();
 */
export function createWebSocket(
  taskId: string,
  onEvent: (event: SSEEvent) => void,
  onError?: (error: Event) => void,
): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host;
  const url = `${protocol}//${host}/api/runtime/ws/${taskId}`;

  const ws = new WebSocket(url);

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      onEvent(data);
    } catch {
      onEvent({ event: 'message', raw: e.data, task_id: taskId });
    }
  };

  ws.onerror = (e) => {
    if (onError) onError(e);
  };

  return ws;
}
