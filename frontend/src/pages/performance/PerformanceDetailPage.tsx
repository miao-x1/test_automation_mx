/**
 * 性能测试 - 任务详情页
 *
 * 路由: /performance/:id
 *
 * 功能:
 *   1. 概览: 任务基本信息 (Descriptions)
 *   2. 测试方案: 方案 JSON + 关键参数 (Descriptions + pre)
 *   3. 执行监控: 启动/停止执行 + SSE 实时指标图表 (TPS/RT/CPU/Memory/错误数)
 *   4. 执行结果: 结果表格 + 指标图表 (recharts) + 汇总统计
 *   5. 脚本: script_content 源码展示 (pre + monospace)
 *   6. 运行分析: AI 性能分析结果 (评分 / 摘要 / 瓶颈 / 建议 / 结论)
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card,
  Descriptions,
  Tabs,
  Tag,
  Statistic,
  Row,
  Col,
  Spin,
  Button,
  message,
  Empty,
  Table,
  Space,
  Typography,
  List,
  Alert,
  Progress,
} from 'antd';
import {
  ArrowLeftOutlined,
  ThunderboltOutlined,
  ReloadOutlined,
  BarChartOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useParams, useNavigate } from 'react-router-dom';
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  BarChart,
  Bar,
  Area,
  AreaChart,
} from 'recharts';
import {
  getTask,
  getResults,
  getMetrics,
  runAnalysis,
  executeTask,
  stopExecute,
  getExecuteStatus,
  streamExecuteMetrics,
  type PerformanceTask,
  type PerformanceResult,
  type PerformanceMetric,
  type MetricEvent,
} from '@/services/performance';

const { Text, Paragraph } = Typography;

// 测试类型中文名
const TEST_TYPE_TEXT: Record<string, string> = {
  api: 'API 测试',
  web: 'Web 测试',
};

// 状态对应的颜色 / 文本
const STATUS_META: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待处理' },
  planning: { color: 'blue', text: '方案生成中' },
  scripting: { color: 'cyan', text: '脚本生成中' },
  running: { color: 'processing', text: '执行中' },
  completed: { color: 'green', text: '已完成' },
  failed: { color: 'red', text: '失败' },
  stopped: { color: 'orange', text: '已停止' },
};

// 分析结论 verdict 颜色
const VERDICT_META: Record<string, { color: string; text: string }> = {
  pass: { color: 'green', text: '通过' },
  excellent: { color: 'green', text: '优秀' },
  good: { color: 'green', text: '良好' },
  warning: { color: 'orange', text: '告警' },
  acceptable: { color: 'orange', text: '可接受' },
  fail: { color: 'red', text: '不通过' },
  poor: { color: 'red', text: '较差' },
};

// 兼容后端返回结构: { items, total } | { data, total } | {code, data:{items,total}} | 数组
function normalizeResults(res: any): PerformanceResult[] {
  if (Array.isArray(res)) return res;
  // 解包 {code, message, data: ...} 信封格式
  const payload = res?.data ?? res;
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.list || [];
}

// 兼容后端指标返回结构: { items, total } | { data, total } | {code, data:{items,total}} | 数组
function normalizeMetrics(res: any): PerformanceMetric[] {
  if (Array.isArray(res)) return res;
  // 解包 {code, message, data: ...} 信封格式
  const payload = res?.data ?? res;
  if (Array.isArray(payload)) return payload;
  return payload?.items || payload?.list || [];
}

// 从原始响应中提取分析结果
interface AnalysisInfo {
  score?: number | null;
  summary?: string | null;
  bottlenecks?: string[] | null;
  recommendations?: string[] | null;
  verdict?: string | null;
}
function extractAnalysis(raw: any): AnalysisInfo | null {
  if (!raw) return null;
  const a = raw.analysis ?? raw;
  if (!a || typeof a !== 'object') return null;
  const pickList = (v: unknown): string[] | null => {
    if (Array.isArray(v)) return v.map((x) => (typeof x === 'string' ? x : JSON.stringify(x)));
    return null;
  };
  return {
    score: a.score ?? a.score_overall ?? a.overall_score ?? null,
    summary: a.summary ?? a.conclusion ?? a.summary_text ?? null,
    bottlenecks: pickList(a.bottlenecks) ?? pickList(a.bottleneck) ?? pickList(a.issues) ?? null,
    recommendations: pickList(a.recommendations) ?? pickList(a.recommendation) ?? pickList(a.suggestions) ?? null,
    verdict: a.verdict ?? a.result ?? a.grade ?? a.level ?? null,
  };
}

// 格式化错误率 (兼容 0-1 与 0-100)
function formatErrorRate(rate: number): string {
  if (rate == null || isNaN(rate)) return '-';
  const v = rate > 1 ? rate : rate * 100;
  return `${v.toFixed(2)}%`;
}

export default function PerformanceDetailPage() {
  const navigate = useNavigate();
  const { id } = useParams<{ id: string }>();
  const taskId = Number(id);

  const [loading, setLoading] = useState(false);
  const [task, setTask] = useState<PerformanceTask | null>(null);

  // 结果列表
  const [results, setResults] = useState<PerformanceResult[]>([]);
  const [resultsLoading, setResultsLoading] = useState(false);

  // 选中结果与其指标
  const [selectedResult, setSelectedResult] = useState<PerformanceResult | null>(null);
  const [metrics, setMetrics] = useState<PerformanceMetric[]>([]);
  const [metricsLoading, setMetricsLoading] = useState(false);

  // 运行分析
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisRaw, setAnalysisRaw] = useState<any>(null);

  // 执行监控
  const [executing, setExecuting] = useState(false);
  const [liveMetrics, setLiveMetrics] = useState<MetricEvent[]>([]);
  const [execStatus, setExecStatus] = useState<string>('idle');
  const [execProgress, setExecProgress] = useState(0);
  const sseControllerRef = useRef<AbortController | null>(null);

  // 拉取任务详情
  const fetchTask = useCallback(async () => {
    if (!taskId) return;
    setLoading(true);
    try {
      const res = await getTask(taskId);
      // 解包 {code, message, data} 信封格式
      setTask(res?.data ?? res);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载任务详情失败');
    } finally {
      setLoading(false);
    }
  }, [taskId]);

  // 拉取结果列表
  const fetchResults = useCallback(async () => {
    if (!taskId) return;
    setResultsLoading(true);
    try {
      const res = await getResults(taskId);
      const list = normalizeResults(res);
      setResults(list);
      // 默认选中最新一条
      if (list.length > 0 && !selectedResult) {
        handleSelectResult(list[0]);
      }
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载执行结果失败');
      setResults([]);
    } finally {
      setResultsLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // 选中结果 -> 拉取指标
  const handleSelectResult = useCallback(async (result: PerformanceResult) => {
    setSelectedResult(result);
    // 如果该结果已有 analysis, 预填到分析区
    if (result.analysis) {
      setAnalysisRaw(result.analysis);
    }
    if (!result.id) {
      setMetrics([]);
      return;
    }
    setMetricsLoading(true);
    try {
      const res = await getMetrics(result.id);
      const list = normalizeMetrics(res);
      setMetrics(list);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载指标数据失败');
      setMetrics([]);
    } finally {
      setMetricsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTask();
    fetchResults();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // 运行分析
  const handleRunAnalysis = async () => {
    if (!taskId) return;
    setAnalyzing(true);
    try {
      const res = await runAnalysis(taskId);
      // 解包 {code, message, data} 信封格式
      setAnalysisRaw(res?.data ?? res);
      message.success('性能分析完成');
      // 刷新结果以同步 analysis 字段
      fetchResults();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '运行分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  // ===== 执行监控 =====

  // 启动执行
  const handleExecute = async () => {
    if (!taskId) return;
    if (!task?.script_content) {
      message.warning('请先生成测试脚本');
      return;
    }
    setExecuting(true);
    setLiveMetrics([]);
    setExecStatus('starting');
    setExecProgress(0);
    try {
      await executeTask(taskId);
      setExecStatus('running');
      message.success('性能测试已启动');
      // 启动 SSE 监听
      startStreaming(taskId);
      // 刷新任务状态
      fetchTask();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '启动执行失败');
      setExecuting(false);
      setExecStatus('failed');
    }
  };

  // 停止执行
  const handleStopExecute = async () => {
    if (!taskId) return;
    try {
      await stopExecute(taskId);
      message.success('已停止执行');
      setExecStatus('stopped');
      setExecuting(false);
      stopStreaming();
      fetchTask();
      fetchResults();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '停止失败');
    }
  };

  // 启动 SSE 流式监听
  const startStreaming = (id: number) => {
    stopStreaming(); // 先停止已有的
    const controller = streamExecuteMetrics(
      id,
      (event: MetricEvent) => {
        // 收到指标
        setLiveMetrics((prev) => [...prev, event]);
        // 更新进度
        if (task?.duration_seconds && event.elapsed) {
          const pct = Math.min(100, (event.elapsed / task.duration_seconds) * 100);
          setExecProgress(pct);
        }
        setExecStatus('running');
      },
      (event: MetricEvent) => {
        // 执行结束
        setExecuting(false);
        setExecStatus(event.status || 'completed');
        setExecProgress(100);
        message.success('性能测试执行完成');
        fetchTask();
        fetchResults();
      },
      (error: Error) => {
        setExecuting(false);
        setExecStatus('error');
        message.error(error.message || '实时监控连接失败');
      },
    );
    sseControllerRef.current = controller;
  };

  // 停止 SSE 流
  const stopStreaming = () => {
    if (sseControllerRef.current) {
      sseControllerRef.current.abort();
      sseControllerRef.current = null;
    }
  };

  // 组件卸载时清理 SSE
  useEffect(() => {
    return () => stopStreaming();
  }, []);

  // 检查执行状态 (页面加载时)
  useEffect(() => {
    if (!taskId) return;
    getExecuteStatus(taskId).then((raw: any) => {
      // 解包 {code, message, data} 信封格式
      const status = raw?.data ?? raw;
      if (status?.status === 'running') {
        setExecuting(true);
        setExecStatus('running');
        startStreaming(taskId);
      }
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [taskId]);

  // ===== 加载中 / 不存在 =====
  if (loading && !task) {
    return (
      <div style={{ textAlign: 'center', padding: 48 }}>
        <Spin size="large" tip="加载中..." />
      </div>
    );
  }

  if (!task) {
    return (
      <Card>
        <Empty description="任务不存在或已被删除" />
        <div style={{ textAlign: 'center', marginTop: 16 }}>
          <Button onClick={() => navigate('/performance')} icon={<ArrowLeftOutlined />}>
            返回列表
          </Button>
        </div>
      </Card>
    );
  }

  const statusMeta = STATUS_META[task.status] || { color: 'default', text: task.status };
  const analysisInfo = extractAnalysis(analysisRaw);
  const verdictMeta = analysisInfo?.verdict
    ? VERDICT_META[String(analysisInfo.verdict).toLowerCase()] || { color: 'blue', text: String(analysisInfo.verdict) }
    : null;

  // 方案信息 (兼容 task.plan 与 task 本身字段)
  const plan: any = task.plan || {};
  const planConcurrency = plan.concurrency ?? task.concurrency;
  const planDuration = plan.duration_seconds ?? task.duration_seconds;
  const planTpsTarget = plan.tps_target ?? task.tps_target;
  const planRampUp = plan.ramp_up ?? task.ramp_up;
  const planBasis = plan.basis ?? plan.reasoning ?? plan.依据 ?? plan.basis_text ?? null;

  // 结果表格列
  const resultColumns = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '状态',
      dataIndex: 'status',
      width: 100,
      render: (s: string) => {
        const meta = STATUS_META[s] || { color: 'default', text: s };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '平均TPS',
      dataIndex: 'avg_tps',
      width: 100,
      align: 'center' as const,
      render: (v: number) => (v != null ? v.toFixed(1) : '-'),
    },
    {
      title: '峰值TPS',
      dataIndex: 'peak_tps',
      width: 100,
      align: 'center' as const,
      render: (v: number) => (v != null ? v.toFixed(1) : '-'),
    },
    {
      title: '平均RT(ms)',
      dataIndex: 'avg_rt',
      width: 110,
      align: 'center' as const,
      render: (v: number) => (v != null ? v.toFixed(2) : '-'),
    },
    {
      title: 'P95 RT(ms)',
      dataIndex: 'p95_rt',
      width: 110,
      align: 'center' as const,
      render: (v: number | null) => (v != null ? v.toFixed(2) : '-'),
    },
    {
      title: '错误率',
      dataIndex: 'error_rate',
      width: 100,
      align: 'center' as const,
      render: (v: number) => formatErrorRate(v),
    },
    {
      title: '总请求数',
      dataIndex: 'total_requests',
      width: 110,
      align: 'center' as const,
      render: (v: number) => (v ?? 0).toLocaleString('zh-CN'),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      width: 170,
      render: (t: string) => (t ? new Date(t).toLocaleString('zh-CN') : '-'),
    },
    {
      title: '操作',
      key: 'action',
      width: 120,
      render: (_: unknown, record: PerformanceResult) => (
        <Button
          type={selectedResult?.id === record.id ? 'primary' : 'link'}
          size="small"
          onClick={() => handleSelectResult(record)}
        >
          {selectedResult?.id === record.id ? '查看中' : '查看指标'}
        </Button>
      ),
    },
  ];

  return (
    <div>
      {/* 顶部操作栏 */}
      <Card size="small" style={{ marginBottom: 16 }} styles={{ body: { padding: '12px 24px' } }}>
        <Space style={{ justifyContent: 'space-between', width: '100%' }}>
          <Space>
            <Button onClick={() => navigate('/performance')} icon={<ArrowLeftOutlined />}>
              返回
            </Button>
            <Text strong>{task.name}</Text>
            <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
            <Tag color="blue">{TEST_TYPE_TEXT[task.test_type] || task.test_type}</Tag>
          </Space>
          <Space>
            <Button icon={<ReloadOutlined />} onClick={() => { fetchTask(); fetchResults(); }}>
              刷新
            </Button>
            <Button
              type="primary"
              icon={<ThunderboltOutlined />}
              loading={analyzing}
              onClick={handleRunAnalysis}
            >
              运行分析
            </Button>
          </Space>
        </Space>
      </Card>

      <Card loading={loading}>
        <Tabs
          defaultActiveKey="overview"
          items={[
            // ===== 1. 概览 =====
            {
              key: 'overview',
              label: '概览',
              children: (
                <Descriptions bordered column={2} size="small">
                  <Descriptions.Item label="任务名称">{task.name}</Descriptions.Item>
                  <Descriptions.Item label="测试类型">
                    <Tag color="blue">{TEST_TYPE_TEXT[task.test_type] || task.test_type}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="目标URL" span={2}>
                    <Text copyable style={{ fontFamily: 'monospace', fontSize: 12 }}>
                      {task.target_url || '-'}
                    </Text>
                  </Descriptions.Item>
                  <Descriptions.Item label="HTTP方法">
                    <Tag>{task.method}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="并发数">
                    {task.concurrency ? <Tag color="blue">{task.concurrency}</Tag> : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="持续时间">
                    {task.duration_seconds ? `${task.duration_seconds} 秒` : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="TPS目标">
                    {task.tps_target != null ? task.tps_target : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="预热时间">
                    {task.ramp_up != null ? `${task.ramp_up} 秒` : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="状态">
                    <Tag color={statusMeta.color}>{statusMeta.text}</Tag>
                  </Descriptions.Item>
                  <Descriptions.Item label="日业务量">
                    {task.business_volume ? task.business_volume.toLocaleString('zh-CN') : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="脚本类型">
                    {task.script_type ? <Tag color="magenta">{task.script_type}</Tag> : '-'}
                  </Descriptions.Item>
                  <Descriptions.Item label="创建时间" span={2}>
                    {task.created_at ? new Date(task.created_at).toLocaleString('zh-CN') : '-'}
                  </Descriptions.Item>
                  {task.error_message && (
                    <Descriptions.Item label="错误信息" span={2}>
                      <Text type="danger">{task.error_message}</Text>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              ),
            },

            // ===== 2. 测试方案 =====
            {
              key: 'plan',
              label: '测试方案',
              children: (
                <div>
                  {task.plan ? (
                    <>
                      <Card size="small" title="方案参数" style={{ marginBottom: 16 }}>
                        <Descriptions bordered column={2} size="small">
                          <Descriptions.Item label="并发数">
                            {planConcurrency != null ? <Tag color="blue">{planConcurrency}</Tag> : '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="持续时间">
                            {planDuration != null ? `${planDuration} 秒` : '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="TPS目标">
                            {planTpsTarget != null ? planTpsTarget : '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="预热时间">
                            {planRampUp != null ? `${planRampUp} 秒` : '-'}
                          </Descriptions.Item>
                          <Descriptions.Item label="方案依据" span={2}>
                            {planBasis ? (
                              <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{String(planBasis)}</Paragraph>
                            ) : <Text type="secondary">未提供</Text>}
                          </Descriptions.Item>
                        </Descriptions>
                      </Card>
                      <Card size="small" title="方案原始 JSON">
                        <pre style={{
                          background: '#f5f5f5',
                          padding: 12,
                          borderRadius: 4,
                          fontSize: 12,
                          maxHeight: 400,
                          overflow: 'auto',
                          fontFamily: 'monospace',
                        }}>
                          {JSON.stringify(task.plan, null, 2)}
                        </pre>
                      </Card>
                    </>
                  ) : (
                    <Empty description="尚未生成测试方案, 请在列表页点击「方案」按钮生成" />
                  )}
                </div>
              ),
            },

            // ===== 3. 执行监控 =====
            {
              key: 'execute',
              label: <span><PlayCircleOutlined /> 执行监控</span>,
              children: (
                <div>
                  {/* 执行控制栏 */}
                  <Card size="small" style={{ marginBottom: 16 }}>
                    <Space style={{ justifyContent: 'space-between', width: '100%' }}>
                      <Space>
                        {executing ? (
                          <Button
                            danger
                            icon={<StopOutlined />}
                            onClick={handleStopExecute}
                          >
                            停止执行
                          </Button>
                        ) : (
                          <Button
                            type="primary"
                            icon={<PlayCircleOutlined />}
                            onClick={handleExecute}
                            disabled={!task.script_content}
                          >
                            启动执行
                          </Button>
                        )}
                        {execStatus !== 'idle' && (
                          <Tag color={
                            execStatus === 'running' ? 'processing'
                            : execStatus === 'completed' ? 'green'
                            : execStatus === 'failed' ? 'red'
                            : execStatus === 'stopped' ? 'orange'
                            : 'default'
                          }>
                            {execStatus === 'running' ? '执行中'
                            : execStatus === 'completed' ? '已完成'
                            : execStatus === 'failed' ? '失败'
                            : execStatus === 'stopped' ? '已停止'
                            : execStatus === 'starting' ? '启动中'
                            : execStatus === 'error' ? '监控错误'
                            : execStatus}
                          </Tag>
                        )}
                      </Space>
                      <Text type="secondary">
                        并发: {task.concurrency || '-'} | 持续: {task.duration_seconds || '-'}s | TPS目标: {task.tps_target || '-'}
                      </Text>
                    </Space>
                    {executing && task.duration_seconds && (
                      <Progress
                        percent={Math.round(execProgress)}
                        status="active"
                        style={{ marginTop: 12 }}
                        format={(pct) => `${pct}%`}
                      />
                    )}
                  </Card>

                  {/* 实时指标卡片 */}
                  {liveMetrics.length > 0 && (() => {
                    const latest = liveMetrics[liveMetrics.length - 1];
                    return (
                      <Row gutter={16} style={{ marginBottom: 16 }}>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="当前TPS" value={latest.tps ?? 0} precision={1} valueStyle={{ color: '#1677ff' }} />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="平均RT(ms)" value={latest.avg_rt ?? 0} precision={2} valueStyle={{ color: '#faad14' }} />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="并发用户" value={latest.concurrent_users ?? 0} />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="错误数" value={latest.error_count ?? 0} valueStyle={{ color: (latest.error_count ?? 0) > 0 ? '#ff4d4f' : '#52c41a' }} />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="CPU(%)" value={latest.cpu_percent ?? '-'} precision={1} suffix="%" />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="内存(MB)" value={latest.memory_mb ?? '-'} precision={1} />
                          </Card>
                        </Col>
                      </Row>
                    );
                  })()}

                  {/* 实时图表 */}
                  {liveMetrics.length > 0 ? (
                    <Row gutter={[16, 16]}>
                      {/* TPS 实时图 */}
                      <Col span={24}>
                        <Card size="small" title="TPS 实时趋势">
                          <ResponsiveContainer width="100%" height={260}>
                            <AreaChart data={liveMetrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                              <defs>
                                <linearGradient id="colorLiveTps" x1="0" y1="0" x2="0" y2="1">
                                  <stop offset="5%" stopColor="#1677ff" stopOpacity={0.6} />
                                  <stop offset="95%" stopColor="#1677ff" stopOpacity={0.05} />
                                </linearGradient>
                              </defs>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="elapsed" name="耗时" unit="s" tick={{ fontSize: 12 }} />
                              <YAxis name="TPS" tick={{ fontSize: 12 }} />
                              <Tooltip formatter={(v: any) => [Number(v).toFixed(2), 'TPS']} labelFormatter={(l) => `${l} 秒`} />
                              <Area type="monotone" dataKey="tps" stroke="#1677ff" fill="url(#colorLiveTps)" strokeWidth={2} name="TPS" />
                            </AreaChart>
                          </ResponsiveContainer>
                        </Card>
                      </Col>

                      {/* 响应时间实时图 */}
                      <Col span={24}>
                        <Card size="small" title="响应时间实时趋势 (ms)">
                          <ResponsiveContainer width="100%" height={260}>
                            <LineChart data={liveMetrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="elapsed" name="耗时" unit="s" tick={{ fontSize: 12 }} />
                              <YAxis name="RT" unit="ms" tick={{ fontSize: 12 }} />
                              <Tooltip formatter={(v: any) => [Number(v).toFixed(2) + ' ms', '平均RT']} labelFormatter={(l) => `${l} 秒`} />
                              <Line type="monotone" dataKey="avg_rt" stroke="#faad14" strokeWidth={2} dot={false} name="平均RT" />
                            </LineChart>
                          </ResponsiveContainer>
                        </Card>
                      </Col>

                      {/* CPU / 内存实时图 */}
                      <Col span={24}>
                        <Card size="small" title="CPU / 内存实时趋势">
                          <ResponsiveContainer width="100%" height={260}>
                            <LineChart data={liveMetrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="elapsed" name="耗时" unit="s" tick={{ fontSize: 12 }} />
                              <YAxis yAxisId="cpu" orientation="left" unit="%" tick={{ fontSize: 12 }} />
                              <YAxis yAxisId="mem" orientation="right" unit="MB" tick={{ fontSize: 12 }} />
                              <Tooltip labelFormatter={(l) => `${l} 秒`} />
                              <Legend />
                              <Line yAxisId="cpu" type="monotone" dataKey="cpu_percent" stroke="#1677ff" strokeWidth={2} dot={false} name="CPU(%)" />
                              <Line yAxisId="mem" type="monotone" dataKey="memory_mb" stroke="#52c41a" strokeWidth={2} dot={false} name="内存(MB)" />
                            </LineChart>
                          </ResponsiveContainer>
                        </Card>
                      </Col>

                      {/* 错误数实时图 */}
                      <Col span={24}>
                        <Card size="small" title="错误数累计趋势">
                          <ResponsiveContainer width="100%" height={200}>
                            <BarChart data={liveMetrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="elapsed" name="耗时" unit="s" tick={{ fontSize: 12 }} />
                              <YAxis name="错误数" tick={{ fontSize: 12 }} />
                              <Tooltip labelFormatter={(l) => `${l} 秒`} />
                              <Bar dataKey="error_count" fill="#ff4d4f" name="错误数" />
                            </BarChart>
                          </ResponsiveContainer>
                        </Card>
                      </Col>
                    </Row>
                  ) : (
                    <Empty description={
                      executing
                        ? '等待指标数据传入...'
                        : '点击「启动执行」按钮开始性能测试, 实时指标将在此展示'
                    } />
                  )}
                </div>
              ),
            },

            // ===== 4. 执行结果 =====
            {
              key: 'results',
              label: '执行结果',
              children: (
                <div>
                  {/* 分析结果卡片 */}
                  {analysisInfo ? (
                    <Card
                      size="small"
                      title={<Space><BarChartOutlined /> 性能分析结果</Space>}
                      style={{ marginBottom: 16 }}
                      extra={
                        verdictMeta ? <Tag color={verdictMeta.color}>{verdictMeta.text}</Tag> : null
                      }
                    >
                      <Row gutter={16} style={{ marginBottom: 12 }}>
                        <Col span={6}>
                          <Statistic
                            title="综合评分"
                            value={analysisInfo.score ?? '-'}
                            precision={analysisInfo.score != null ? 1 : undefined}
                            valueStyle={{
                              color: (analysisInfo.score ?? 0) >= 80 ? '#52c41a'
                                : (analysisInfo.score ?? 0) >= 60 ? '#faad14' : '#ff4d4f',
                            }}
                            suffix={analysisInfo.score != null ? ' / 100' : ''}
                          />
                        </Col>
                        <Col span={18}>
                          <Text type="secondary">分析摘要</Text>
                          <Paragraph style={{ margin: '4px 0 0' }}>
                            {analysisInfo.summary || <Text type="secondary">无</Text>}
                          </Paragraph>
                        </Col>
                      </Row>
                      <Row gutter={16}>
                        <Col span={12}>
                          <Text strong>性能瓶颈</Text>
                          {analysisInfo.bottlenecks && analysisInfo.bottlenecks.length > 0 ? (
                            <List
                              size="small"
                              dataSource={analysisInfo.bottlenecks}
                              renderItem={(item, idx) => (
                                <List.Item style={{ padding: '6px 0' }}>
                                  <Text>
                                    <Tag color="red" style={{ marginRight: 6 }}>{idx + 1}</Tag>
                                    {item}
                                  </Text>
                                </List.Item>
                              )}
                            />
                          ) : (
                            <Paragraph type="secondary" style={{ margin: '4px 0' }}>未发现明显瓶颈</Paragraph>
                          )}
                        </Col>
                        <Col span={12}>
                          <Text strong>优化建议</Text>
                          {analysisInfo.recommendations && analysisInfo.recommendations.length > 0 ? (
                            <List
                              size="small"
                              dataSource={analysisInfo.recommendations}
                              renderItem={(item, idx) => (
                                <List.Item style={{ padding: '6px 0' }}>
                                  <Text>
                                    <Tag color="blue" style={{ marginRight: 6 }}>{idx + 1}</Tag>
                                    {item}
                                  </Text>
                                </List.Item>
                              )}
                            />
                          ) : (
                            <Paragraph type="secondary" style={{ margin: '4px 0' }}>暂无建议</Paragraph>
                          )}
                        </Col>
                      </Row>
                    </Card>
                  ) : (
                    <Alert
                      style={{ marginBottom: 16 }}
                      message="点击右上角「运行分析」按钮生成 AI 性能分析报告"
                      type="info"
                      showIcon
                    />
                  )}

                  {/* 结果表格 */}
                  <Table
                    dataSource={results}
                    rowKey="id"
                    size="small"
                    loading={resultsLoading}
                    pagination={results.length > 10 ? { pageSize: 10 } : false}
                    columns={resultColumns}
                    style={{ marginBottom: 16 }}
                  />

                  {/* 选中结果: 汇总统计 + 图表 */}
                  {selectedResult ? (
                    <div>
                      <Text strong>结果 #{selectedResult.id} 指标详情</Text>

                      {/* 汇总统计卡片 */}
                      <Row gutter={16} style={{ marginTop: 12, marginBottom: 16 }}>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic title="平均TPS" value={selectedResult.avg_tps ?? 0} precision={1} />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic
                              title="峰值TPS"
                              value={selectedResult.peak_tps ?? 0}
                              precision={1}
                              valueStyle={{ color: '#1677ff' }}
                            />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic
                              title="平均RT(ms)"
                              value={selectedResult.avg_rt ?? 0}
                              precision={2}
                              valueStyle={{ color: '#faad14' }}
                            />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic
                              title="P95 RT(ms)"
                              value={selectedResult.p95_rt ?? 0}
                              precision={2}
                              valueStyle={{ color: '#fa8c16' }}
                            />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic
                              title="错误率"
                              value={formatErrorRate(selectedResult.error_rate)}
                              valueStyle={{
                                color: (selectedResult.error_rate ?? 0) > 1 ? '#ff4d4f' : '#52c41a',
                              }}
                            />
                          </Card>
                        </Col>
                        <Col span={4}>
                          <Card size="small">
                            <Statistic
                              title="总请求数"
                              value={selectedResult.total_requests ?? 0}
                              valueStyle={{ color: '#52c41a' }}
                            />
                          </Card>
                        </Col>
                      </Row>

                      {/* 指标图表 */}
                      <Spin spinning={metricsLoading}>
                        {metrics.length > 0 ? (
                          <Row gutter={[16, 16]}>
                            {/* TPS 随时间变化 */}
                            <Col span={24}>
                              <Card size="small" title="TPS 随时间变化">
                                <ResponsiveContainer width="100%" height={260}>
                                  <LineChart data={metrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                      dataKey="elapsed"
                                      name="耗时"
                                      unit="s"
                                      tick={{ fontSize: 12 }}
                                    />
                                    <YAxis name="TPS" tick={{ fontSize: 12 }} />
                                    <Tooltip
                                      formatter={(v: any) => [Number(v).toFixed(2), 'TPS']}
                                      labelFormatter={(l) => `${l} 秒`}
                                    />
                                    <Line
                                      type="monotone"
                                      dataKey="tps"
                                      stroke="#1677ff"
                                      strokeWidth={2}
                                      dot={false}
                                      name="TPS"
                                    />
                                  </LineChart>
                                </ResponsiveContainer>
                              </Card>
                            </Col>

                            {/* 响应时间随时间变化 */}
                            <Col span={24}>
                              <Card size="small" title="响应时间随时间变化 (ms)">
                                <ResponsiveContainer width="100%" height={260}>
                                  <LineChart data={metrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                      dataKey="elapsed"
                                      name="耗时"
                                      unit="s"
                                      tick={{ fontSize: 12 }}
                                    />
                                    <YAxis name="响应时间" unit="ms" tick={{ fontSize: 12 }} />
                                    <Tooltip
                                      formatter={(v: any) => [Number(v).toFixed(2) + ' ms', '平均RT']}
                                      labelFormatter={(l) => `${l} 秒`}
                                    />
                                    <Line
                                      type="monotone"
                                      dataKey="avg_rt"
                                      stroke="#faad14"
                                      strokeWidth={2}
                                      dot={false}
                                      name="平均RT"
                                    />
                                  </LineChart>
                                </ResponsiveContainer>
                              </Card>
                            </Col>

                            {/* CPU / 内存随时间变化 */}
                            <Col span={24}>
                              <Card size="small" title="CPU / 内存随时间变化">
                                <ResponsiveContainer width="100%" height={260}>
                                  <BarChart data={metrics} margin={{ top: 8, right: 24, left: 0, bottom: 8 }}>
                                    <CartesianGrid strokeDasharray="3 3" />
                                    <XAxis
                                      dataKey="elapsed"
                                      name="耗时"
                                      unit="s"
                                      tick={{ fontSize: 12 }}
                                    />
                                    <YAxis
                                      yAxisId="cpu"
                                      orientation="left"
                                      name="CPU"
                                      unit="%"
                                      tick={{ fontSize: 12 }}
                                    />
                                    <YAxis
                                      yAxisId="mem"
                                      orientation="right"
                                      name="内存"
                                      unit="MB"
                                      tick={{ fontSize: 12 }}
                                    />
                                    <Tooltip
                                      labelFormatter={(l) => `${l} 秒`}
                                      formatter={(v: any, name: any) => {
                                        if (name === '内存' || name === 'memory_mb') {
                                          return [Number(v).toFixed(1) + ' MB', '内存'];
                                        }
                                        return [Number(v).toFixed(2) + ' %', 'CPU'];
                                      }}
                                    />
                                    <Legend />
                                    <Bar
                                      yAxisId="cpu"
                                      dataKey="cpu_percent"
                                      fill="#1677ff"
                                      name="CPU(%)"
                                    />
                                    <Bar
                                      yAxisId="mem"
                                      dataKey="memory_mb"
                                      fill="#52c41a"
                                      name="内存(MB)"
                                    />
                                  </BarChart>
                                </ResponsiveContainer>
                              </Card>
                            </Col>
                          </Row>
                        ) : (
                          <Empty description="暂无指标数据" />
                        )}
                      </Spin>
                    </div>
                  ) : (
                    <Empty description="请选择一条执行结果查看指标图表" />
                  )}
                </div>
              ),
            },

            // ===== 4. 脚本 =====
            {
              key: 'script',
              label: '脚本',
              children: (
                <div>
                  <Space style={{ marginBottom: 12 }}>
                    <Text type="secondary">脚本类型:</Text>
                    <Tag color="magenta">{task.script_type || '-'}</Tag>
                  </Space>
                  {task.script_content ? (
                    <pre style={{
                      background: '#f5f5f5',
                      padding: 16,
                      borderRadius: 6,
                      fontSize: 13,
                      lineHeight: 1.6,
                      maxHeight: 600,
                      overflow: 'auto',
                      fontFamily: 'Consolas, "Courier New", monospace',
                      border: '1px solid #e8e8e8',
                    }}>
                      {task.script_content}
                    </pre>
                  ) : (
                    <Empty description="尚未生成测试脚本, 请在列表页点击「脚本」按钮生成" />
                  )}
                  {task.jmeter_config && (
                    <Card size="small" title="JMeter 配置" style={{ marginTop: 16 }}>
                      <pre style={{
                        background: '#f5f5f5',
                        padding: 12,
                        borderRadius: 4,
                        fontSize: 12,
                        maxHeight: 400,
                        overflow: 'auto',
                        fontFamily: 'monospace',
                      }}>
                        {typeof task.jmeter_config === 'string'
                          ? task.jmeter_config
                          : JSON.stringify(task.jmeter_config, null, 2)}
                      </pre>
                    </Card>
                  )}
                </div>
              ),
            },
          ]}
        />
      </Card>
    </div>
  );
}
