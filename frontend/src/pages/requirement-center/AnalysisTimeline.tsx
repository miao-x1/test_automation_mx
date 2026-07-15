import React from 'react';
import {
  Timeline,
  Card,
  Tag,
  Collapse,
  Descriptions,
  Alert,
  Empty,
  Typography,
  Space,
  Statistic,
  Row,
  Col,
} from 'antd';
import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  LoadingOutlined,
  PlayCircleOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons';

const { Text, Paragraph } = Typography;

export interface TimelineStep {
  name: string;
  display: string;
  status: 'pending' | 'running' | 'completed' | 'failed';
  duration?: number;
  output?: any;
  error?: string;
  started_at?: number;
  completed_at?: number;
}

export interface AnalysisResult {
  summary?: any;
  review?: any;
  questions?: any[];
  final_requirement?: string;
  needs_input?: boolean;
}

interface AnalysisTimelineProps {
  steps: TimelineStep[];
  analyzing: boolean;
  result: AnalysisResult | null;
  reviewQuestions: any[];
}

const AnalysisTimeline: React.FC<AnalysisTimelineProps> = ({
  steps,
  analyzing,
  reviewQuestions,
}) => {
  const getIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'running':
        return <LoadingOutlined style={{ color: '#1890ff' }} />;
      case 'failed':
        return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case 'pending':
        return <ClockCircleOutlined style={{ color: '#d9d9d9' }} />;
      default:
        return <PlayCircleOutlined />;
    }
  };

  const getColor = (status: string) => {
    switch (status) {
      case 'completed': return 'green';
      case 'running': return 'blue';
      case 'failed': return 'red';
      default: return 'gray';
    }
  };

  const formatDuration = (seconds?: number) => {
    if (!seconds) return '';
    if (seconds < 1) return `${(seconds * 1000).toFixed(0)}ms`;
    return `${seconds.toFixed(2)}s`;
  };

  const renderStepContent = (step: TimelineStep) => {
    if (!step.output && !step.error) return null;

    const items: React.ReactNode[] = [];

    if (step.error) {
      items.push(
        <Alert key="error" type="error" message={step.error} style={{ marginTop: 8 }} />
      );
    }

    if (step.output) {
      const out = step.output;

      // 图片分析
      if (out.type === 'image_analysis' || (out.results && out.file_count !== undefined)) {
        items.push(
          <Descriptions key="img" size="small" column={3} bordered style={{ marginTop: 8 }}>
            <Descriptions.Item label="文件数">{out.file_count}</Descriptions.Item>
            <Descriptions.Item label="元素总数">{out.total_elements || 0}</Descriptions.Item>
          </Descriptions>
        );
        if (out.results) {
          out.results.forEach((r: any, i: number) => {
            if (r.elements && r.elements.length > 0) {
              items.push(
                <div key={`el-${i}`} style={{ marginTop: 4 }}>
                  <Text type="secondary">{r.file}: </Text>
                  <Text>{r.elements.length} 个元素</Text>
                </div>
              );
            }
          });
        }
      }

      // 需求分析
      if (out.type === 'requirement_analysis') {
        items.push(
          <Descriptions key="req" size="small" column={2} bordered style={{ marginTop: 8 }}>
            <Descriptions.Item label="意图">{out.intent || '-'}</Descriptions.Item>
            <Descriptions.Item label="目标URL">{out.target_url || '-'}</Descriptions.Item>
          </Descriptions>
        );
        if (out.summary) {
          items.push(<Paragraph key="sum" style={{ marginTop: 8 }}>{out.summary}</Paragraph>);
        }
        if (out.steps && out.steps.length > 0) {
          items.push(
            <div key="steps" style={{ marginTop: 8 }}>
              <Text type="secondary">步骤：</Text>
              {out.steps.map((s: string, i: number) => (
                <Tag key={i} style={{ marginBottom: 4 }}>{s}</Tag>
              ))}
            </div>
          );
        }
      }

      // URL分析
      if (out.type === 'url_analysis') {
        items.push(
          <Descriptions key="url" size="small" column={2} bordered style={{ marginTop: 8 }}>
            <Descriptions.Item label="URL数">{out.url_count}</Descriptions.Item>
            <Descriptions.Item label="元素总数">{out.total_elements || 0}</Descriptions.Item>
          </Descriptions>
        );
      }

      // Schema分析
      if (out.type === 'schema_analysis') {
        items.push(
          <Descriptions key="schema" size="small" column={2} bordered style={{ marginTop: 8 }}>
            <Descriptions.Item label="文件数">{out.file_count}</Descriptions.Item>
          </Descriptions>
        );
      }

      // 整合结果
      if (step.name === 'merge' && out.requirement_text) {
        items.push(
          <Card key="merge" size="small" style={{ marginTop: 8 }} title="整合结果">
            <Row gutter={16}>
              <Col span={6}>
                <Statistic title="页面元素" value={out.page_elements?.length || 0} />
              </Col>
              <Col span={6}>
                <Statistic title="业务流程" value={out.business_flows?.length || 0} />
              </Col>
              <Col span={6}>
                <Statistic title="测试目标" value={out.test_goals?.length || 0} />
              </Col>
              <Col span={6}>
                <Statistic title="风险点" value={out.risk_points?.length || 0} />
              </Col>
            </Row>
            <Paragraph style={{ marginTop: 8 }}>{out.requirement_text}</Paragraph>
            {out.risk_points?.map((r: any, i: number) => (
              <Tag key={i} color={r.level === 'high' ? 'red' : r.level === 'medium' ? 'orange' : 'green'}>
                {r.risk}
              </Tag>
            ))}
          </Card>
        );
      }

      // 评审结果
      if (step.name === 'review' && out.completeness !== undefined) {
        items.push(
          <Card key="review" size="small" style={{ marginTop: 8 }} title="评审结果">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="完整性"
                  value={out.completeness}
                  suffix=""
                  valueStyle={{ color: out.completeness > 0.6 ? '#3f8600' : '#cf1322' }}
                />
              </Col>
            </Row>
            {out.missing_items?.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <Text type="warning">缺失项：</Text>
                {out.missing_items.map((m: string, i: number) => (
                  <Tag key={i} color="orange">{m}</Tag>
                ))}
              </div>
            )}
            <Paragraph style={{ marginTop: 8 }} type="secondary">
              {out.review_summary}
            </Paragraph>
          </Card>
        );
      }

      // Agents 列表
      if (out.agents && Array.isArray(out.agents)) {
        items.push(
          <div key="agents" style={{ marginTop: 8 }}>
            <Space wrap>
              {out.agents.map((a: string, i: number) => (
                <Tag key={i} color="blue">{a}</Tag>
              ))}
            </Space>
          </div>
        );
      }
    }

    if (items.length === 0) return null;

    return (
      <Collapse
        ghost
        items={[{
          key: '1',
          label: <Text type="secondary" style={{ fontSize: 12 }}>展开详情</Text>,
          children: items,
        }]}
        style={{ marginTop: 4 }}
      />
    );
  };

  return (
    <Card title="AI理解过程" style={{ marginTop: 16 }}>
      {steps.length === 0 && !analyzing ? (
        <Empty description="点击「开始AI分析」后，AI理解过程将在这里实时展示" />
      ) : (
        <>
          <Timeline
            items={steps.map((step) => ({
              dot: getIcon(step.status),
              color: getColor(step.status),
              children: (
                <div>
                  <Space>
                    <Text strong>{step.display}</Text>
                    {step.duration && (
                      <Tag>{formatDuration(step.duration)}</Tag>
                    )}
                    <Tag color={getColor(step.status)}>
                      {step.status === 'completed' ? '完成' :
                       step.status === 'running' ? '分析中' :
                       step.status === 'failed' ? '失败' : '等待'}
                    </Tag>
                  </Space>
                  {renderStepContent(step)}
                </div>
              ),
            }))}
          />

          {/* 评审问题 */}
          {reviewQuestions.length > 0 && (
            <Alert
              type="warning"
              icon={<ExclamationCircleOutlined />}
              message="AI需要您补充以下信息"
              description={
                <Space direction="vertical" style={{ width: '100%' }}>
                  {reviewQuestions.map((q: any, i: number) => (
                    <div key={i}>
                      <Text strong>{q.question_text || q.question}</Text>
                      {q.required && <Tag color="red" style={{ marginLeft: 8 }}>必填</Tag>}
                    </div>
                  ))}
                </Space>
              }
              style={{ marginTop: 16 }}
            />
          )}
        </>
      )}
    </Card>
  );
};

export default AnalysisTimeline;
