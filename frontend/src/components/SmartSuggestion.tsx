/**
 * 智能建议组件
 *
 * 执行失败后自动生成：
 * - 失败原因（结构化）
 * - 修复建议
 * - 自动修复按钮
 */
import { useState, useEffect } from 'react';
import { Card, Typography, Space, Tag, Button, Alert, Collapse, Spin, message } from 'antd';
import {
  BugOutlined, BulbOutlined, ToolOutlined, ThunderboltOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';
import request from '../services/request';

const { Text, Paragraph } = Typography;

export interface FailureAnalysis {
  root_cause: string;
  category: 'locator' | 'timing' | 'assertion' | 'environment' | 'network' | 'other';
  confidence: number;
  suggestions: Suggestion[];
  auto_fixable: boolean;
  auto_fix_description?: string;
}

export interface Suggestion {
  type: 'fix' | 'improve' | 'workaround';
  description: string;
  action?: string;
  confidence: number;
}

const categoryLabels: Record<string, { label: string; color: string }> = {
  locator: { label: '定位器问题', color: 'orange' },
  timing: { label: '时序问题', color: 'blue' },
  assertion: { label: '断言失败', color: 'purple' },
  environment: { label: '环境问题', color: 'red' },
  network: { label: '网络问题', color: 'cyan' },
  other: { label: '其他', color: 'default' },
};

interface SmartSuggestionProps {
  executionId: number;
  taskId: number;
  errorMessage?: string;
  onAutoFix?: () => void;
  onRerun?: () => void;
}

export function SmartSuggestion({ executionId, taskId, errorMessage, onAutoFix, onRerun }: SmartSuggestionProps) {
  const [analysis, setAnalysis] = useState<FailureAnalysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [fixing, setFixing] = useState(false);

  useEffect(() => {
    if (executionId) {
      fetchAnalysis();
    }
  }, [executionId]);

  const fetchAnalysis = async () => {
    setLoading(true);
    try {
      const res: any = await request.get(`/executions/${executionId}/analysis`);
      if (res.code === 200 && res.data) {
        setAnalysis(res.data);
      } else {
        // 后端暂不支持时，生成前端侧的基础分析
        setAnalysis(generateLocalAnalysis(errorMessage));
      }
    } catch {
      setAnalysis(generateLocalAnalysis(errorMessage));
    }
    setLoading(false);
  };

  const handleAutoFix = async () => {
    if (!analysis?.auto_fixable) return;
    setFixing(true);
    try {
      const res: any = await request.post(`/tasks/${taskId}/auto_fix`, { execution_id: executionId });
      if (res.code === 200) {
        message.success('自动修复完成，脚本已更新');
        onAutoFix?.();
      } else {
        message.error(res.message || '自动修复失败');
      }
    } catch {
      message.error('自动修复请求失败');
    }
    setFixing(false);
  };

  if (loading) {
    return (
      <Card size="small" style={{ borderColor: '#ff4d4f' }}>
        <Space><Spin size="small" /><Text>正在分析失败原因...</Text></Space>
      </Card>
    );
  }

  if (!analysis) return null;

  const catInfo = categoryLabels[analysis.category] || categoryLabels.other;

  return (
    <Card size="small" style={{ borderColor: '#ff4d4f' }}
      title={<Space><BugOutlined style={{ color: '#ff4d4f' }} /> 智能分析</Space>}
      extra={<Tag color={catInfo.color}>{catInfo.label}</Tag>}
    >
      {/* 根因 */}
      <Alert
        type="error"
        message={<Space><ExclamationCircleOutlined /> 根因分析</Space>}
        description={
          <div>
            <Paragraph style={{ margin: 0, fontSize: 13 }}>{analysis.root_cause}</Paragraph>
            {analysis.confidence > 0 && (
              <Text type="secondary" style={{ fontSize: 11 }}>置信度: {(analysis.confidence * 100).toFixed(0)}%</Text>
            )}
          </div>
        }
        showIcon={false}
        style={{ marginBottom: 12 }}
      />

      {/* 修复建议 */}
      {analysis.suggestions.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ display: 'block', marginBottom: 8 }}>
            <BulbOutlined style={{ color: '#faad14' }} /> 修复建议
          </Text>
          <Collapse ghost size="small" items={analysis.suggestions.map((s, i) => ({
            key: i,
            label: (
              <Space>
                <Tag color={s.type === 'fix' ? 'green' : s.type === 'improve' ? 'blue' : 'orange'}
                  style={{ fontSize: 10 }}>
                  {s.type === 'fix' ? '修复' : s.type === 'improve' ? '优化' : '绕行'}
                </Tag>
                <Text style={{ fontSize: 12 }}>{s.description}</Text>
              </Space>
            ),
            children: s.action ? (
              <div style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, fontSize: 12 }}>
                <Text code>{s.action}</Text>
              </div>
            ) : undefined,
          }))} />
        </div>
      )}

      {/* 操作按钮 */}
      <Space>
        {analysis.auto_fixable && (
          <Button type="primary" icon={<ToolOutlined />} loading={fixing} onClick={handleAutoFix} size="small">
            {analysis.auto_fix_description || '自动修复'}
          </Button>
        )}
        {onRerun && (
          <Button icon={<ThunderboltOutlined />} onClick={onRerun} size="small">
            一键复现
          </Button>
        )}
      </Space>
    </Card>
  );
}

/**
 * 前端侧基础失败分析（后端不支持时使用）
 */
function generateLocalAnalysis(errorMessage?: string): FailureAnalysis {
  const msg = errorMessage || '';

  // 简单规则匹配
  let category: FailureAnalysis['category'] = 'other';
  let rootCause = msg || '执行过程中发生未知错误';

  if (msg.includes('timeout') || msg.includes('Timeout') || msg.includes('超时')) {
    category = 'timing';
    rootCause = '页面元素加载超时，可能是网络延迟或元素未及时出现';
  } else if (msg.includes('selector') || msg.includes('定位') || msg.includes('not found') || msg.includes('No element')) {
    category = 'locator';
    rootCause = '元素定位器失效，页面结构可能已变更';
  } else if (msg.includes('assert') || msg.includes('AssertionError') || msg.includes('断言')) {
    category = 'assertion';
    rootCause = '断言验证失败，实际结果与预期不符';
  } else if (msg.includes('network') || msg.includes('ECONNREFUSED') || msg.includes('网络')) {
    category = 'network';
    rootCause = '网络连接异常，目标服务可能不可达';
  } else if (msg.includes('import') || msg.includes('Module') || msg.includes('环境')) {
    category = 'environment';
    rootCause = '运行环境异常，依赖模块缺失或配置错误';
  }

  const suggestions: Suggestion[] = [];
  if (category === 'locator') {
    suggestions.push(
      { type: 'fix', description: '重新分析页面元素，更新定位器', confidence: 0.8 },
      { type: 'improve', description: '使用更稳定的CSS选择器替代XPath', confidence: 0.6 },
    );
  } else if (category === 'timing') {
    suggestions.push(
      { type: 'fix', description: '增加等待时间或使用智能等待策略', confidence: 0.85 },
      { type: 'workaround', description: '添加重试机制', confidence: 0.7 },
    );
  } else if (category === 'assertion') {
    suggestions.push(
      { type: 'fix', description: '检查断言条件是否与当前页面状态匹配', confidence: 0.7 },
      { type: 'improve', description: '优化断言，使用更灵活的匹配策略', confidence: 0.6 },
    );
  } else {
    suggestions.push({ type: 'fix', description: '查看详细日志定位具体错误', confidence: 0.5 });
  }

  return {
    root_cause: rootCause,
    category,
    confidence: 0.6,
    suggestions,
    auto_fixable: category === 'locator' || category === 'timing',
    auto_fix_description: category === 'locator' ? '重新生成定位器' : category === 'timing' ? '优化等待策略' : undefined,
  };
}
