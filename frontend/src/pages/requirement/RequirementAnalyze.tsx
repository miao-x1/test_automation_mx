/**
 * 需求模块 - 需求分析（AI）
 *
 * AI分析流水线：解析→类型识别→RAG→Graph→用例→脚本
 * 输入层：只分析，不执行。分析完成后跳转到"需求转测试任务"
 */
import { useState, useEffect } from 'react';
import { useNavigate, useParams, useLocation } from 'react-router-dom';
import {
  Card, Button, Space, Typography, Progress, Tag, Table, Descriptions,
  message, Alert, Row, Col, Tooltip,
} from 'antd';
import {
  RobotOutlined, CheckCircleOutlined, CloseCircleOutlined,
  FileTextOutlined, CodeOutlined, DatabaseOutlined,
  SwapOutlined, ApartmentOutlined,
  CodeSandboxOutlined, CopyOutlined, ThunderboltOutlined,
  TagOutlined, ArrowRightOutlined,
} from '@ant-design/icons';
import { PageHeader } from '../../components/UI';
import { AIStepTimeline, buildAIStepsFromSSE } from '../../components/AIStepTimeline';

const { Text } = Typography;

interface SSEMessage { step: string; progress: number; message: string; data?: any; }

const stepIconMap: Record<string, React.ReactNode> = {
  '多模态解析开始': <CodeSandboxOutlined />, '多模态解析完成': <CheckCircleOutlined />,
  '多模态融合完成': <ThunderboltOutlined />,
  '类型识别完成': <TagOutlined />,
  '需求解析开始': <RobotOutlined />, '需求解析完成': <CheckCircleOutlined />,
  '脚本复用检查': <SwapOutlined />, '命中历史脚本': <SwapOutlined />,
  'RAG检索开始': <DatabaseOutlined />, 'RAG召回完成': <DatabaseOutlined />,
  '页面关联发现': <ApartmentOutlined />, '页面关联完成': <ApartmentOutlined />, '页面关联跳过': <ApartmentOutlined />,
  'Graph推理开始': <ApartmentOutlined />, 'Graph推理完成': <ApartmentOutlined />, 'Graph推理跳过': <ApartmentOutlined />,
  '测试用例生成开始': <FileTextOutlined />, '测试用例生成完成': <FileTextOutlined />,
  '脚本生成开始': <CodeOutlined />, '策略选择完成': <ThunderboltOutlined />, '脚本生成完成': <CodeOutlined />,
  '任务完成': <CheckCircleOutlined />, '任务失败': <CloseCircleOutlined />,
};

export default function RequirementAnalyze() {
  const navigate = useNavigate();
  const { id } = useParams();
  const location = useLocation();
  const [loading, setLoading] = useState(false);
  const [sseMessages, setSseMessages] = useState<SSEMessage[]>([]);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState('');
  const [generatedScript, setGeneratedScript] = useState('');
  const [caseData, setCaseData] = useState<any>(null);
  const [ragData, setRagData] = useState<any>(null);
  const [graphData, setGraphData] = useState<any>(null);
  const [reuseInfo, setReuseInfo] = useState<any>(null);
  const [taskId, setTaskId] = useState<number | null>(null);
  const [strategyInfo, setStrategyInfo] = useState<any>(null);
  const [scriptQuality, setScriptQuality] = useState<number>(0);
  const [detectedTypeInfo, setDetectedTypeInfo] = useState<any>(null);
  const [analyzed, setAnalyzed] = useState(false);

  const resetResults = () => {
    setSseMessages([]); setProgress(0); setCurrentStep('');
    setGeneratedScript('');
    setCaseData(null); setRagData(null); setGraphData(null);
    setReuseInfo(null); setTaskId(null); setStrategyInfo(null); setScriptQuality(0);
    setDetectedTypeInfo(null); setAnalyzed(false);
  };

  // 自动开始分析
  useEffect(() => {
    if (id && id !== 'new' && !loading && !analyzed) {
      handleSSE(`/api/requirement/analyze/${id}`);
    }
    // 多模态数据从 location.state 传入
    const multimodalData = (location.state as any)?.multimodalData;
    if (id === 'new' && multimodalData && !loading && !analyzed) {
      handleSSE('/api/requirement/generate_multimodal', {
        text: multimodalData.text || undefined,
        images: multimodalData.images || undefined,
        urls: multimodalData.urls || undefined,
        script_content: multimodalData.script_content || undefined,
        script_language: multimodalData.script_language || 'python',
        script_format: 'playwright',
      });
    }
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSSE = async (url: string, body?: any) => {
    setLoading(true);
    resetResults();
    try {
      const opts: RequestInit = { method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'include' };
      if (body) opts.body = JSON.stringify(body);
      const response = await fetch(url, opts);
      if (!response.ok) throw new Error(`请求失败 (${response.status})`);
      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      if (!reader) { setLoading(false); return; }
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
              if (data.step === '类型识别完成' && data.data) setDetectedTypeInfo(data.data);
              if (data.step === 'Graph推理完成' && data.data) setGraphData(data.data);
              if (data.step === '命中历史脚本' && data.data) setReuseInfo(data.data);
              if (data.step === '测试用例生成完成' && data.data?.case) setCaseData(data.data.case);
              if (data.step === '策略选择完成' && data.data) {
                setStrategyInfo(data.data.strategy);
                setScriptQuality(data.data.script_quality || 0);
              }
              if (data.step === '脚本生成完成' && data.data?.script_preview) {
                setGeneratedScript(data.data.script_preview);
                if (data.data.task_id) { sseTaskId = data.data.task_id; setTaskId(data.data.task_id); }
                if (data.data.script_quality) setScriptQuality(data.data.script_quality);
                if (data.data.strategy_used) setStrategyInfo(data.data.strategy_used);
              }
              if (data.step === '任务完成' && data.data?.task_id) {
                sseTaskId = data.data.task_id;
                setTaskId(data.data.task_id);
              }
            } catch { /* ignore SSE parse error */ }
          }
        }
      }
      setAnalyzed(true);
      if (sseTaskId) {
        message.success('AI分析完成，可转测试任务');
      }
    } catch (e: any) {
      message.error(e?.message || '分析失败');
    } finally {
      setLoading(false);
    }
  };

  const getCurrentStepKey = (step: string): string | undefined => {
    if (!step) return undefined;
    if (step.includes('多模态')) return 'multimodal';
    if (step.includes('类型识别')) return 'classify';
    if (step.includes('需求解析')) return 'parse';
    if (step.includes('RAG') || step.includes('检索')) return 'rag';
    if (step.includes('页面关联')) return 'relation';
    if (step.includes('Graph') || step.includes('推理')) return 'graph';
    if (step.includes('用例')) return 'case';
    if (step.includes('脚本')) return 'script';
    return undefined;
  };

  const hasResults = caseData || generatedScript || ragData || graphData;

  return (
    <div>
      <PageHeader title="需求分析" subtitle="AI自动解析需求，生成测试用例和脚本" icon={<RobotOutlined />} />
      <Row gutter={16}>
        {/* 左栏：AI解析过程 */}
        <Col xs={24} lg={12}>
          <Card size="small" title={<Space><RobotOutlined /> AI分析流水线</Space>}
            extra={analyzed && taskId && (
              <Button type="primary" icon={<ArrowRightOutlined />} onClick={() => navigate(`/requirement/to-task/${taskId}`)}>
                转测试任务
              </Button>
            )}
          >
            {loading && (
              <div style={{ marginBottom: 16 }}>
                <Progress percent={progress} status="active" />
                {currentStep && <Alert message={<Space>{stepIconMap[currentStep] || <RobotOutlined />}<Text strong>{currentStep}</Text></Space>} type="info" showIcon={false} style={{ marginTop: 8 }} />}
              </div>
            )}
            {sseMessages.length > 0 ? (
              <AIStepTimeline steps={buildAIStepsFromSSE(sseMessages)} currentStepKey={getCurrentStepKey(currentStep)} />
            ) : !loading && (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#bfbfbf' }}>
                <RobotOutlined style={{ fontSize: 40 }} />
                <div style={{ marginTop: 8 }}>等待开始分析...</div>
              </div>
            )}
          </Card>
          {detectedTypeInfo && (
            <Alert type="success" message={<Space><TagOutlined /> 自动类型识别</Space>}
              description={<Space wrap><Tag color={detectedTypeInfo.task_type === 'web' ? 'blue' : 'purple'}>{detectedTypeInfo.task_type}</Tag><Text type="secondary">{detectedTypeInfo.reason}</Text></Space>}
              style={{ marginTop: 12 }} showIcon />
          )}
          {reuseInfo && (
            <Alert type="info" message={<Space><SwapOutlined /> 命中历史脚本</Space>} description={`相似度: ${reuseInfo.similarity ?? '-'}`} style={{ marginTop: 12 }} showIcon />
          )}
        </Col>

        {/* 右栏：生成结果 */}
        <Col xs={24} lg={12}>
          <Card size="small" title={<Space><CheckCircleOutlined /> 生成结果</Space>}>
            {hasResults ? (
              <div style={{ maxHeight: 700, overflow: 'auto' }}>
                {caseData && (
                  <div style={{ marginBottom: 16 }}>
                    <Text strong><FileTextOutlined /> 测试用例</Text>
                    <Descriptions bordered size="small" column={1} style={{ marginTop: 8 }}>
                      <Descriptions.Item label="名称">{caseData.case_name}</Descriptions.Item>
                      {caseData.steps?.length > 0 && <Descriptions.Item label="步骤">{caseData.steps.map((s: any, i: number) => <div key={i}><Tag color="blue" style={{ fontSize: 10 }}>{i + 1}</Tag>{typeof s === 'object' ? (s.step || JSON.stringify(s)) : String(s)}</div>)}</Descriptions.Item>}
                    </Descriptions>
                  </div>
                )}
                {generatedScript && (
                  <div style={{ marginBottom: 16 }}>
                    <Text strong><CodeOutlined /> 生成脚本</Text>
                    {strategyInfo && (
                      <div style={{ marginTop: 4, marginBottom: 4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                        <Tag color="blue" icon={<ThunderboltOutlined />}>策略: {(strategyInfo.primary || 'playwright').toUpperCase()}</Tag>
                        <Tag color={scriptQuality >= 0.7 ? 'green' : scriptQuality >= 0.4 ? 'orange' : 'red'}>质量: {(scriptQuality * 100).toFixed(0)}%</Tag>
                        {strategyInfo.degradation_chain?.length > 1 && (
                          <Tooltip title="降级顺序"><Tag color="default">降级: {strategyInfo.degradation_chain.map((s: string) => s.toUpperCase()).join(' → ')}</Tag></Tooltip>
                        )}
                      </div>
                    )}
                    <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto', fontSize: 12, marginTop: 8 }}>{generatedScript}</pre>
                    <Space size="small" style={{ marginTop: 4 }}>
                      <Button size="small" icon={<CopyOutlined />} onClick={() => { navigator.clipboard.writeText(generatedScript); message.success('已复制'); }}>复制</Button>
                    </Space>
                  </div>
                )}
                {ragData && ragData.elements?.length > 0 && (
                  <div style={{ marginBottom: 16 }}>
                    <Text strong><DatabaseOutlined /> RAG检索 ({ragData.elements.length})</Text>
                    <Table size="small" dataSource={ragData.elements.slice(0, 10)} rowKey={(_: any, i: number | undefined) => String(i ?? 0)} pagination={false} style={{ marginTop: 8 }}
                      columns={[{ title: '元素', dataIndex: 'name', width: 100 }, { title: '类型', dataIndex: 'type', width: 60, render: (v: string) => <Tag>{v}</Tag> }, { title: '定位器', dataIndex: 'locator', ellipsis: true }]} />
                  </div>
                )}
                {graphData && (
                  <div>
                    <Text strong><ApartmentOutlined /> Graph推理</Text>
                    <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 150, overflow: 'auto', fontSize: 11, marginTop: 8 }}>{JSON.stringify(graphData, null, 2)}</pre>
                  </div>
                )}
              </div>
            ) : (
              <div style={{ textAlign: 'center', padding: '40px 0', color: '#bfbfbf' }}>
                <CodeSandboxOutlined style={{ fontSize: 40 }} />
                <div style={{ marginTop: 8 }}>分析结果将在此展示</div>
              </div>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
