/**
 * Agent Monitor API 服务
 *
 * 提供与后端 /api/v1/ 接口的通信能力，
 * 用于 Agent 执行监控、日志查询和注册表管理。
 */
import request from './request';

const BASE = '/api/v1';

/* ===================== 类型定义 ===================== */

/** 工作流步骤执行信息 */
export interface WorkflowStepInfo {
  /** 步骤索引 */
  step_index: number;
  /** Agent 名称（唯一标识） */
  agent_name: string;
  /** 显示名称 */
  display_name: string;
  /** 执行状态：success / error / running / skipped */
  status: string;
  /** 执行耗时（秒） */
  duration: number;
  /** 使用的模型名称 */
  model_name: string;
  /** 使用的 Token 数 */
  tokens_used: number;
  /** 错误信息（失败时存在） */
  error: string | null;
  /** 开始时间 */
  start_time: string;
  /** 结束时间 */
  end_time: string | null;
  /** 输入数据 */
  input_data?: any;
  /** 输出数据 */
  output_data?: any;
}

/** 工作流执行结果 */
export interface TaskWorkflow {
  /** 任务 ID */
  task_id: number;
  /** 任务状态 */
  status: string;
  /** 工作流步骤列表 */
  steps: WorkflowStepInfo[];
  /** 总步骤数 */
  total_steps: number;
  /** 总耗时（秒） */
  total_duration: number;
}

/** Agent 执行日志详情 */
export interface AgentLogDetail {
  id: number;
  agent_name: string;
  step: string;
  status: string;
  duration: number;
  model_name: string;
  tokens_used: number;
  error: string | null;
  start_time: string;
  end_time: string | null;
  input_data: any;
  output_data: any;
}

/** Agent 执行日志查询结果 */
export interface AgentLogResult {
  total: number;
  logs: AgentLogDetail[];
}

/** Agent 注册表项 */
export interface AgentRegistryItem {
  /** Agent 名称 */
  agent_name: string;
  /** 显示名称 */
  display_name: string;
  /** Agent 类型 */
  agent_type: string;
  /** 模型名称 */
  model_name: string;
  /** 运行状态 */
  status: string;
  /** 是否启用 */
  enabled: boolean;
  /** 版本号 */
  version: string;
  /** 描述 */
  description?: string;
  /** 能力列表 */
  capabilities?: string[];
}

/** Agent 注册表查询结果 */
export interface AgentRegistryResult {
  total: number;
  agents: AgentRegistryItem[];
}

/** 生命周期统计信息 */
export interface LifecycleStats {
  total_agents: number;
  enabled_agents: number;
  total_tasks: number;
  completed_tasks: number;
  failed_tasks: number;
  running_tasks: number;
  total_tokens_used: number;
  avg_duration: number;
}

/* ===================== API 方法 ===================== */

/**
 * 获取任务工作流（Agent 执行链）
 */
export async function getTaskWorkflow(taskId: number): Promise<TaskWorkflow> {
  const res = await request.get(`${BASE}/tasks/${taskId}/workflow`);
  return res.data;
}

/**
 * 查询任务 Agent 执行日志
 */
export async function getTaskAgentLog(
  taskId: number,
  params?: { agent_name?: string; status?: string; limit?: number }
): Promise<AgentLogResult> {
  const res = await request.get(`${BASE}/tasks/${taskId}/agent-log`, { params });
  return res.data;
}

/**
 * 获取 Agent 注册表
 */
export async function getAgentRegistry(): Promise<AgentRegistryResult> {
  const res = await request.get(`${BASE}/agents/registry`);
  return res.data;
}

/**
 * 启用/禁用 Agent
 */
export async function toggleAgent(agentName: string, enabled: boolean): Promise<any> {
  const res = await request.put(`${BASE}/agents/${agentName}/toggle`, null, { params: { enabled } });
  return res.data;
}

/**
 * 更新 Agent 模型配置
 */
export async function updateAgentModel(agentName: string, modelName: string, provider: string): Promise<any> {
  const res = await request.put(`${BASE}/agents/${agentName}/model`, null, { params: { model_name: modelName, provider } });
  return res.data;
}

/**
 * 获取生命周期统计信息
 */
export async function getLifecycleStats(): Promise<LifecycleStats> {
  const res = await request.get(`${BASE}/lifecycle/stats`);
  return res.data;
}
