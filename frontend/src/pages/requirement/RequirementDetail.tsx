/**
 * 需求详情页（左需求 + 右分析结果）
 *
 * 核心原则：
 *   - 分析必须进入详情，禁止独立分析页
 *   - 左栏：需求内容
 *   - 右栏：分析结果（AI分析流水线）
 *   - 页面切换不丢数据（zustand持久化）
 */
import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card, Row, Col, Descriptions, Tag, Button, Space, Progress,
  Alert, Table, Empty, Spin, message,
} from 'antd';
import {
  RobotOutlined, CheckCircleOutlined, FileTextOutlined,
  DatabaseOutlined, ApartmentOutlined,
  ArrowRightOutlined,
} from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import { AIStepTimeline, buildAIStepsFromSSE } from '../../components/AIStepTimeline';

interface SSEMessage { step: string; progress: number; message: string; data?: any; }

export default function RequirementDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [requirement, setRequirement] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);
  const [sseMessages, setSseMessages] = useState<SSEMessage[]>([]);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState('');
  const [caseData, setCaseData] = useState<any>(null);
  const [ragData, setRagData] = useState<any>(null);
  const [graphData, setGraphData] = useState<any>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [analyzed, setAnalyzed] = useState(false);

  // 加载需求详情
  useEffect(() => {
    if (id && id !== 'new') {
      setLoading(true);
      fetch(`/api/requirement/${id}`, { credentials: 'include' })
        .then(res => res.json())
        .then(data => setRequirement(data.data || data))
        .catch(() => message.error('加载需求失败'))
        .finally(() => setLoading(false));
    }
  }, [id]);

  // 开始AI分析
  const handleAnalyze = async () => {
    if (!id) return;
    setAnalyzing(true);
    setSseMessages([]);
    setProgress(0);
    setCurrentStep('');
    setCaseData(null);
    setRagData(null);
    setGraphData(null);
    setTaskId(null);
    setAnalyzed(false);

    try {
      const response = await fetch(`/api/requirement/analyze/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
      });
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) { setAnalyzing(false); return; }
      let buffer = '';
      let sseTaskId: number | null = null;
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';
        for (const line of lines) {
          if (line.startsWith('data:')) {
            try {
              const data: SSEMessage = JSON.parse(line.slice(5).trim());
              setSseMessages(prev => [...prev, data]);
              if (data.progress) setProgress(prev => Math.max(prev, data.progress));
              setCurrentStep(data.step);
              if (data.step === 'RAG召回完成' && data.data) setRagData(data.data);
              if (data.step === 'Graph推理完成' && data.data) setGraphData(data.data);
              if (data.step === '测试用例生成完成' && data.data?.case) setCaseData(data.data.case);
              if (data.step === '脚本生成完成' && data.data?.task_id) {
                sseTaskId = data.data.task_id;
                setTaskId(data.data.task_id);
              }
              if (data.step === '任务完成' && data.data?.task_id) {
                sseTaskId = data.data.task_id;
                setTaskId(data.data.task_id);
              }
            } catch { /* ignore */ }
          }
        }
      }
      setAnalyzed(true);
      if (sseTaskId) message.success('AI分析完成');
    } catch (e: any) {
      message.error(e?.message || '分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  const hasResults = caseData || ragData || graphData;

  return (
    <div>
      <PageHeader
        title="需求详情"
        subtitle={requirement?.requirement?.slice(0, 60) || `需求 #${id}`}
        icon={<FileTextOutlined />}
      />
      <div style={{ marginBottom: 12 }}>
        <Space>
          {!analyzing && !analyzed && (
            <Button type="primary" icon={<RobotOutlined />} onClick={handleAnalyze}>
              开始AI分析
            </Button>
          )}
          {analyzing && (
            <Button disabled icon={<RobotOutlined />}>分析中...</Button>
          )}
          {analyzed && taskId && (
            <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(`/requirement/to-task/${taskId}`)}>
              转测试任务
            </Button>
          )}
        </Space>
      </div>
      <Row gutter={16}>
        {/* 左栏：需求内容 */}
        <Col xs={24} lg={10}>
          <Card size="small" title={<Space><FileTextOutlined /> 需求内容</Space>}>
            {loading ? <Spin /> : requirement ? (
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="ID">{requirement.id}</Descriptions.Item>
                <Descriptions.Item label="需求内容">
                  <div style={{ maxHeight: 300, overflow: 'auto', whiteSpace: 'pre-wrap' }}>
                    {requirement.requirement || requirement.raw_input || '-'}
                  </div>
                </Descriptions.Item>
                <Descriptions.Item label="状态">
                  <Tag color={requirement.status === 'completed' ? 'success' : 'processing'}>
                    {requirement.status || 'pending'}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="来源">
                  <Tag>{requirement.source_type || 'text'}</Tag>
                </Descriptions.Item>
                <Descriptions.Item label="创建时间">{requirement.created_at || '-'}</Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description="需求不存在" />
            )}
          </Card>
        </Col>

        {/* 右栏：分析结果 */}
        <Col xs={24} lg={14}>
          <Card size="small" title={<Space><RobotOutlined /> 分析结果</Space>}>
            {analyzing && (
              <div style={{ marginBottom: 16 }}>
                <Progress percent={progress} status="active" />
                {currentStep && <Alert message={currentStep} type="info" style={{ marginTop: 8 }} />}
              </div>
            )}
            {sseMessages.length > 0 ? (
              <AIStepTimeline steps={buildAIStepsFromSSE(sseMessages)} />
            ) : !analyzing && !hasResults ? (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#bfbfbf' }}>
                <RobotOutlined style={{ fontSize: 40 }} />
                <div style={{ marginTop: 8 }}>点击"开始AI分析"生成测试用例</div>
              </div>
            ) : null}
          </Card>

          {/* 用例结果 */}
          {caseData && (
            <Card size="small" title={<Space><CheckCircleOutlined /> 生成用例</Space>} style={{ marginTop: 12 }}>
              <Descriptions bordered size="small" column={1}>
                <Descriptions.Item label="名称">{caseData.case_name}</Descriptions.Item>
                {caseData.steps?.length > 0 && (
                  <Descriptions.Item label="步骤">
                    {caseData.steps.map((s: any, i: number) => (
                      <div key={i}><Tag color="blue" style={{ fontSize: 10 }}>{i + 1}</Tag>{typeof s === 'object' ? (s.step || JSON.stringify(s)) : String(s)}</div>
                    ))}
                  </Descriptions.Item>
                )}
              </Descriptions>
            </Card>
          )}

          {/* RAG结果 */}
          {ragData && ragData.elements?.length > 0 && (
            <Card size="small" title={<Space><DatabaseOutlined /> RAG检索 ({ragData.elements.length})</Space>} style={{ marginTop: 12 }}>
              <Table size="small" dataSource={ragData.elements.slice(0, 10)} rowKey={(_: any, i?: number) => String(i ?? 0)} pagination={false}
                columns={[{ title: '元素', dataIndex: 'name', width: 100 }, { title: '类型', dataIndex: 'type', width: 60, render: (v: string) => <Tag>{v}</Tag> }, { title: '定位器', dataIndex: 'locator', ellipsis: true }]} />
            </Card>
          )}

          {/* Graph结果 */}
          {graphData && (
            <Card size="small" title={<Space><ApartmentOutlined /> Graph推理</Space>} style={{ marginTop: 12 }}>
              <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 150, overflow: 'auto', fontSize: 11 }}>{JSON.stringify(graphData, null, 2)}</pre>
            </Card>
          )}
        </Col>
      </Row>
    </div>
  );
}
