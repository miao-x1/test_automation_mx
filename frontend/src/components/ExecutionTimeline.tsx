/**
 * 执行时间轴回放组件
 *
 * 展示执行过程中每一步的：
 * - 步骤名称 + 状态
 * - 输入/输出对照
 * - 耗时
 * - 截图（如有）
 *
 * 支持展开查看每步详情
 */
import React from 'react';
import { Timeline, Typography, Tag, Space, Image } from 'antd';
import {
  CheckCircleOutlined, CloseCircleOutlined, LoadingOutlined,
  ClockCircleOutlined, PlayCircleOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

export interface ExecutionStep {
  step: string;
  status: 'pending' | 'running' | 'success' | 'failed';
  action?: string;
  selector?: string;
  value?: string;
  screenshotUrl?: string;
  duration?: number;
  error?: string;
  log?: string;
}

interface ExecutionTimelineProps {
  steps: ExecutionStep[];
  title?: string;
}

const statusToColor = (status: ExecutionStep['status']): string => {
  switch (status) {
    case 'running': return '#1890ff';
    case 'success': return '#52c41a';
    case 'failed': return '#ff4d4f';
    default: return '#d9d9d9';
  }
};

const statusToIcon = (status: ExecutionStep['status']): React.ReactNode => {
  switch (status) {
    case 'running': return <LoadingOutlined spin style={{ color: '#1890ff' }} />;
    case 'success': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    default: return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
  }
};

export function ExecutionTimeline({ steps, title }: ExecutionTimelineProps) {
  if (!steps || steps.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '24px 0', color: '#bfbfbf' }}>
        <PlayCircleOutlined style={{ fontSize: 32 }} />
        <div style={{ marginTop: 8 }}>执行步骤将在此展示</div>
      </div>
    );
  }

  const timelineItems = steps.map((step, idx) => ({
    key: String(idx),
    color: statusToColor(step.status),
    dot: statusToIcon(step.status),
    children: (
      <div style={{ paddingBottom: 4 }}>
        <Space size="small" align="center">
          <Text strong style={{ fontSize: 13 }}>{step.step}</Text>
          <Tag color={step.status === 'success' ? 'success' : step.status === 'failed' ? 'error' : 'processing'}
            style={{ fontSize: 10 }}>
            {step.status === 'success' ? '通过' : step.status === 'failed' ? '失败' : step.status === 'running' ? '执行中' : '等待'}
          </Tag>
          {step.duration != null && <Text type="secondary" style={{ fontSize: 11 }}>{step.duration}ms</Text>}
        </Space>
        <div style={{ marginTop: 4, paddingLeft: 4, borderLeft: '2px solid #f0f0f0' }}>
          {step.action && (
            <div style={{ fontSize: 12 }}>
              <Text type="secondary">操作：</Text>
              <Text code style={{ fontSize: 11 }}>{step.action}</Text>
            </div>
          )}
          {step.selector && (
            <div style={{ fontSize: 12 }}>
              <Text type="secondary">定位器：</Text>
              <Text code style={{ fontSize: 11 }}>{step.selector}</Text>
            </div>
          )}
          {step.value && (
            <div style={{ fontSize: 12 }}>
              <Text type="secondary">输入值：</Text>
              <Text style={{ fontSize: 11 }}>{step.value}</Text>
            </div>
          )}
          {step.error && (
            <div style={{ fontSize: 12, color: '#ff4d4f', marginTop: 2 }}>
              <CloseCircleOutlined /> {step.error}
            </div>
          )}
          {step.screenshotUrl && (
            <div style={{ marginTop: 4 }}>
              <Image src={step.screenshotUrl} style={{ maxWidth: 200, maxHeight: 120, borderRadius: 4 }} />
            </div>
          )}
        </div>
      </div>
    ),
  }));

  return (
    <div>
      {title && <Text strong style={{ display: 'block', marginBottom: 12 }}>{title}</Text>}
      <Timeline items={timelineItems} />
    </div>
  );
}

/**
 * 从执行记录构建时间轴步骤
 */
export function buildTimelineFromExecution(exec: {
  steps?: any[];
  log_content?: string;
  screenshot_path?: string;
}): ExecutionStep[] {
  if (!exec?.steps || !Array.isArray(exec.steps)) {
    // 从日志解析步骤
    return parseStepsFromLog(exec?.log_content || '');
  }
  return exec.steps.map((s: any) => ({
    step: s.step || s.name || `步骤 ${s.order}`,
    status: s.status || (s.passed !== false ? 'success' : 'failed'),
    action: s.action,
    selector: s.selector,
    value: s.value,
    duration: s.duration,
    error: s.error,
    screenshotUrl: s.screenshot_url,
  }));
}

function parseStepsFromLog(log: string): ExecutionStep[] {
  if (!log) return [];
  const lines = log.split('\n').filter(l => l.trim());
  return lines.slice(0, 50).map((line, idx) => ({
    step: `步骤 ${idx + 1}`,
    status: line.toLowerCase().includes('fail') || line.toLowerCase().includes('error') ? 'failed' : 'success',
    log: line,
  }));
}
