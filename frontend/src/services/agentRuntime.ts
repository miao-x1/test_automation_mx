/**
 * Agent Runtime API 服务
 *
 * 提供与后端 /api/v1/ 接口的通信能力。
 */
import request from './request';

const BASE = '/api/v1';

/** 提交任务请求 */
export interface TaskRunRequest {
  task_id?: string;
  requirement: string;
  user_id?: number;
  task_type?: string;
  workflow_name?: string;
  framework?: string;
  platform?: string;
  confidence?: number;
  auto_classify?: boolean;
  timeout?: number;
}

/** 提交任务响应 */
export interface TaskRunResponse {
  session_id: string;
  task_id: string;
  status: string;
  message: string;
}

/** Agent 执行日志 */
export interface AgentExecutionLog {
  id: number;
  session_id: string;
  task_id: string;
  agent_name: string;
  step: string;
  input_data: any;
  output_data: any;
  status: string;
  start_time: string;
  end_time: string | null;
  duration: number;
  error: string | null;
  model_name: string | null;
  tokens_used: number;
}

/** Agent 事件 */
export interface AgentEvent {
  event_id: string;
  event_type: string;
  task_id: string;
  session_id: string;
  agent_name: string;
  agent_type: string;
  status: string;
  step: string;
  message: string;
  progress: number;
  timestamp: number;
  input_data?: any;
  output_data?: any;
  error?: string;
  duration: number;
  model_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
}

/** 工作流步骤 */
export interface WorkflowStep {
  name: string;
  agent_name: string;
  action: string;
  input_key: string;
  output_key: string;
  required: boolean;
  timeout: number;
}

/** 工作流定义 */
export interface WorkflowDef {
  name: string;
  display_name: string;
  description: string;
  task_type: string;
  steps: WorkflowStep[];
  total_steps: number;
}

/** Agent 元数据 */
export interface AgentMeta {
  name: string;
  display_name: string;
  description: string;
  module_path: string;
  class_name: string;
  model_config: any;
  system_prompt: string;
  tools: string[];
  capabilities: string[];
  enabled: boolean;
  category: string;
}

/**
 * 提交 AI 任务
 */
export async function runTask(req: TaskRunRequest): Promise<TaskRunResponse> {
  const res = await request.post(`${BASE}/task/run`, req);
  return res.data;
}

/**
 * SSE 流式提交任务
 * 返回 EventSource 用于实时监听执行状态
 */
export function runTaskStream(req: TaskRunRequest): EventSource {
  // 使用 POST + SSE 需要通过 fetch + ReadableStream 实现
  // 这里提供 EventSource 的简化版本（仅 GET）
  // 实际使用时通过 fetch SSE
  const params = new URLSearchParams({
    requirement: req.requirement,
    task_id: req.task_id || '',
    user_id: String(req.user_id || 0),
    task_type: req.task_type || '',
    workflow_name: req.workflow_name || '',
    timeout: String(req.timeout || 600),
  });
  return new EventSource(`${BASE}/task/run/stream?${params}`);
}

/**
 * 使用 fetch + ReadableStream 实现 POST SSE
 */
export async function runTaskSSE(
  req: TaskRunRequest,
  onEvent: (event: any) => void,
  onError?: (error: any) => void,
  onComplete?: () => void
): Promise<void> {
  try {
    const response = await fetch(`${BASE}/task/run/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
      },
      body: JSON.stringify(req),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('无法获取响应流');
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
          try {
            const data = JSON.parse(line.slice(6));
            onEvent(data);
            if (data.event_type === 'done' || data.event === 'done') {
              onComplete?.();
              return;
            }
          } catch (e) {
            // 忽略解析错误
          }
        }
      }
    }
    onComplete?.();
  } catch (error) {
    onError?.(error);
  }
}

/**
 * 查询 Agent 执行日志
 */
export async function getTaskLogs(
  sessionId: string,
  params?: { agent_name?: string; status?: string; limit?: number }
): Promise<{ session_id: string; total: number; logs: AgentExecutionLog[] }> {
  const res = await request.get(`${BASE}/task/${sessionId}/logs`, { params });
  return res.data;
}

/**
 * 查询任务状态
 */
export async function getTaskStatus(sessionId: string): Promise<any> {
  const res = await request.get(`${BASE}/task/${sessionId}/status`);
  return res.data;
}

/**
 * 获取会话事件
 */
export async function getSessionEvents(sessionId: string): Promise<any> {
  const res = await request.get(`${BASE}/sessions/${sessionId}/events`);
  return res.data;
}

/**
 * 列出所有已注册 Agent
 */
export async function listAgents(): Promise<{ total: number; agents: AgentMeta[] }> {
  const res = await request.get(`${BASE}/agents`);
  return res.data;
}

/**
 * 列出所有工作流
 */
export async function listWorkflows(): Promise<{ total: number; workflows: WorkflowDef[] }> {
  const res = await request.get(`${BASE}/workflows`);
  return res.data;
}

/**
 * 获取运行时统计
 */
export async function getRuntimeStats(): Promise<any> {
  const res = await request.get(`${BASE}/runtime/stats`);
  return res.data;
}

/**
 * 列出所有会话
 */
export async function listSessions(userId?: number): Promise<any> {
  const res = await request.get(`${BASE}/sessions`, { params: { user_id: userId } });
  return res.data;
}

// ==================== 一键执行 ====================

/** 一键执行响应 */
export interface OneClickResponse {
  status: 'completed' | 'failed';
  session_id: string;
  requirement_analysis?: {
    intent: string;
    summary: string;
    target_url: string;
    steps: string[];
    business_flow?: {
      name: string;
      description: string;
      stages: { name: string; actions: string[] }[];
    };
    test_points?: {
      point: string;
      type: string;
      priority: string;
      description: string;
    }[];
    risk_points?: {
      risk: string;
      level: string;
      impact: string;
      mitigation: string;
    }[];
  };
  test_cases?: any;
  script_content?: string;
  execution_result?: {
    status: string;
    success_count: number;
    failed_count: number;
    duration: number;
    error_message: string;
    report_path: string;
    screenshot_path: string;
    log_content: string;
  };
  failure_analysis?: {
    root_cause: string;
    failure_reasons: string[];
    fix_suggestions: string[];
    failed_steps: string[];
    severity: string;
  };
  report_url?: string;
  screenshot_url?: string;
  duration: number;
  message: string;
}

/**
 * 一键执行（非流式）
 */
export async function oneClickRun(
  requirement: string,
  taskId?: string
): Promise<OneClickResponse> {
  const res = await request.post(`${BASE}/task/one-click`, {
    requirement,
    task_id: taskId || '',
  });
  return res.data;
}

/**
 * 一键执行（SSE流式）
 */
export async function oneClickRunSSE(
  requirement: string,
  onEvent: (event: any) => void,
  onError?: (error: any) => void,
  onComplete?: () => void,
  taskId?: string
): Promise<void> {
  try {
    const response = await fetch(`${BASE}/task/one-click/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${localStorage.getItem('token') || ''}`,
      },
      body: JSON.stringify({ requirement, task_id: taskId || '' }),
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new Error('无法获取响应流');
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
          try {
            const data = JSON.parse(line.slice(6));
            onEvent(data);
            if (data.event === 'done') {
              onComplete?.();
              return;
            }
          } catch {
            // 忽略解析错误
          }
        }
      }
    }
    onComplete?.();
  } catch (error) {
    onError?.(error);
  }
}
