import request from './request';

export interface PerformanceTask {
  id: number;
  name: string;
  test_type: string;
  target_url: string;
  method: string;
  headers: Record<string, any>;
  body: Record<string, any>;
  business_volume: number;
  concurrency: number;
  duration_seconds: number;
  tps_target: number | null;
  ramp_up: number;
  script_type: string;
  script_content: string | null;
  jmeter_config: string | null;
  plan: any;
  status: string;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface PerformanceResult {
  id: number;
  task_id: number;
  total_requests: number;
  total_errors: number;
  error_rate: number;
  avg_tps: number;
  peak_tps: number;
  avg_rt: number;
  p50_rt: number | null;
  p90_rt: number | null;
  p95_rt: number | null;
  p99_rt: number | null;
  concurrency: number;
  duration_seconds: number;
  analysis: any;
  status: string;
  created_at: string;
}

export interface PerformanceMetric {
  id: number;
  result_id: number;
  timestamp: number;
  elapsed: number;
  tps: number;
  avg_rt: number;
  concurrent_users: number;
  error_count: number;
  cpu_percent: number | null;
  memory_mb: number | null;
}

export function createTask(data: { name: string; target_url: string; method: string; test_type: string; headers?: any; body?: any; business_volume: number }): Promise<PerformanceTask> {
  return request.post('/performance', data);
}
export function listTasks(params: { page: number; page_size: number; test_type?: string; status?: string }): Promise<{ items: PerformanceTask[]; total: number; page: number; page_size: number } | PerformanceTask[]> {
  return request.get('/performance/list', { params });
}
export function getTask(taskId: number): Promise<PerformanceTask> {
  return request.get(`/performance/${taskId}`);
}
export function deleteTask(taskId: number): Promise<any> {
  return request.delete(`/performance/${taskId}`);
}
export function runPlan(taskId: number): Promise<any> {
  return request.post(`/performance/${taskId}/plan`);
}
export function runScript(taskId: number, scriptType: string): Promise<any> {
  return request.post(`/performance/${taskId}/script`, { script_type: scriptType });
}
export function runAnalysis(taskId: number, logs?: any[]): Promise<any> {
  return request.post(`/performance/${taskId}/analyze`, { logs: logs || null });
}
export function getResults(taskId: number): Promise<{ items: PerformanceResult[]; total: number } | PerformanceResult[]> {
  return request.get(`/performance/${taskId}/results`);
}
export function getMetrics(resultId: number): Promise<{ items: PerformanceMetric[]; total: number } | PerformanceMetric[]> {
  return request.get(`/performance/${resultId}/metrics`);
}
export function saveResult(taskId: number, data: any): Promise<any> {
  return request.post(`/performance/${taskId}/results`, data);
}
export function saveMetric(resultId: number, data: any): Promise<any> {
  return request.post(`/performance/${resultId}/metrics`, data);
}

// ================================================================
// 测试执行
// ================================================================

export interface ExecuteStatus {
  task_id: number;
  result_id: number;
  status: 'running' | 'completed' | 'failed' | 'stopped' | 'not_found';
  elapsed: number;
  error: string;
  metrics_count: number;
  final_stats: any;
}

export interface MetricEvent {
  type: 'metric' | 'final' | 'end' | 'stopped' | 'error';
  task_id?: number;
  result_id?: number;
  timestamp?: number;
  elapsed?: number;
  tps?: number;
  avg_rt?: number;
  concurrent_users?: number;
  error_count?: number;
  total_requests?: number;
  cpu_percent?: number | null;
  memory_mb?: number | null;
  p50_rt?: number;
  p90_rt?: number;
  p95_rt?: number;
  p99_rt?: number;
  min_rt?: number;
  max_rt?: number;
  status?: string;
  error?: string;
  data?: any;
  final_stats?: any;
  message?: string;
}

export function executeTask(taskId: number): Promise<{ status: string; task_id: number; result_id: number }> {
  return request.post(`/performance/${taskId}/execute`);
}

export function stopExecute(taskId: number): Promise<any> {
  return request.post(`/performance/${taskId}/execute/stop`);
}

export function getExecuteStatus(taskId: number): Promise<ExecuteStatus> {
  return request.get(`/performance/${taskId}/execute/status`);
}

/**
 * SSE 流式监听实时性能指标
 * 使用 fetch + ReadableStream 解析 text/event-stream
 *
 * @param taskId 任务 ID
 * @param onMetric 指标回调
 * @param onEnd 结束回调
 * @param onError 错误回调
 * @returns AbortController (调用 .abort() 停止监听)
 */
export function streamExecuteMetrics(
  taskId: number,
  onMetric: (event: MetricEvent) => void,
  onEnd?: (event: MetricEvent) => void,
  onError?: (error: Error) => void,
): AbortController {
  const controller = new AbortController();

  (async () => {
    try {
      const resp = await fetch(`/api/performance/${taskId}/execute/stream`, {
        method: 'GET',
        credentials: 'include',
        signal: controller.signal,
        headers: { 'Accept': 'text/event-stream' },
      });

      if (!resp.ok) {
        onError?.(new Error(`SSE 连接失败: ${resp.status}`));
        return;
      }

      const reader = resp.body?.getReader();
      if (!reader) {
        onError?.(new Error('无法读取响应流'));
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const jsonStr = line.slice(6).trim();
            if (!jsonStr) continue;
            try {
              const event: MetricEvent = JSON.parse(jsonStr);
              if (event.type === 'metric') {
                onMetric(event);
              } else if (event.type === 'final') {
                onMetric(event);
              } else if (event.type === 'end' || event.type === 'stopped') {
                onEnd?.(event);
                return;
              } else if (event.type === 'error') {
                onError?.(new Error(event.message || '执行错误'));
                return;
              }
            } catch {
              // 忽略解析错误
            }
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        onError?.(err);
      }
    }
  })();

  return controller;
}
