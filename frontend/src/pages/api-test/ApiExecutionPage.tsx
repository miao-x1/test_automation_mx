/**
 * 接口测试执行中心
 * 选择用例执行 / JSON执行 + 执行记录列表 + 状态轮询 + 重跑 + HTTP日志
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Button, Table, Tag, Space, Typography, Input, Select,
  Tabs, message, Empty, Tooltip, Alert, Modal, Popconfirm,
} from 'antd';
import {
  PlayCircleOutlined, ReloadOutlined, EyeOutlined,
  CodeOutlined, ThunderboltOutlined, RedoOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  LoadingOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  runExecution, runExecutionJson,
  listExecutions, retryExecution,
  ExecutionListItem,
} from '../../services/apiExec';
import { getExecutionReport, ExecutionReport, CaseResult } from '../../services/apiReport';
import { listCases, ApiCase } from '../../services/apiCase';

const { Text } = Typography;
const { TextArea } = Input;

const STATUS_MAP: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  waiting: { color: 'default', text: '排队中', icon: <ClockCircleOutlined /> },
  pending: { color: 'default', text: '待执行', icon: <ClockCircleOutlined /> },
  running: { color: 'processing', text: '执行中', icon: <LoadingOutlined /> },
  success: { color: 'success', text: '成功', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
};

const CASE_STATUS_MAP: Record<string, { color: string; text: string }> = {
  PASS: { color: 'success', text: '通过' },
  FAIL: { color: 'error', text: '失败' },
  ERROR: { color: 'warning', text: '异常' },
};

const DEFAULT_CASE_JSON = `[
  {
    "case_id": "C001",
    "title": "开户接口测试",
    "type": "api",
    "steps": [
      {
        "action": "POST",
        "url": "/api/open_account",
        "headers": {},
        "body": {
          "name": "张三",
          "id_type": "身份证",
          "id_number": "110101199001011234"
        }
      }
    ],
    "assertions": [
      {
        "type": "equals",
        "path": "code",
        "expected": 200
      },
      {
        "type": "not_empty",
        "path": "data.account_id"
      }
    ]
  }
]`;

export default function ApiExecutionPage() {
  const [activeTab, setActiveTab] = useState('run');
  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [execLoading, setExecLoading] = useState(false);
  const [execTotal, setExecTotal] = useState(0);
  const [execPage, setExecPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  // 用例选择执行
  const [allCases, setAllCases] = useState<ApiCase[]>([]);
  const [selectedCaseIds, setSelectedCaseIds] = useState<number[]>([]);
  const [env, setEnv] = useState('test');
  const [baseUrl, setBaseUrl] = useState('http://localhost:8080');
  const [running, setRunning] = useState(false);

  // JSON执行
  const [caseJson, setCaseJson] = useState(DEFAULT_CASE_JSON);

  // 报告查看
  const [reportVisible, setReportVisible] = useState(false);
  const [currentReport, setCurrentReport] = useState<ExecutionReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchExecutions = useCallback(async () => {
    setExecLoading(true);
    try {
      const res: any = await listExecutions({
        status: statusFilter,
        page: execPage,
        page_size: 20,
      });
      const data = res?.data || res;
      setExecutions(data?.items || []);
      setExecTotal(data?.total || 0);
    } catch {
      message.error('加载执行列表失败');
    }
    setExecLoading(false);
  }, [statusFilter, execPage]);

  const fetchAllCases = useCallback(async () => {
    try {
      const res: any = await listCases({ page_size: 200 });
      const data = res?.data || res;
      setAllCases(data?.items || []);
    } catch {
      message.error('加载用例列表失败');
    }
  }, []);

  useEffect(() => { fetchExecutions(); fetchAllCases(); }, [fetchExecutions, fetchAllCases]);

  // 轮询进行中的任务
  useEffect(() => {
    const hasRunning = executions.some(e =>
      e.status === 'waiting' || e.status === 'pending' || e.status === 'running'
    );
    if (hasRunning && !pollingRef.current) {
      pollingRef.current = setInterval(fetchExecutions, 3000);
    } else if (!hasRunning && pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [executions, fetchExecutions]);

  const handleRun = async () => {
    if (selectedCaseIds.length === 0) {
      message.warning('请选择要执行的用例');
      return;
    }
    setRunning(true);
    try {
      const res: any = await runExecution({
        case_ids: selectedCaseIds,
        env,
        base_url: baseUrl,
      });
      const data = res?.data || res;
      message.success(`执行任务已提交 (ID: ${data.execution_id})`);
      setActiveTab('history');
      fetchExecutions();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '执行失败');
    }
    setRunning(false);
  };

  const handleRunJson = async () => {
    let parsed;
    try {
      parsed = JSON.parse(caseJson);
    } catch {
      message.error('JSON格式错误');
      return;
    }
    if (!Array.isArray(parsed)) {
      message.error('用例必须是数组格式');
      return;
    }
    setRunning(true);
    try {
      const res: any = await runExecutionJson({
        cases: parsed,
        env,
        base_url: baseUrl,
      });
      const data = res?.data || res;
      message.success(`执行任务已提交 (ID: ${data.execution_id})`);
      setActiveTab('history');
      fetchExecutions();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '执行失败');
    }
    setRunning(false);
  };

  const handleRetry = async (executionId: number) => {
    try {
      const res: any = await retryExecution(executionId);
      message.success(`重跑已提交 (ID: ${res?.data?.execution_id || res?.execution_id})`);
      fetchExecutions();
    } catch (e: any) {
      message.error(e?.response?.data?.detail || '重跑失败');
    }
  };

  const handleViewReport = async (executionId: number) => {
    setReportLoading(true);
    setReportVisible(true);
    setCurrentReport(null);
    try {
      const res: any = await getExecutionReport(executionId, 'json');
      const data = res?.data || res;
      setCurrentReport(data);
    } catch {
      message.error('获取报告失败');
    }
    setReportLoading(false);
  };

  const caseColumns: ColumnsType<ApiCase> = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60 },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '优先级', dataIndex: 'priority', key: 'priority', width: 80,
      render: (p: string) => {
        const colorMap: Record<string, string> = { high: 'red', medium: 'orange', low: 'blue' };
        return <Tag color={colorMap[p] || 'default'}>{p}</Tag>;
      },
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 80,
      render: (s: string) => <Tag>{s}</Tag>,
    },
  ];

  const execColumns: ColumnsType<ExecutionListItem> = [
    { title: 'ID', dataIndex: 'execution_id', key: 'execution_id', width: 70 },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 110,
      render: (status: string) => {
        const s = STATUS_MAP[status] || { color: 'default', text: status, icon: null };
        return <Tag color={s.color} icon={s.icon}>{s.text}</Tag>;
      },
    },
    {
      title: '来源', dataIndex: 'trigger_source', key: 'trigger_source', width: 120,
      render: (t: string) => t || '-',
    },
    {
      title: '通过/失败', key: 'counts', width: 120,
      render: (_: unknown, r: ExecutionListItem) => (
        <Space>
          <Text style={{ color: '#52c41a' }}>{r.success_count || 0}</Text>
          <Text>/</Text>
          <Text style={{ color: '#f5222d' }}>{r.failed_count || 0}</Text>
        </Space>
      ),
    },
    {
      title: '耗时(s)', dataIndex: 'duration', key: 'duration', width: 90,
      render: (d: number | null) => d != null ? d.toFixed(1) : '-',
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (t: string) => t || '-',
    },
    {
      title: '操作', key: 'action', width: 150,
      render: (_: unknown, r: ExecutionListItem) => (
        <Space>
          <Tooltip title="查看报告">
            <Button
              type="link"
              size="small"
              icon={<EyeOutlined />}
              disabled={r.status === 'waiting' || r.status === 'pending' || r.status === 'running'}
              onClick={() => handleViewReport(r.execution_id)}
            />
          </Tooltip>
          <Popconfirm title="确认重跑？" onConfirm={() => handleRetry(r.execution_id)}>
            <Tooltip title="重跑">
              <Button type="link" size="small" icon={<RedoOutlined />} />
            </Tooltip>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Typography.Title level={3} style={{ marginBottom: 16 }}>
        <ThunderboltOutlined /> 执行中心
      </Typography.Title>

      <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
        {
          key: 'run',
          label: '执行中心',
          children: (
            <Space direction="vertical" style={{ width: '100%' }} size="middle">
              <Card title="环境配置" size="small">
                <Space wrap>
                  <Space>
                    <Text>环境:</Text>
                    <Select value={env} onChange={setEnv} style={{ width: 120 }}
                      options={[
                        { value: 'test', label: '测试环境' },
                        { value: 'staging', label: '预发环境' },
                        { value: 'production', label: '生产环境' },
                      ]}
                    />
                  </Space>
                  <Space>
                    <Text>Base URL:</Text>
                    <Input value={baseUrl} onChange={e => setBaseUrl(e.target.value)} style={{ width: 300 }} />
                  </Space>
                </Space>
              </Card>

              <Tabs items={[
                {
                  key: 'select',
                  label: '选择用例',
                  children: (
                    <Card title="选择测试用例" size="small">
                      <Table
                        columns={caseColumns}
                        dataSource={allCases}
                        rowKey="id"
                        size="small"
                        pagination={{ pageSize: 10 }}
                        rowSelection={{
                          selectedRowKeys: selectedCaseIds,
                          onChange: (keys) => setSelectedCaseIds(keys as number[]),
                        }}
                        locale={{ emptyText: <Empty description="暂无用例" /> }}
                      />
                      <div style={{ marginTop: 16, textAlign: 'right' }}>
                        <Button
                          type="primary"
                          icon={<PlayCircleOutlined />}
                          loading={running}
                          onClick={handleRun}
                          disabled={selectedCaseIds.length === 0}
                        >
                          执行 ({selectedCaseIds.length})
                        </Button>
                      </div>
                    </Card>
                  ),
                },
                {
                  key: 'json',
                  label: 'JSON执行',
                  children: (
                    <Card title="直接提交Case JSON" size="small">
                      <Alert
                        type="info"
                        message="输入符合Case Runner标准结构的JSON数组，直接提交执行"
                        style={{ marginBottom: 12 }}
                        showIcon
                      />
                      <TextArea
                        value={caseJson}
                        onChange={e => setCaseJson(e.target.value)}
                        rows={12}
                        style={{ fontFamily: 'monospace', fontSize: 12 }}
                      />
                      <div style={{ marginTop: 12, textAlign: 'right' }}>
                        <Button
                          type="primary"
                          icon={<CodeOutlined />}
                          loading={running}
                          onClick={handleRunJson}
                        >
                          执行JSON
                        </Button>
                      </div>
                    </Card>
                  ),
                },
              ]} />
            </Space>
          ),
        },
        {
          key: 'history',
          label: '执行记录',
          children: (
            <Card>
              <Space style={{ marginBottom: 12 }}>
                <Select
                  value={statusFilter}
                  onChange={v => { setStatusFilter(v); setExecPage(1); }}
                  style={{ width: 140 }}
                  allowClear
                  placeholder="状态筛选"
                  options={[
                    { value: undefined, label: '全部状态' },
                    { value: 'waiting', label: '排队中' },
                    { value: 'running', label: '执行中' },
                    { value: 'success', label: '成功' },
                    { value: 'failed', label: '失败' },
                  ]}
                />
                <Button icon={<ReloadOutlined />} onClick={fetchExecutions}>刷新</Button>
              </Space>
              <Table
                columns={execColumns}
                dataSource={executions}
                rowKey="execution_id"
                loading={execLoading}
                pagination={{ current: execPage, total: execTotal, pageSize: 20, onChange: setExecPage }}
                locale={{ emptyText: <Empty description="暂无执行记录" /> }}
              />
            </Card>
          ),
        },
      ]} />

      {/* 报告弹窗 - 含步骤级HTTP日志 */}
      <ReportModal
        visible={reportVisible}
        report={currentReport}
        loading={reportLoading}
        onClose={() => setReportVisible(false)}
        onRetry={(executionId) => { handleRetry(executionId); setReportVisible(false); }}
      />
    </div>
  );
}

// ========== 报告弹窗（含步骤级HTTP日志） ==========
function ReportModal({
  visible, report, loading, onClose, onRetry,
}: {
  visible: boolean;
  report: ExecutionReport | null;
  loading: boolean;
  onClose: () => void;
  onRetry: (executionId: number) => void;
}) {
  return (
    <Modal
      title={`测试报告 - E${report?.execution_id || ''}`}
      open={visible}
      onCancel={onClose}
      footer={report ? [
        <Button key="retry" icon={<RedoOutlined />} onClick={() => onRetry(report.execution_id)}>重跑</Button>,
        <Button key="close" onClick={onClose}>关闭</Button>,
      ] : null}
      width={960}
    >
      {loading ? (
        <div style={{ textAlign: 'center', padding: 40 }}>加载中...</div>
      ) : report ? (
        <div>
          <Space style={{ marginBottom: 16 }}>
            <Text>总计: {report.total}</Text>
            <Text style={{ color: '#52c41a' }}>通过: {report.passed}</Text>
            <Text style={{ color: '#f5222d' }}>失败: {report.failed}</Text>
            <Text>通过率: {report.total > 0 ? Math.round(report.passed / report.total * 100) : 0}%</Text>
          </Space>
          <Table
            columns={[
              { title: '用例ID', dataIndex: 'case_id', width: 90 },
              { title: '标题', dataIndex: 'title', ellipsis: true },
              {
                title: '状态', dataIndex: 'status', width: 90,
                render: (s: string) => <Tag color={CASE_STATUS_MAP[s]?.color || 'default'}>{CASE_STATUS_MAP[s]?.text || s}</Tag>,
              },
              { title: '耗时', dataIndex: 'duration_ms', width: 90, render: (d: number) => `${d}ms` },
              { title: '错误', dataIndex: 'error', ellipsis: true, render: (e: string) => e || '-' },
            ]}
            dataSource={report.cases || []}
            rowKey="case_id"
            size="small"
            pagination={false}
            expandable={{
              expandedRowRender: (record: CaseResult) => (
                <CaseDetailExpand record={record} />
              ),
            }}
          />
        </div>
      ) : (
        <Empty description="暂无报告数据" />
      )}
    </Modal>
  );
}

// ========== 用例展开详情（步骤HTTP日志 + 断言） ==========
function CaseDetailExpand({ record }: { record: CaseResult }) {
  return (
    <div style={{ padding: '8px 0' }}>
      {/* 步骤级HTTP日志 */}
      {record.steps && record.steps.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <Text strong style={{ marginBottom: 8, display: 'block' }}>HTTP请求日志</Text>
          <Table
            size="small"
            dataSource={record.steps}
            rowKey="step_index"
            pagination={false}
            columns={[
              { title: '#', dataIndex: 'step_index', width: 40 },
              { title: '方法', dataIndex: 'action', width: 70 },
              { title: 'URL', dataIndex: 'url', ellipsis: true },
              {
                title: '状态码', dataIndex: 'status_code', width: 80,
                render: (v: number | undefined) => {
                  if (v == null) return '-';
                  const color = v < 400 ? '#52c41a' : '#f5222d';
                  return <Text style={{ color, fontWeight: 'bold' }}>{v}</Text>;
                },
              },
              {
                title: '耗时', dataIndex: 'elapsed_ms', width: 80,
                render: (v: number | undefined) => v != null ? `${v}ms` : '-',
              },
              {
                title: '错误', dataIndex: 'error', ellipsis: true,
                render: (v: string | undefined) => v ? <Text type="danger">{v}</Text> : '-',
              },
            ]}
          />
        </div>
      )}

      {/* 断言详情 */}
      {record.assertion_result && record.assertion_result.results?.length > 0 && (
        <div>
          <Text strong style={{ marginBottom: 8, display: 'block' }}>断言详情</Text>
          <Table
            size="small"
            dataSource={record.assertion_result.results}
            rowKey={(_, i) => String(i)}
            pagination={false}
            columns={[
              { title: '类型', dataIndex: 'type', width: 100 },
              { title: '路径', dataIndex: 'path', width: 150 },
              { title: '期望', dataIndex: 'expected', width: 150, render: (v: unknown) => JSON.stringify(v) },
              { title: '实际', dataIndex: 'actual', width: 150, render: (v: unknown) => JSON.stringify(v) },
              {
                title: '结果', dataIndex: 'passed', width: 80,
                render: (p: boolean) => p
                  ? <Tag color="success">通过</Tag>
                  : <Tag color="error">失败</Tag>,
              },
              { title: '信息', dataIndex: 'message', ellipsis: true },
            ]}
          />
        </div>
      )}

      {!record.steps?.length && !record.assertion_result?.results?.length && (
        <Empty description="无步骤和断言详情" image={Empty.PRESENTED_IMAGE_SIMPLE} />
      )}
    </div>
  );
}
