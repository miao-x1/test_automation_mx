/**
 * 任务理解层组件
 *
 * 在 TaskDetail 顶部显示 AI 对任务的理解：
 * - 需求摘要
 * - 测试目标拆解
 * - 风险点识别
 *
 * 使用前端本地生成，不依赖后端 /understanding 接口
 */
import { useState, useEffect } from 'react';
import { Card, Typography, Space, Tag, Row, Col } from 'antd';
import {
  RobotOutlined, AimOutlined, WarningOutlined,
  CheckCircleOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export interface TaskUnderstandingData {
  summary: string;
  objectives: string[];
  risks: string[];
  coverage_estimate?: number;
}

interface TaskUnderstandingProps {
  taskId: number;
  requirement?: string;
  pageUrl?: string;
}

export function TaskUnderstanding({ taskId, requirement, pageUrl }: TaskUnderstandingProps) {
  const [data, setData] = useState<TaskUnderstandingData | null>(null);

  useEffect(() => {
    if (taskId) {
      setData(generateLocalUnderstanding(requirement, pageUrl));
    }
  }, [taskId, requirement, pageUrl]);

  if (!data) return null;

  return (
    <Card size="small" style={{ marginBottom: 16, background: '#ffffff' }}
      title={<Space><RobotOutlined style={{ color: '#1c1c1c' }} /> AI任务理解</Space>}
      extra={data.coverage_estimate != null && (
        <Tag color="blue">预估覆盖率 {(data.coverage_estimate * 100).toFixed(0)}%</Tag>
      )}
    >
      <Row gutter={16}>
        {/* 需求摘要 */}
        <Col span={24} style={{ marginBottom: 12 }}>
          <Space align="start">
            <AimOutlined style={{ color: '#1c1c1c', marginTop: 2 }} />
            <div>
              <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>需求摘要</Text>
              <Paragraph style={{ margin: 0, fontSize: 13 }}>{data.summary}</Paragraph>
            </div>
          </Space>
        </Col>

        {/* 测试目标拆解 */}
        {data.objectives.length > 0 && (
          <Col xs={24} md={14} style={{ marginBottom: 12 }}>
            <Space align="start">
              <CheckCircleOutlined style={{ color: '#52c41a', marginTop: 2 }} />
              <div>
                <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>测试目标</Text>
                <div style={{ marginTop: 4 }}>
                  {data.objectives.map((obj, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', marginBottom: 4 }}>
                      <Tag color="green" style={{ fontSize: 10, minWidth: 20, textAlign: 'center' }}>{i + 1}</Tag>
                      <Text style={{ fontSize: 12 }}>{obj}</Text>
                    </div>
                  ))}
                </div>
              </div>
            </Space>
          </Col>
        )}

        {/* 风险点识别 */}
        {data.risks.length > 0 && (
          <Col xs={24} md={10}>
            <Space align="start">
              <WarningOutlined style={{ color: '#faad14', marginTop: 2 }} />
              <div>
                <Text strong style={{ fontSize: 12, color: '#8c8c8c' }}>风险点</Text>
                <div style={{ marginTop: 4 }}>
                  {data.risks.map((risk: string, i: number) => (
                    <div key={i} style={{ marginBottom: 4 }}>
                      <Tag color="warning" style={{ fontSize: 10 }}>风险</Tag>
                      <Text style={{ fontSize: 12 }}>{risk}</Text>
                    </div>
                  ))}
                </div>
              </div>
            </Space>
          </Col>
        )}
      </Row>
    </Card>
  );
}

/**
 * 前端侧基础任务理解（后端不支持时使用）
 */
function generateLocalUnderstanding(requirement?: string, pageUrl?: string): TaskUnderstandingData {
  const objectives: string[] = [];
  const risks: string[] = [];

  if (requirement) {
    objectives.push(`验证${requirement}的核心功能`);
    objectives.push('检查页面关键元素的可访问性');
    objectives.push('验证用户交互流程的完整性');

    if (requirement.includes('登录') || requirement.includes('注册')) {
      objectives.push('验证表单验证逻辑');
      risks.push('登录/注册涉及敏感数据，需注意数据安全');
    }
    if (requirement.includes('搜索')) {
      objectives.push('验证搜索结果的相关性');
      risks.push('搜索结果可能因数据量不同而不稳定');
    }
    if (requirement.includes('购物车') || requirement.includes('订单')) {
      objectives.push('验证价格计算准确性');
      risks.push('涉及金额计算，断言需精确');
    }
  }

  if (pageUrl) {
    risks.push('页面结构变更可能导致定位器失效');
    risks.push('网络延迟可能导致超时');
  }

  if (risks.length === 0) {
    risks.push('页面动态内容可能导致测试不稳定');
  }

  return {
    summary: requirement || '自动化测试任务',
    objectives,
    risks,
    coverage_estimate: 0.7,
  };
}
