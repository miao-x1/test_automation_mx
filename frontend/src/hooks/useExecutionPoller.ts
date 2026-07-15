/**
 * 执行状态轮询 Hook
 *
 * 自适应轮询策略：
 * - waiting: 3秒
 * - running: 1秒
 * - 终态(success/failed/cancelled): 停止轮询
 */
import { useState, useEffect, useRef, useCallback } from 'react';
import request from '../services/request';

export interface ExecutionStatus {
  id: number;
  task_id: number;
  status: string;  // waiting/pending/running/success/failed/cancelled
  duration: number | null;
  success_count: number;
  failed_count: number;
  error_message: string | null;
  log_content: string | null;
  report_path: string | null;
  screenshot_path: string | null;
  trigger_source: string | null;
  created_at: string;
}

const FINAL_STATES = ['success', 'failed', 'cancelled'];

function getInterval(status: string): number {
  if (status === 'running') return 1000;
  if (status === 'waiting' || status === 'pending') return 3000;
  return 2000;
}

export function useExecutionPoller(executionId: number | null) {
  const [status, setStatus] = useState<string>('waiting');
  const [execution, setExecution] = useState<ExecutionStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const poll = useCallback(async () => {
    if (!executionId || !mountedRef.current) return;

    setLoading(true);
    try {
      const res: any = await request.get(`/executions/${executionId}`);
      const data = res?.data || res;
      setExecution(data);
      setStatus(data.status || 'waiting');

      // 终态停止轮询
      if (FINAL_STATES.includes(data.status)) {
        if (timerRef.current) {
          clearTimeout(timerRef.current);
          timerRef.current = null;
        }
        setLoading(false);
        return;
      }
    } catch (e) {
      console.error('[useExecutionPoller] poll failed:', e);
    } finally {
      setLoading(false);
    }

    // 安排下次轮询
    if (mountedRef.current) {
      timerRef.current = setTimeout(poll, getInterval(status));
    }
  }, [executionId, status]);

  useEffect(() => {
    mountedRef.current = true;

    if (executionId) {
      // 首次立即轮询
      poll();
    }

    return () => {
      mountedRef.current = false;
      if (timerRef.current) {
        clearTimeout(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [executionId]); // eslint-disable-line react-hooks/exhaustive-deps

  const isRunning = status === 'running' || status === 'waiting' || status === 'pending';
  const isFinished = FINAL_STATES.includes(status);

  return {
    status,
    execution,
    loading,
    isRunning,
    isFinished,
    refetch: poll,
  };
}
