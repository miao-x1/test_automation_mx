/**
 * AI流程可视化组件
 *
 * 展示AI分析5步流程的实时状态：
 * 1. 需求解析 → 2. RAG召回 → 3. Graph推理 → 4. 用例生成 → 5. 脚本生成
 *
 * 每步显示：状态图标 + 步骤名 + 输入/输出对照 + 耗时
 */
import React from 'react';
import { Steps, Typography, Tag, Space } from 'antd';
import {
  RobotOutlined, DatabaseOutlined, ApartmentOutlined,
  FileTextOutlined, CodeOutlined, CheckCircleOutlined,
  CloseCircleOutlined, LoadingOutlined, ClockCircleOutlined,
  EyeOutlined, TagOutlined,
} from '@ant-design/icons';

const { Text } = Typography;

export interface AIStep {
  key: string;
  label: string;
  icon: React.ReactNode;
  status: 'pending' | 'running' | 'success' | 'failed';
  input?: string;
  output?: string;
  duration?: number;
  detail?: any;
}

interface AIStepTimelineProps {
  steps: AIStep[];
  currentStepKey?: string;
  compact?: boolean;
}

const STEP_DEFINITIONS = [
  { key: 'multimodal', label: '多模态解析', icon: <EyeOutlined /> },
  { key: 'classify', label: '类型识别', icon: <TagOutlined /> },
  { key: 'parse', label: '需求解析', icon: <RobotOutlined /> },
  { key: 'rag', label: 'RAG召回', icon: <DatabaseOutlined /> },
  { key: 'relation', label: '页面关联', icon: <ApartmentOutlined /> },
  { key: 'graph', label: 'Graph推理', icon: <ApartmentOutlined /> },
  { key: 'case', label: '用例生成', icon: <FileTextOutlined /> },
  { key: 'script', label: '脚本生成', icon: <CodeOutlined /> },
];

const statusIcon = (status: AIStep['status']) => {
  switch (status) {
    case 'running': return <LoadingOutlined spin style={{ color: '#1890ff' }} />;
    case 'success': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
    case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
    default: return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
  }
};

const statusColor = (status: AIStep['status']) => {
  switch (status) {
    case 'running': return '#1890ff';
    case 'success': return '#52c41a';
    case 'failed': return '#ff4d4f';
    default: return '#d9d9d9';
  }
};

export function AIStepTimeline({ steps, currentStepKey, compact = false }: AIStepTimelineProps) {
  const stepMap = new Map(steps.map(s => [s.key, s]));

  const items = STEP_DEFINITIONS.map(def => {
    const step = stepMap.get(def.key);
    const status = step?.status || (currentStepKey === def.key ? 'running' : 'pending');

    return {
      key: def.key,
      title: (
        <Space size="small">
          {statusIcon(status)}
          <Text strong={status === 'running'} style={{ color: statusColor(status), fontSize: compact ? 12 : 14 }}>
            {def.label}
          </Text>
          {step?.duration != null && <Tag style={{ fontSize: 10 }}>{step.duration}ms</Tag>}
        </Space>
      ),
      description: step && !compact ? (
        <div style={{ marginTop: 4 }}>
          {step.input && (
            <div style={{ fontSize: 11, color: '#8c8c8c', marginBottom: 2 }}>
              <Text type="secondary" style={{ fontSize: 10 }}>输入：</Text>{step.input}
            </div>
          )}
          {step.output && (
            <div style={{ fontSize: 11, color: '#52c41a' }}>
              <Text type="secondary" style={{ fontSize: 10 }}>输出：</Text>{step.output}
            </div>
          )}
        </div>
      ) : undefined,
    };
  });

  // 找到当前活跃步骤索引
  let currentIdx = -1;
  if (currentStepKey) {
    currentIdx = STEP_DEFINITIONS.findIndex(d => d.key === currentStepKey);
  } else {
    // 找最后一个 running 或第一个 pending
    for (let i = STEP_DEFINITIONS.length - 1; i >= 0; i--) {
      const step = stepMap.get(STEP_DEFINITIONS[i].key);
      if (step?.status === 'running') { currentIdx = i; break; }
    }
    if (currentIdx === -1) {
      for (let i = 0; i < STEP_DEFINITIONS.length; i++) {
        const step = stepMap.get(STEP_DEFINITIONS[i].key);
        if (!step || step.status === 'pending') { currentIdx = i; break; }
      }
    }
  }

  return (
    <Steps
      direction="vertical"
      size="small"
      current={currentIdx}
      items={items}
      style={{ padding: compact ? '0' : '8px 0' }}
    />
  );
}

/**
 * 从SSE消息列表构建AI步骤状态
 */
export function buildAIStepsFromSSE(sseMessages: { step: string; data?: any }[]): AIStep[] {
  const stepMapping: Record<string, { key: string; input?: string; output?: string }> = {
    '多模态解析开始': { key: 'multimodal', input: '多模态输入' },
    '多模态解析完成': { key: 'multimodal', output: '路由+推荐模式' },
    '多模态融合完成': { key: 'multimodal', output: '统一需求文本' },
    '类型识别完成': { key: 'classify', output: '自动分类结果' },
    '需求解析开始': { key: 'parse', input: '需求文本' },
    '需求解析完成': { key: 'parse', output: '意图+实体' },
    'RAG检索开始': { key: 'rag', input: '解析结果' },
    'RAG召回完成': { key: 'rag', output: '相关元素+历史脚本' },
    'Graph推理开始': { key: 'graph', input: 'RAG结果+页面结构' },
    'Graph推理完成': { key: 'graph', output: '业务流程+测试路径' },
    'Graph推理跳过': { key: 'graph', output: '跳过（无图谱数据）' },
    '测试用例生成开始': { key: 'case', input: '推理结果' },
    '测试用例生成完成': { key: 'case', output: '测试用例集' },
    '脚本生成开始': { key: 'script', input: '用例+元素定位器' },
    '脚本生成完成': { key: 'script', output: 'Playwright脚本' },
  };

  const stepStatusMap = new Map<string, AIStep>();

  for (const msg of sseMessages) {
    const mapping = stepMapping[msg.step];
    if (!mapping) continue;

    const existing = stepStatusMap.get(mapping.key);
    if (existing) {
      // 更新已有步骤
      if (msg.step.includes('完成') || msg.step.includes('跳过')) {
        existing.status = 'success';
        if (mapping.output) existing.output = mapping.output;
      } else if (msg.step.includes('开始')) {
        existing.status = 'running';
        if (mapping.input) existing.input = mapping.input;
      }
    } else {
      stepStatusMap.set(mapping.key, {
        key: mapping.key,
        label: STEP_DEFINITIONS.find(d => d.key === mapping.key)?.label || mapping.key,
        icon: STEP_DEFINITIONS.find(d => d.key === mapping.key)?.icon,
        status: msg.step.includes('完成') ? 'success' : msg.step.includes('失败') ? 'failed' : 'running',
        input: mapping.input,
        output: mapping.output,
      });
    }
  }

  return Array.from(stepStatusMap.values());
}
