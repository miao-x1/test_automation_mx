/**
 * 需求中心 — 输入工作台
 *
 * 三栏布局：
 *   左栏（输入）：多模态需求输入（文本/图片/URL/脚本）
 *   中栏（AI解析）：SSE时间线 + 进度
 *   右栏（生成结果）：用例/脚本/RAG/Graph预览
 */
import { useState, useCallback, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import {
  Card, Button, Space, Typography, Progress, Tag, Table, Descriptions, Tabs,
  message, Alert, Popconfirm, Row, Col, Tooltip,
} from 'antd';
import {
  RobotOutlined, CheckCircleOutlined, CloseCircleOutlined,
  FileTextOutlined, CodeOutlined, DatabaseOutlined, HistoryOutlined,
  SwapOutlined, ApartmentOutlined,
  CodeSandboxOutlined, CopyOutlined, EyeOutlined, ThunderboltOutlined,
  TagOutlined,
} from '@ant-design/icons';
import { getRequirementTasks, RequirementTask } from '../services/requirement';
import request from '../services/request';
import { detectTaskType, TYPE_LABELS } from '../services/taskTypeDetector';
import { StatusTag, PageHeader, EmptyGuide } from '../components/UI';
import { AIStepTimeline, buildAIStepsFromSSE } from '../components/AIStepTimeline';
import { PageRelationPanel } from '../components/PageRelationPanel';
import { RequirementInput } from '../components/RequirementInput';

const { Text } = Typography;

interface SSEMessage { step: string; progress: number; message: string; data?: any; }

const stepIconMap: Record<string, React.ReactNode> = {
  '多模态解析开始': <EyeOutlined />, '多模态解析完成': <CheckCircleOutlined />,
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

// ==================== 需求输入Tab ====================
function RequirementInputTab() {
  const navigate = useNavigate();
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
  // 用于PageRelationPanel的需求文本
  const [requirementText, setRequirementText] = useState('');
  const [additionalInfo, setAdditionalInfo] = useState('');

  const resetResults = () => {
    setSseMessages([]); setProgress(0); setCurrentStep('');
    setGeneratedScript('');
    setCaseData(null); setRagData(null); setGraphData(null);
    setReuseInfo(null); setTaskId(null); setStrategyInfo(null); setScriptQuality(0);
    setDetectedTypeInfo(null);
  };

  const reAnalyzeStarted = useRef(false);
  useEffect(() => {
    const reqId = (location.state as any)?.reAnalyzeReqId;
    if (reqId && !reAnalyzeStarted.current && !loading) {
      reAnalyzeStarted.current = true;
      navigate('/requirement', { replace: true, state: {} });
      handleSSE(`/api/requirement/analyze/${reqId}`, undefined, reqId);
    }
  }, [location.state]);

  // 多模态输入提交
  const handleMultiModalSubmit = useCallback(async (data: {
    text?: string;
    images?: string[];
    urls?: string[];
    script_content?: string;
    script_language?: string;
  }) => {
    // 判断是否为纯文本模式（向后兼容）
    const isTextOnly = !!data.text?.trim() && !data.images?.length && !data.urls?.length && !data.script_content?.trim();
    setRequirementText(data.text || '');
    setAdditionalInfo(data.urls?.join('\n') || '');

    if (isTextOnly) {
      // 纯文本：使用原有流程
      const typeResult = detectTaskType(data.text!.trim(), '');
      setLoading(true);
      try {
        const res: any = await request.post('/requirement/create', {
          requirement: data.text!.trim(),
          image_paths: undefined,
          script_format: 'playwright',
          task_type: typeResult.task_type,
          test_scope: typeResult.test_scope,
        });
        if (res.code === 200 && res.data?.id) {
          message.success(`需求任务创建成功（AI识别为${TYPE_LABELS[typeResult.task_type]}），正在启动分析...`);
          handleSSE(`/api/requirement/analyze/${res.data.id}`, undefined, res.data.id);
        } else {
          message.error(res.message || '创建失败');
          setLoading(false);
        }
      } catch (e: any) {
        message.error(e?.response?.data?.detail || '创建失败');
        setLoading(false);
      }
    } else {
      // 多模态：使用新的多模态流程
      setLoading(true);
      handleSSE('/api/requirement/generate_multimodal', {
        text: data.text || undefined,
        images: data.images || undefined,
        urls: data.urls || undefined,
        script_content: data.script_content || undefined,
        script_language: data.script_language || 'python',
        script_format: 'playwright',
      });
    }
  }, []);

  const handleSSE = async (url: string, body?: any, _reqTaskId?: number) => {
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
            } catch { /* ignore */ }
          }
        }
      }
      if (sseTaskId) {
        message.success('分析完成，跳转到任务详情...');
        navigate(`/web/task/${sseTaskId}`);
      }
    } catch (e: any) {
      message.error(e?.message || '请求失败');
    } finally {
      setLoading(false);
    }
  };

  const currentScript = generatedScript;
  const hasResults = caseData || generatedScript || ragData || graphData;

  // SSE步骤名 → AIStepTimeline key映射
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

  // ==================== 三栏布局 ====================
  return (
    <Row gutter={16}>
      {/* ===== 左栏：输入 ===== */}
      <Col xs={24} lg={8}>
        <RequirementInput onSubmit={handleMultiModalSubmit} loading={loading} />
        {/* 关联页面面板 */}
        {requirementText.trim() && (
          <PageRelationPanel
            requirement={requirementText.trim()}
            keywords={detectTaskType(requirementText.trim(), additionalInfo.trim()).reason.split(/[，,、]/).slice(0, 3)}
            targetUrl={additionalInfo.trim()}
          />
        )}
      </Col>

      {/* ===== 中栏：AI解析过程 ===== */}
      <Col xs={24} lg={8}>
        <Card size="small" title={<Space><RobotOutlined /> AI解析过程</Space>}>
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
              <div style={{ marginTop: 8 }}>输入需求后，AI解析过程将在此展示</div>
            </div>
          )}
        </Card>
        {detectedTypeInfo && (
          <Alert
            type="success"
            message={<Space><TagOutlined /> 自动类型识别</Space>}
            description={
              <Space wrap>
                <Tag color={detectedTypeInfo.task_type === 'web' ? 'blue' : detectedTypeInfo.task_type === 'api' ? 'purple' : detectedTypeInfo.task_type === 'android' ? 'green' : 'orange'}>
                  {TYPE_LABELS[detectedTypeInfo.task_type] || detectedTypeInfo.task_type}
                </Tag>
                <Text type="secondary">{detectedTypeInfo.reason}</Text>
                <Text type="secondary">置信度 {(detectedTypeInfo.confidence * 100).toFixed(0)}%</Text>
              </Space>
            }
            style={{ marginTop: 12 }}
            showIcon
          />
        )}
        {reuseInfo && (
          <Alert type="info" message={<Space><SwapOutlined /> 命中历史脚本</Space>} description={`相似度: ${reuseInfo.similarity ?? '-'}`} style={{ marginTop: 12 }} showIcon />
        )}
      </Col>

      {/* ===== 右栏：生成结果 ===== */}
      <Col xs={24} lg={8}>
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
                  {/* 策略与质量信息 */}
                  {strategyInfo && (
                    <div style={{ marginTop: 4, marginBottom: 4, display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                      <Tag color="blue" icon={<ThunderboltOutlined />}>
                        策略: {(strategyInfo.primary || 'playwright').toUpperCase()}
                      </Tag>
                      <Tag color={scriptQuality >= 0.7 ? 'green' : scriptQuality >= 0.4 ? 'orange' : 'red'}>
                        质量: {(scriptQuality * 100).toFixed(0)}%
                      </Tag>
                      {strategyInfo.degradation_chain?.length > 1 && (
                        <Tooltip title="主策略失败后的降级顺序">
                          <Tag color="default">
                            降级: {strategyInfo.degradation_chain.map((s: string) => s.toUpperCase()).join(' → ')}
                          </Tag>
                        </Tooltip>
                      )}
                      {strategyInfo.confidence != null && (
                        <Tag color="default">置信度: {(strategyInfo.confidence * 100).toFixed(0)}%</Tag>
                      )}
                    </div>
                  )}
                  <pre style={{ background: '#f5f5f5', padding: 8, borderRadius: 4, maxHeight: 200, overflow: 'auto', fontSize: 12, marginTop: 8 }}>{currentScript}</pre>
                  <Space size="small" style={{ marginTop: 4 }}>
                    <Button size="small" icon={<CopyOutlined />} onClick={() => { navigator.clipboard.writeText(currentScript); message.success('已复制'); }}>复制</Button>
                    {taskId && <Button type="primary" size="small" onClick={() => navigate(`/web/task/${taskId}`)}>前往任务详情</Button>}
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
  );
}

// ==================== 历史记录Tab ====================
function HistoryTab() {
  const navigate = useNavigate();
  const [history, setHistory] = useState<RequirementTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedReqKeys, setSelectedReqKeys] = useState<React.Key[]>([]);

  const fetchHistory = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getRequirementTasks() as any;
      const payload = res?.data || res;
      const items = Array.isArray(payload) ? payload : (payload?.items || []);
      setHistory(items);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { fetchHistory(); }, [fetchHistory]);

  const handleDeleteReq = async (id: number) => { try { await request.delete(`/requirement/${id}`); message.success('删除成功'); fetchHistory(); } catch { message.error('删除失败'); } };
  const handleReAnalyze = (record: RequirementTask) => { navigate('/requirement', { state: { reAnalyzeReqId: record.id } }); };

  return (
    <Card extra={<Space><Button icon={<HistoryOutlined />} onClick={fetchHistory} loading={loading}>刷新</Button></Space>}>
      {history.length === 0 && !loading ? (
        <EmptyGuide title="暂无需求记录" description="创建第一个测试需求开始" actionLabel="创建需求" actionTo="/requirement" />
      ) : (
        <Table columns={[
          { title: 'ID', dataIndex: 'id', width: 50 },
          { title: '需求', dataIndex: 'requirement', ellipsis: true },
          { title: '状态', dataIndex: 'status', width: 90, render: (s: string) => <StatusTag status={s} size="small" /> },
          { title: '关联任务', dataIndex: 'task_id', width: 80, render: (tid: number | null) => tid ? <Button type="link" size="small" onClick={() => navigate(`/web/task/${tid}`)}>#{tid}</Button> : '-' },
          { title: '时间', dataIndex: 'created_at', width: 150 },
          { title: '操作', width: 180, render: (_: unknown, r: RequirementTask) => (
            <Space size="small">
              {r.task_id && <Button type="link" size="small" onClick={() => navigate(`/web/task/${r.task_id}`)}>查看任务</Button>}
              <Button size="small" onClick={() => handleReAnalyze(r)}>重新分析</Button>
              <Popconfirm title="确定删除？" onConfirm={() => handleDeleteReq(r.id)} okText="确定" cancelText="取消">
                <Button size="small" danger>删除</Button>
              </Popconfirm>
            </Space>
          )},
        ]} dataSource={history} rowKey="id" loading={loading} pagination={{ pageSize: 20 }} rowSelection={{ selectedRowKeys: selectedReqKeys, onChange: setSelectedReqKeys }} />
      )}
    </Card>
  );
}

// ==================== 主组件 ====================
export default function RequirementCenter() {
  return (
    <div>
      <PageHeader
        title="需求中心"
        icon={<RobotOutlined />}
        subtitle="多模态输入测试需求，AI自动完成：解析 → 融合 → RAG检索 → 用例生成 → 脚本生成"
      />
      <Tabs defaultActiveKey="input" items={[
        { key: 'input', label: <Space><RobotOutlined /> 需求输入</Space>, children: <RequirementInputTab /> },
        { key: 'history', label: <Space><HistoryOutlined /> 历史记录</Space>, children: <HistoryTab /> },
      ]} />
    </div>
  );
}
