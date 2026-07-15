/**
 * 一键测试页面
 *
 * 用户只需输入自然语言需求，系统自动完成全链路测试流程：
 * 需求理解 → 知识检索 → 用例生成 → 脚本生成 → 执行 → 报告 → 失败分析
 */
import { useState, useCallback } from 'react';
import {
  Card, Input, Button, Collapse, Tag, Alert, Spin,
  Result, Statistic, Descriptions, Typography, Space, Divider, Timeline
} from 'antd';
import {
  PlayCircleOutlined, CheckCircleOutlined, CloseCircleOutlined,
  LoadingOutlined, ExclamationCircleOutlined, ExperimentOutlined,
  BugOutlined, FileTextOutlined, SafetyOutlined
} from '@ant-design/icons';
import { oneClickRunSSE, type OneClickResponse } from '../../services/agentRuntime';

const { TextArea } = Input;
const { Title, Text, Paragraph } = Typography;
const { Panel } = Collapse;

interface PipelineStep {
  step: number;
  agent_type: string;
  action: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped';
  duration?: number;
  error?: string;
}

const STEP_LABELS: Record<string, string> = {
  requirement_agent: '需求理解',
  rag_agent: '知识检索',
  relation_agent: '关系发现',
  graph_agent: '图谱推理',
  flow_parser: '流程解析',
  case_agent: '用例生成',
  script_generator: '脚本生成',
  storage_agent: '脚本存储',
  execution_agent: '执行测试',
  report_agent: '生成报告',
  defect_agent: '缺陷分析',
  feedback_agent: '失败分析',
  flow_export_agent: '导出结果',
};

export default function OneClickTestPage() {
  const [requirement, setRequirement] = useState('');
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<PipelineStep[]>([]);
  const [result, setResult] = useState<OneClickResponse | null>(null);
  const [error, setError] = useState<string>('');

  const handleRun = useCallback(async () => {
    if (!requirement.trim()) return;

    setRunning(true);
    setError('');
    setSteps([]);
    setResult(null);

    await oneClickRunSSE(
      requirement,
      (event) => {
        const { event: eventType, data } = event;

        if (eventType === 'pipeline_start') {
          const initialSteps: PipelineStep[] = (data.steps || []).map((s: any, i: number) => ({
            step: i,
            agent_type: s.agent_type,
            action: s.action,
            status: 'pending',
          }));
          setSteps(initialSteps);
        } else if (eventType === 'step_start') {
          setSteps(prev => prev.map(s =>
            s.step === data.step ? { ...s, status: 'running' } : s
          ));
        } else if (eventType === 'step_completed') {
          setSteps(prev => prev.map(s =>
            s.step === data.step ? { ...s, status: 'completed', duration: data.duration } : s
          ));
        } else if (eventType === 'step_failed') {
          setSteps(prev => prev.map(s =>
            s.step === data.step ? { ...s, status: 'failed', error: data.error } : s
          ));
        } else if (eventType === 'step_skipped') {
          setSteps(prev => prev.map(s =>
            s.step === data.step ? { ...s, status: 'skipped' } : s
          ));
        } else if (eventType === 'reuse_hit') {
          // 复用命中
        } else if (eventType === 'one_click_result') {
          setResult(data as OneClickResponse);
        }
      },
      (err) => {
        setError(typeof err === 'string' ? err : err.message || '执行失败');
        setRunning(false);
      },
      () => {
        setRunning(false);
      },
    );
  }, [requirement]);

  const getStatusIcon = (status: PipelineStep['status']) => {
    switch (status) {
      case 'completed': return <CheckCircleOutlined style={{ color: '#52c41a' }} />;
      case 'failed': return <CloseCircleOutlined style={{ color: '#ff4d4f' }} />;
      case 'running': return <LoadingOutlined style={{ color: '#1890ff' }} />;
      case 'skipped': return <ExclamationCircleOutlined style={{ color: '#faad14' }} />;
      default: return <div style={{ width: 16, height: 16, borderRadius: '50%', border: '2px solid #d9d9d9' }} />;
    }
  };

  const completedSteps = steps.filter(s => s.status === 'completed').length;
  const totalSteps = steps.length;

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px' }}>
      <Card>
        <Space direction="vertical" style={{ width: '100%' }} size="large">
          <div>
            <Title level={3}><ExperimentOutlined /> 一键测试</Title>
            <Text type="secondary">输入自然语言测试需求，系统自动完成全链路测试流程</Text>
          </div>

          <div>
            <TextArea
              value={requirement}
              onChange={e => setRequirement(e.target.value)}
              placeholder="例如：测试商城: 1.打开首页 2.登录 3.搜索商品 4.加入购物车 5.提交订单"
              autoSize={{ minRows: 4, maxRows: 8 }}
              disabled={running}
            />
          </div>

          <div>
            <Button
              type="primary"
              size="large"
              icon={<PlayCircleOutlined />}
              onClick={handleRun}
              loading={running}
              disabled={!requirement.trim()}
            >
              {running ? '执行中...' : '一键运行'}
            </Button>
          </div>

          {error && (
            <Alert message="执行错误" description={error} type="error" showIcon closable onClose={() => setError('')} />
          )}
        </Space>
      </Card>

      {/* 执行进度 */}
      {(running || steps.length > 0) && (
        <Card style={{ marginTop: 16 }} title={
          <Space>
            <span>执行进度</span>
            {totalSteps > 0 && <Tag color="blue">{completedSteps}/{totalSteps}</Tag>}
          </Space>
        }>
          {running && <Spin tip="正在执行..." style={{ marginBottom: 16 }} />}
          <Timeline>
            {steps.map(s => (
              <Timeline.Item
                key={s.step}
                dot={getStatusIcon(s.status)}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Text strong>{STEP_LABELS[s.agent_type] || s.agent_type}</Text>
                  <Tag>{s.action}</Tag>
                  {s.status === 'completed' && s.duration != null && (
                    <Text type="secondary" style={{ fontSize: 12 }}>{s.duration.toFixed(2)}s</Text>
                  )}
                  {s.status === 'skipped' && <Tag color="orange">跳过</Tag>}
                  {s.status === 'failed' && <Tag color="red">失败</Tag>}
                </div>
                {s.error && <Text type="danger" style={{ fontSize: 12 }}>{s.error}</Text>}
              </Timeline.Item>
            ))}
          </Timeline>
        </Card>
      )}

      {/* 结果展示 */}
      {result && (
        <ResultSection result={result} />
      )}
    </div>
  );
}

function ResultSection({ result }: { result: OneClickResponse }) {
  const isFailed = result.status === 'failed';
  const execResult = result.execution_result;

  return (
    <div style={{ marginTop: 16 }}>
      {/* 整体状态 */}
      <Card style={{ marginBottom: 16 }}>
        <Result
          status={isFailed ? 'error' : 'success'}
          title={isFailed ? '测试失败' : '测试完成'}
          subTitle={result.message}
          extra={[
            <Statistic
              key="stats"
              title="总耗时"
              value={result.duration.toFixed(1)}
              suffix="秒"
              style={{ display: 'inline-block', marginRight: 32 }}
            />,
            execResult && (
              <Statistic
                key="pass"
                title="通过/失败"
                value={`${execResult.success_count}/${execResult.failed_count}`}
                style={{ display: 'inline-block' }}
              />
            ),
          ]}
        />
      </Card>

      {/* 需求分析 */}
      {result.requirement_analysis && (
        <Card title={<><FileTextOutlined /> 需求分析</>} style={{ marginBottom: 16 }}>
          <Collapse defaultActiveKey={['summary']}>
            <Panel header="需求摘要" key="summary">
              <Descriptions column={1} size="small">
                <Descriptions.Item label="意图">{result.requirement_analysis.intent}</Descriptions.Item>
                <Descriptions.Item label="概述">{result.requirement_analysis.summary}</Descriptions.Item>
                <Descriptions.Item label="目标URL">{result.requirement_analysis.target_url || '未识别'}</Descriptions.Item>
                <Descriptions.Item label="步骤">
                  <ol>
                    {result.requirement_analysis.steps?.map((s, i) => <li key={i}>{s}</li>)}
                  </ol>
                </Descriptions.Item>
              </Descriptions>
            </Panel>

            {result.requirement_analysis.business_flow && (
              <Panel header="业务流程" key="flow">
                <Title level={5}>{result.requirement_analysis.business_flow.name}</Title>
                <Paragraph>{result.requirement_analysis.business_flow.description}</Paragraph>
                {result.requirement_analysis.business_flow.stages?.map((stage, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <Tag color="blue">{stage.name}</Tag>
                    <Text type="secondary">{stage.actions?.join(' → ')}</Text>
                  </div>
                ))}
              </Panel>
            )}

            {result.requirement_analysis.test_points && result.requirement_analysis.test_points.length > 0 && (
              <Panel header={`测试点 (${result.requirement_analysis.test_points.length})`} key="points">
                {result.requirement_analysis.test_points.map((tp, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <Space>
                      <Tag color={
                        tp.priority === 'high' ? 'red' :
                        tp.priority === 'medium' ? 'orange' : 'green'
                      }>{tp.priority}</Tag>
                      <Tag>{tp.type}</Tag>
                      <Text strong>{tp.point}</Text>
                    </Space>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>{tp.description}</Text>
                  </div>
                ))}
              </Panel>
            )}

            {result.requirement_analysis.risk_points && result.requirement_analysis.risk_points.length > 0 && (
              <Panel header={`风险点 (${result.requirement_analysis.risk_points.length})`} key="risks">
                {result.requirement_analysis.risk_points.map((rp, i) => (
                  <div key={i} style={{ marginBottom: 8 }}>
                    <Space>
                      <Tag color={
                        rp.level === 'high' ? 'red' :
                        rp.level === 'medium' ? 'orange' : 'green'
                      }><SafetyOutlined /> {rp.level}</Tag>
                      <Text strong>{rp.risk}</Text>
                    </Space>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>影响: {rp.impact}</Text>
                    <br />
                    <Text type="secondary" style={{ fontSize: 12 }}>缓解: {rp.mitigation}</Text>
                  </div>
                ))}
              </Panel>
            )}
          </Collapse>
        </Card>
      )}

      {/* 执行结果 */}
      {execResult && (
        <Card title={<><CheckCircleOutlined /> 执行结果</>} style={{ marginBottom: 16 }}>
          <Descriptions column={2} bordered size="small">
            <Descriptions.Item label="状态">
              <Tag color={execResult.status === 'success' ? 'green' : 'red'}>
                {execResult.status}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="耗时">{execResult.duration?.toFixed(2)}s</Descriptions.Item>
            <Descriptions.Item label="成功步骤">{execResult.success_count}</Descriptions.Item>
            <Descriptions.Item label="失败步骤">{execResult.failed_count}</Descriptions.Item>
            {execResult.error_message && (
              <Descriptions.Item label="错误信息" span={2}>
                <Text type="danger">{execResult.error_message}</Text>
              </Descriptions.Item>
            )}
          </Descriptions>

          {execResult.log_content && (
            <div style={{ marginTop: 16 }}>
              <Divider>执行日志</Divider>
              <pre style={{
                background: '#1e1e1e', color: '#d4d4d4',
                padding: 12, borderRadius: 6, maxHeight: 300,
                overflow: 'auto', fontSize: 12, fontFamily: 'Consolas, monospace'
              }}>
                {execResult.log_content}
              </pre>
            </div>
          )}
        </Card>
      )}

      {/* 失败分析 */}
      {result.failure_analysis && (
        <Card title={<><BugOutlined /> 失败分析</>} style={{ marginBottom: 16, borderColor: '#ff4d4f' }}>
          <Alert
            message={result.failure_analysis.root_cause}
            type="error"
            showIcon
            style={{ marginBottom: 16 }}
          />

          {result.failure_analysis.failure_reasons.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Title level={5}>失败原因</Title>
              {result.failure_analysis.failure_reasons.map((r, i) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <Tag color="red">{i + 1}</Tag>
                  <Text>{r}</Text>
                </div>
              ))}
            </div>
          )}

          {result.failure_analysis.fix_suggestions.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <Title level={5}>修复建议</Title>
              {result.failure_analysis.fix_suggestions.map((s, i) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <Tag color="green">{i + 1}</Tag>
                  <Text>{s}</Text>
                </div>
              ))}
            </div>
          )}

          {result.failure_analysis.failed_steps.length > 0 && (
            <div>
              <Title level={5}>失败步骤</Title>
              {result.failure_analysis.failed_steps.map((s, i) => (
                <div key={i} style={{ marginBottom: 4 }}>
                  <Tag color="orange">{i + 1}</Tag>
                  <Text code style={{ fontSize: 12 }}>{s}</Text>
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {/* 脚本内容 */}
      {result.script_content && (
        <Card title="生成的脚本" style={{ marginBottom: 16 }}>
          <pre style={{
            background: '#f5f5f5', padding: 12, borderRadius: 6,
            maxHeight: 400, overflow: 'auto', fontSize: 12,
            fontFamily: 'Consolas, monospace'
          }}>
            {result.script_content}
          </pre>
        </Card>
      )}
    </div>
  );
}
