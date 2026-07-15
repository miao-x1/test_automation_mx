/**
 * 工作流监控 Hook
 *
 * 实时轮询工作流事件和Agent状态
 * - running: 2秒轮询
 * - 终态: 停止轮询
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import request from '../services/request';

export interface WorkflowEventItem {
  event_id: string;
  session_id: string;
  agent: string;
  event_type: string;
  status: string;
  message: string;
  error_detail?: string;
  timestamp: string;
}

export interface AgentResultItem {
  agent: string;
  status: string;
  result: any;
  error?: string;
  started_at?: string;
  completed_at?: string;
}

const FINAL_STATES = ['completed', 'failed', 'cancelled'];

function getInterval(statuses: string[]): number {
  if (statuses.some(s => s === 'running')) return 2000;
  if (statuses.some(s => s === 'pending' || s === 'waiting')) return 3000;
  return 5000;
}

export function useWorkflowMonitor(sessionId: string | null) {
  const [events, setEvents] = useState<WorkflowEventItem[]>([]);
  const [agents, setAgents] = useState<AgentResultItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const poll = useCallback(async () => {
    if (!sessionId || !mountedRef.current) return;

    setLoading(true);
    setError(null);
    try {
      const res: any = await request.get(`/workflow/events?session_id=${sessionId}`);
      const data = res?.data || res;
      const eventList: WorkflowEventItem[] = data.items || data.events || data || [];
      setEvents(eventList);

      // 从事件中提取agent状态
      const agentMap = new Map<string, AgentResultItem>();
      for (const ev of eventList) {
        if (!ev.agent) continue;
        const existing = agentMap.get(ev.agent);
        if (!existing || (ev.timestamp && existing.started_at && ev.timestamp > existing.started_at)) {
          agentMap.set(ev.agent, {
            agent: ev.agent,
            status: ev.status,
            result: null,
            error: ev.error_detail,
            started_at: ev.timestamp,
            completed_at: FINAL_STATES.includes(ev.status) ? ev.timestamp : undefined,
          });
        }
      }
      setAgents(Array.from(agentMap.values()));

      // 全部终态则停止轮询
      const statuses = eventList.map(e => e.status).filter(Boolean);
      if (statuses.length > 0 && statuses.every(s => FINAL_STATES.includes(s))) {
        if (timerRef.current) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        setLoading(false);
        return;
      }
    } catch (e: any) {
      setError(e?.message || '获取工作流事件失败');
    } finally {
      setLoading(false);
    }

    // 安排下次轮询
    if (mountedRef.current) {
      const statuses = agents.map(a => a.status);
      timerRef.current = setTimeout(poll, getInterval(statuses));
    }
  }, [sessionId, agents]);

  useEffect(() => {
    mountedRef.current = true;

    if (sessionId) {
      poll();
    }

    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const isRunning = agents.some(a => a.status === 'running' || a.status === 'pending' || a.status === 'waiting');

  return {
    events,
    agents,
    loading,
    error,
    isRunning,
    refetch: poll,
  };
}
