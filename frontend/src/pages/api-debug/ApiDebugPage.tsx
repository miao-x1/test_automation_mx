/**
 * AI 接口调试页面
 *
 * Postman 风格三列布局:
 *   左侧: 请求编辑(method + URL + headers + body + auth)
 *   中间: 响应展示(status / headers / body / 耗时)
 *   右侧: AI 分析(问题原因 / 解决方案 / 修复建议)
 *
 * 功能:
 *   1. 编辑并发送 HTTP 请求
 *   2. 查看完整响应
 *   3. AI 一键分析失败原因
 *   4. 查看历史执行记录
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Card, Row, Col, Input, Button, Select, Tabs, Table, Tag, Space,
  message, Typography, Tooltip, Spin, Empty, Divider, Statistic, Alert,
} from 'antd';
import {
  PlayCircleOutlined, ReloadOutlined, ThunderboltOutlined, HistoryOutlined,
  RobotOutlined, CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  EyeOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

import {
  executeRequest, analyzeRecord, listExecutionRecords,
  type ExecuteRequest, type ExecuteResult, type AnalysisResult,
  type ExecutionRecord, type HttpMethod,
} from '@/services/apiDebug';

const { Text, Paragraph } = Typography;
const { TextArea } = Input;

// ============================================================
// 常量
// ============================================================

const METHODS: HttpMethod[] = ['GET', 'POST', 'PUT', 'DELETE', 'PATCH', 'HEAD', 'OPTIONS'];

const METHOD_COLORS: Record<string, string> = {
  GET: 'green', POST: 'blue', PUT: 'orange', DELETE: 'red',
  PATCH: 'purple', HEAD: 'default', OPTIONS: 'default',
};

const STATUS_COLORS: Record<string, string> = {
  success: 'success', failed: 'warning', error: 'error', timeout: 'error', pending: 'default',
};

const AUTH_TYPES = [
  { value: 'none', label: '无认证' },
  { value: 'bearer', label: 'Bearer Token' },
  { value: 'basic', label: 'Basic Auth' },
  { value: 'api_key', label: 'API Key' },
];

// ============================================================
// 默认请求
// ============================================================

const DEFAULT_REQUEST: ExecuteRequest = {
  method: 'GET',
  url: 'https://httpbin.org/get',
  headers: { 'Content-Type': 'application/json' },
  params: {},
  body: null,
  auth: { type: 'none' },
  timeout: 30000,
  env: 'test',
  auto_analyze: true,
};

// ============================================================
// 主组件
// ============================================================

export default function ApiDebugPage() {
  // 请求状态
  const [method, setMethod] = useState<HttpMethod>(DEFAULT_REQUEST.method!);
  const [url, setUrl] = useState(DEFAULT_REQUEST.url!);
  const [headersText, setHeadersText] = useState(
    JSON.stringify(DEFAULT_REQUEST.headers, null, 2),
  );
  const [paramsText, setParamsText] = useState('{}');
  const [bodyText, setBodyText] = useState('');
  const [authType, setAuthType] = useState<string>('none');
  const [authToken, setAuthToken] = useState('');
  const [authUsername, setAuthUsername] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [autoAnalyze, setAutoAnalyze] = useState(true);

  // 执行状态
  const [executing, setExecuting] = useState(false);
  const [executeResult, setExecuteResult] = useState<ExecuteResult | null>(null);

  // AI 分析
  const [analyzing, setAnalyzing] = useState(false);
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);

  // 历史记录
  const [history, setHistory] = useState<ExecutionRecord[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('request');

  // 加载历史
  const fetchHistory = useCallback(async () => {
    setHistoryLoading(true);
    try {
      const data = await listExecutionRecords({ page: historyPage, page_size: 10 });
      setHistory(data.items);
      setHistoryTotal(data.total);
    } catch (e) {
      const err = e as { message?: string };
      message.error(err.message || '加载历史失败');
    } finally {
      setHistoryLoading(false);
    }
  }, [historyPage]);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  // 解析 JSON 辅助
  const safeParse = (text: string): any => {
    if (!text || !text.trim()) return null;
    try {
      return JSON.parse(text);
    } catch {
      return text;
    }
  };

  // 执行请求
  const handleExecute = async () => {
    if (!url.trim()) {
      message.warning('请输入 URL');
      return;
    }

    setExecuting(true);
    setExecuteResult(null);
    setAnalysis(null);
    setActiveTab('response');

    try {
      const headers = safeParse(headersText) || {};
      const params = safeParse(paramsText) || {};
      const body = bodyText.trim() ? safeParse(bodyText) : null;

      const auth: any = { type: authType };
      if (authType === 'bearer') auth.token = authToken;
      if (authType === 'basic') {
        auth.username = authUsername;
        auth.password = authPassword;
      }
      if (authType === 'api_key') {
        auth.key_name = 'X-API-Key';
        auth.key_value = authToken;
      }

      const result = await executeRequest({
        method, url, headers, params, body,
        auth: authType === 'none' ? undefined : auth,
        timeout: 30000,
        auto_analyze: autoAnalyze,
      });

      setExecuteResult(result);
      if (result.analysis) {
        setAnalysis(result.analysis);
        setActiveTab('analysis');
      }
      message.success(`执行完成: ${result.status} (${result.status_code ?? '-'})`);
      fetchHistory();
    } catch (e) {
      const err = e as { message?: string };
      message.error(err.message || '执行失败');
    } finally {
      setExecuting(false);
    }
  };

  // AI 分析
  const handleAnalyze = async () => {
    if (!executeResult?.record_id) {
      message.warning('请先执行请求');
      return;
    }
    setAnalyzing(true);
    setActiveTab('analysis');
    try {
      const result = await analyzeRecord(executeResult.record_id, true);
      setAnalysis(result);
      if (result.status === 'success' || result.status === 'degraded') {
        message.success(`分析完成 (来源: ${result.source}, 置信度: ${(result.confidence * 100).toFixed(0)}%)`);
      } else {
        message.warning(result.message || '分析未完成');
      }
    } catch (e) {
      const err = e as { message?: string };
      message.error(err.message || '分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  // 加载历史记录到编辑器
  const loadFromHistory = (record: ExecutionRecord) => {
    setMethod(record.method as HttpMethod);
    setUrl(record.url);
    setHeadersText(JSON.stringify(record.headers || {}, null, 2));
    setParamsText(JSON.stringify(record.params || {}, null, 2));
    setBodyText(record.body ? JSON.stringify(record.body, null, 2) : '');
    setActiveTab('request');
    message.info(`已加载记录 #${record.id}`);
  };

  // 历史记录表格列
  const historyColumns: ColumnsType<ExecutionRecord> = [
    { title: 'ID', dataIndex: 'id', width: 70 },
    {
      title: '方法', dataIndex: 'method', width: 80,
      render: (m: string) => <Tag color={METHOD_COLORS[m] || 'default'}>{m}</Tag>,
    },
    {
      title: 'URL', dataIndex: 'url', ellipsis: true,
      render: (u: string) => <Tooltip title={u}><span>{u}</span></Tooltip>,
    },
    {
      title: '状态码', dataIndex: 'status_code', width: 80,
      render: (c: number) => c ? <Tag color={c < 400 ? 'green' : 'red'}>{c}</Tag> : '-',
    },
    {
      title: '状态', dataIndex: 'status', width: 90,
      render: (s: string) => <Tag color={STATUS_COLORS[s] || 'default'}>{s}</Tag>,
    },
    {
      title: '耗时', dataIndex: 'duration', width: 80,
      render: (d: number) => <Text>{d.toFixed(0)}ms</Text>,
    },
    {
      title: 'AI', dataIndex: 'analysis_status', width: 70,
      render: (s: string) => {
        const meta: Record<string, { color: string; icon: any }> = {
          none: { color: 'default', icon: <ClockCircleOutlined /> },
          analyzing: { color: 'processing', icon: <ReloadOutlined spin /> },
          done: { color: 'success', icon: <CheckCircleOutlined /> },
          failed: { color: 'error', icon: <CloseCircleOutlined /> },
        };
        const m = meta[s] || meta.none;
        return <Tag color={m.color} icon={m.icon}>{s}</Tag>;
      },
    },
    {
      title: '操作', width: 80, fixed: 'right',
      render: (_: any, r: ExecutionRecord) => (
        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => loadFromHistory(r)} />
      ),
    },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Card
        title={
          <Space>
            <RobotOutlined />
            <span>AI 接口调试</span>
            <Tag color="purple">Postman + AI</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<HistoryOutlined />} onClick={fetchHistory} loading={historyLoading}>
              刷新历史
            </Button>
          </Space>
        }
      >
        {/* ====== 顶部统计 ====== */}
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="执行总数"
                value={historyTotal}
                prefix={<PlayCircleOutlined />}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="最近状态"
                value={executeResult?.status || '未执行'}
                valueStyle={{
                  color: executeResult?.status === 'success' ? '#3f8600' :
                    executeResult?.status ? '#cf1322' : undefined,
                }}
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="响应耗时"
                value={executeResult?.duration?.toFixed(0) || 0}
                suffix="ms"
              />
            </Card>
          </Col>
          <Col span={6}>
            <Card size="small">
              <Statistic
                title="AI 分析"
                value={analysis ? `${(analysis.confidence * 100).toFixed(0)}%` : '未分析'}
                prefix={<ThunderboltOutlined />}
              />
            </Card>
          </Col>
        </Row>

        {/* ====== 主区域:三列布局 ====== */}
        <Row gutter={16}>
          {/* 左侧:请求编辑 */}
          <Col span={10}>
            <Card
              size="small"
              title={<span><PlayCircleOutlined /> 请求编辑</span>}
              extra={
                <Space>
                  <Select
                    value={autoAnalyze ? 'yes' : 'no'}
                    onChange={(v) => setAutoAnalyze(v === 'yes')}
                    size="small"
                    style={{ width: 130 }}
                    options={[
                      { value: 'yes', label: '失败自动分析' },
                      { value: 'no', label: '不自动分析' },
                    ]}
                  />
                  <Button
                    type="primary"
                    icon={<PlayCircleOutlined />}
                    loading={executing}
                    onClick={handleExecute}
                  >
                    发送
                  </Button>
                </Space>
              }
            >
              <Space.Compact style={{ width: '100%', marginBottom: 12 }}>
                <Select
                  value={method}
                  onChange={setMethod}
                  style={{ width: 100 }}
                  options={METHODS.map(m => ({ value: m, label: m }))}
                />
                <Input
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                  placeholder="https://api.example.com/users"
                  onPressEnter={handleExecute}
                />
              </Space.Compact>

              <Tabs
                activeKey={activeTab === 'analysis' ? 'request' : activeTab}
                onChange={setActiveTab}
                size="small"
                items={[
                  {
                    key: 'request',
                    label: '请求头',
                    children: (
                      <TextArea
                        value={headersText}
                        onChange={(e) => setHeadersText(e.target.value)}
                        rows={6}
                        style={{ fontFamily: 'monospace', fontSize: 12 }}
                        placeholder='{"Content-Type": "application/json"}'
                      />
                    ),
                  },
                  {
                    key: 'params',
                    label: 'Query 参数',
                    children: (
                      <TextArea
                        value={paramsText}
                        onChange={(e) => setParamsText(e.target.value)}
                        rows={6}
                        style={{ fontFamily: 'monospace', fontSize: 12 }}
                        placeholder='{"page": 1, "size": 20}'
                      />
                    ),
                  },
                  {
                    key: 'body',
                    label: '请求体',
                    children: (
                      <TextArea
                        value={bodyText}
                        onChange={(e) => setBodyText(e.target.value)}
                        rows={6}
                        style={{ fontFamily: 'monospace', fontSize: 12 }}
                        placeholder='{"username": "test", "password": "***"}'
                      />
                    ),
                  },
                  {
                    key: 'auth',
                    label: '认证',
                    children: (
                      <Space direction="vertical" style={{ width: '100%' }}>
                        <Select
                          value={authType}
                          onChange={setAuthType}
                          style={{ width: '100%' }}
                          options={AUTH_TYPES}
                        />
                        {authType === 'bearer' && (
                          <Input.Password
                            value={authToken}
                            onChange={(e) => setAuthToken(e.target.value)}
                            placeholder="Bearer Token"
                          />
                        )}
                        {authType === 'basic' && (
                          <>
                            <Input
                              value={authUsername}
                              onChange={(e) => setAuthUsername(e.target.value)}
                              placeholder="用户名"
                            />
                            <Input.Password
                              value={authPassword}
                              onChange={(e) => setAuthPassword(e.target.value)}
                              placeholder="密码"
                            />
                          </>
                        )}
                        {authType === 'api_key' && (
                          <Input.Password
                            value={authToken}
                            onChange={(e) => setAuthToken(e.target.value)}
                            placeholder="API Key Value"
                          />
                        )}
                      </Space>
                    ),
                  },
                ]}
              />
            </Card>
          </Col>

          {/* 中间:响应展示 */}
          <Col span={8}>
            <Card
              size="small"
              title={
                <Space>
                  <span>响应</span>
                  {executeResult?.status_code && (
                    <Tag color={executeResult.status_code < 400 ? 'green' : 'red'}>
                      {executeResult.status_code}
                    </Tag>
                  )}
                  {executeResult?.duration != null && (
                    <Tag color="blue">{executeResult.duration.toFixed(0)}ms</Tag>
                  )}
                </Space>
              }
              extra={executeResult?.record_id && <Text type="secondary">#{executeResult.record_id}</Text>}
            >
              {executing ? (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <Spin tip="请求中..." />
                </div>
              ) : executeResult?.response ? (
                <Tabs
                  size="small"
                  items={[
                    {
                      key: 'body',
                      label: '响应体',
                      children: (
                        <pre
                          style={{
                            maxHeight: 360, overflow: 'auto',
                            background: '#f5f5f5', padding: 12,
                            borderRadius: 4, fontSize: 12,
                            fontFamily: 'monospace', whiteSpace: 'pre-wrap',
                            wordBreak: 'break-word',
                          }}
                        >
                          {typeof executeResult.response.body === 'object'
                            ? JSON.stringify(executeResult.response.body, null, 2)
                            : String(executeResult.response.body || '')}
                        </pre>
                      ),
                    },
                    {
                      key: 'headers',
                      label: '响应头',
                      children: (
                        <pre
                          style={{
                            maxHeight: 360, overflow: 'auto',
                            background: '#f5f5f5', padding: 12,
                            borderRadius: 4, fontSize: 12,
                            fontFamily: 'monospace', whiteSpace: 'pre-wrap',
                          }}
                        >
                          {JSON.stringify(executeResult.response.headers, null, 2)}
                        </pre>
                      ),
                    },
                  ]}
                />
              ) : executeResult?.error ? (
                <div>
                  <Alert
                    type="error"
                    message="请求失败"
                    description={executeResult.error}
                    showIcon
                  />
                </div>
              ) : (
                <Empty description="尚未执行" />
              )}

              {executeResult?.error && (
                <Alert
                  type="error"
                  message="请求错误"
                  description={executeResult.error}
                  showIcon
                  style={{ marginTop: 12 }}
                />
              )}
            </Card>
          </Col>

          {/* 右侧:AI 分析 */}
          <Col span={6}>
            <Card
              size="small"
              title={
                <Space>
                  <RobotOutlined />
                  <span>AI 分析</span>
                  {analysis && (
                    <Tag color={analysis.source === 'llm' ? 'purple' : 'orange'}>
                      {analysis.source === 'llm' ? 'LLM' : '规则引擎'}
                    </Tag>
                  )}
                </Space>
              }
              extra={
                <Tooltip title="重新分析">
                  <Button
                    type="primary"
                    size="small"
                    ghost
                    icon={<ThunderboltOutlined />}
                    loading={analyzing}
                    onClick={handleAnalyze}
                    disabled={!executeResult?.record_id}
                  >
                    分析
                  </Button>
                </Tooltip>
              }
            >
              {analyzing ? (
                <div style={{ textAlign: 'center', padding: 40 }}>
                  <Spin tip="AI 分析中..." />
                </div>
              ) : analysis ? (
                <div style={{ fontSize: 13 }}>
                  <Statistic
                    title="置信度"
                    value={(analysis.confidence * 100).toFixed(0)}
                    suffix="%"
                    valueStyle={{
                      color: analysis.confidence > 0.7 ? '#3f8600' :
                        analysis.confidence > 0.5 ? '#d4b106' : '#cf1322',
                    }}
                    style={{ marginBottom: 12 }}
                  />
                  <Divider style={{ margin: '8px 0' }} />
                  <Paragraph>
                    <Text strong>问题原因</Text>
                    <Paragraph style={{ marginTop: 4 }}>{analysis.problem_cause}</Paragraph>
                  </Paragraph>
                  <Divider style={{ margin: '8px 0' }} />
                  <Paragraph>
                    <Text strong>解决方案</Text>
                    <Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
                      {analysis.solution}
                    </Paragraph>
                  </Paragraph>
                  <Divider style={{ margin: '8px 0' }} />
                  <Paragraph>
                    <Text strong>修复建议</Text>
                    <Paragraph style={{ marginTop: 4, whiteSpace: 'pre-wrap' }}>
                      {analysis.fix_suggestion}
                    </Paragraph>
                  </Paragraph>
                </div>
              ) : (
                <Empty description="点击分析按钮开始" />
              )}
            </Card>
          </Col>
        </Row>

        {/* ====== 底部:历史记录 ====== */}
        <Card
          size="small"
          title={<span><HistoryOutlined /> 执行历史</span>}
          style={{ marginTop: 16 }}
        >
          <Table
            rowKey="id"
            size="small"
            columns={historyColumns}
            dataSource={history}
            loading={historyLoading}
            scroll={{ x: 800 }}
            pagination={{
              current: historyPage,
              total: historyTotal,
              pageSize: 10,
              showSizeChanger: false,
              onChange: (p) => setHistoryPage(p),
              showTotal: (t) => `共 ${t} 条`,
            }}
          />
        </Card>
      </Card>
    </div>
  );
}

