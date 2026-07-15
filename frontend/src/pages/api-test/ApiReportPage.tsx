/**
 * 接口测试报告页面
 * 报告弹窗（统计+用例结果+断言详情）+ 导出 + 重跑 + 失败分析
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Table, Button, Tag, Space, Typography, Select,
  Modal, message, Descriptions, Progress, Spin, Empty,
  Switch, Popconfirm,
} from 'antd';
import {
  ReloadOutlined, EyeOutlined, FileTextOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  LoadingOutlined, RedoOutlined, DownloadOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listExecutions,
  ExecutionListItem, retryExecution,
} from '../../services/apiExec';
import {
  getExecutionReport, exportReport,
  ExecutionReport, CaseResult,
} from '../../services/apiReport';

const { Text } = Typography;

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

export default function ApiReportPage() {
  const [executions, setExecutions] = useState<ExecutionListItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  const [reportVisible, setReportVisible] = useState(false);
  const [currentReport, setCurrentReport] = useState<ExecutionReport | null>(null);
  const [reportLoading, setReportLoading] = useState(false);
  const [showFailedOnly, setShowFailedOnly] = useState(false);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchExecutions = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await listExecutions({
        status: statusFilter,
        page,
        page_size: 20,
      });
      const data = res?.data || res;
      setExecutions(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('加载报告数据失败');
    }
    setLoading(false);
  }, [statusFilter, page]);

  useEffect(() => { fetchExecutions(); }, [fetchExecutions]);

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

  const handleViewReport = async (executionId: number) => {
    setReportLoading(true);
    setReportVisible(true);
    setCurrentReport(null);
    setShowFailedOnly(false);
    try {
      const res: any = await getExecutionReport(executionId, 'json');
      const data = res?.data || res;
      setCurrentReport(data);
    } catch {
      message.error('获取报告失败');
    }
    setReportLoading(false);
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

  const handleExport = async (executionId: number, format: 'html' | 'markdown') => {
    try {
      const res: any = await exportReport(executionId, format);
      const blob = new Blob([res], { type: format === 'html' ? 'text/html' : 'text/markdown' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `report_${executionId}.${format === 'html' ? 'html' : 'md'}`;
      a.click();
      URL.revokeObjectURL(url);
      message.success('导出成功');
    } catch { message.error('导出失败'); }
  };

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
      title: '操作', key: 'action', width: 180,
      render: (_: unknown, r: ExecutionListItem) => (
        <Space>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            disabled={r.status === 'waiting' || r.status === 'pending' || r.status === 'running'}
            onClick={() => handleViewReport(r.execution_id)}
          >
            报告
          </Button>
          <Popconfirm title="确认重跑？" onConfirm={() => handleRetry(r.execution_id)}>
            <Button type="link" size="small" icon={<RedoOutlined />}>重跑</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  const reportCaseColumns: ColumnsType<CaseResult> = [
    { title: '用例ID', dataIndex: 'case_id', key: 'case_id', width: 90 },
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (s: string) => {
        const m = CASE_STATUS_MAP[s] || { color: 'default', text: s };
        return <Tag color={m.color}>{m.text}</Tag>;
      },
    },
    {
      title: '耗时', dataIndex: 'duration_ms', key: 'duration_ms', width: 90,
      render: (d: number) => `${d}ms`,
    },
    {
      title: '断言', key: 'assertion', width: 120,
      render: (_: unknown, r: CaseResult) => {
        const ar = r.assertion_result;
        if (!ar) return '-';
        return (
          <Space>
            <Text style={{ color: '#52c41a' }}>{ar.passed_count}通过</Text>
            {ar.failed_count > 0 && <Text style={{ color: '#f5222d' }}>{ar.failed_count}失败</Text>}
          </Space>
        );
      },
    },
    {
      title: '错误', dataIndex: 'error', key: 'error', ellipsis: true,
      render: (e: string) => e || '-',
    },
  ];

  const filteredCases = showFailedOnly
    ? (currentReport?.cases || []).filter(c => c.status === 'FAIL' || c.status === 'ERROR')
    : (currentReport?.cases || []);

  return (
    <div>
      <Typography.Title level={3} style={{ marginBottom: 16 }}>
        <FileTextOutlined /> 测试报告
      </Typography.Title>

      <Card>
        <Space style={{ marginBottom: 12 }}>
          <Select
            value={statusFilter}
            onChange={v => { setStatusFilter(v); setPage(1); }}
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
          loading={loading}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage }}
          locale={{ emptyText: <Empty description="暂无执行记录" /> }}
        />
      </Card>

      {/* 报告详情弹窗 */}
      <Modal
        title={<><FileTextOutlined /> 测试报告 - E{currentReport?.execution_id || ''}</>}
        open={reportVisible}
        onCancel={() => setReportVisible(false)}
        footer={currentReport ? [
          <Button key="export-html" icon={<DownloadOutlined />} onClick={() => handleExport(currentReport.execution_id, 'html')}>导出HTML</Button>,
          <Button key="export-md" icon={<DownloadOutlined />} onClick={() => handleExport(currentReport.execution_id, 'markdown')}>导出Markdown</Button>,
          <Button key="retry" icon={<RedoOutlined />} onClick={() => { handleRetry(currentReport.execution_id); setReportVisible(false); }}>重跑</Button>,
          <Button key="close" onClick={() => setReportVisible(false)}>关闭</Button>,
        ] : null}
        width={960}
      >
        {reportLoading ? (
          <div style={{ textAlign: 'center', padding: 40 }}><Spin size="large" /></div>
        ) : currentReport ? (
          <div>
            <Descriptions bordered size="small" column={4} style={{ marginBottom: 16 }}>
              <Descriptions.Item label="总计">{currentReport.total}</Descriptions.Item>
              <Descriptions.Item label="通过">
                <Text style={{ color: '#52c41a', fontWeight: 'bold' }}>{currentReport.passed}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="失败">
                <Text style={{ color: '#f5222d', fontWeight: 'bold' }}>{currentReport.failed}</Text>
              </Descriptions.Item>
              <Descriptions.Item label="通过率">
                <Progress
                  percent={currentReport.total > 0 ? Math.round(currentReport.passed / currentReport.total * 100) : 0}
                  size="small"
                  status={currentReport.failed > 0 ? 'exception' : 'success'}
                />
              </Descriptions.Item>
            </Descriptions>

            <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <Space>
                <Switch
                  checked={showFailedOnly}
                  onChange={setShowFailedOnly}
                  checkedChildren="仅看失败"
                  unCheckedChildren="全部"
                />
                {showFailedOnly && <Text type="secondary">筛选出 {filteredCases.length} 条失败用例</Text>}
              </Space>
            </div>

            <Table
              columns={reportCaseColumns}
              dataSource={filteredCases}
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
    </div>
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
