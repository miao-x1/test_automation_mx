/**
 * 执行详情页
 *
 * 路由: /execution/detail/:id
 *
 * 功能:
 *   1. 执行基本信息 (状态/类型/耗时/通过失败数)
 *   2. 用例结果表格 (从 analysis.cases 展开)
 *   3. 执行日志
 *   4. 报告下载 (HTML/JSON/Excel)
 *   5. AI 智能分析
 */
import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Card,
  Descriptions,
  Table,
  Tag,
  Button,
  Space,
  message,
  Typography,
  Spin,
  Alert,
  Statistic,
  Row,
  Col,
  Collapse,
} from 'antd';
import {
  ArrowLeftOutlined,
  FileTextOutlined,
  FileExcelOutlined,
  RobotOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import request from '@/services/request';

const { Title, Text } = Typography;

/** 格式化耗时 */
function formatDuration(d?: number): string {
  if (!d && d !== 0) return '-';
  if (d < 60) return d.toFixed(2) + 's';
  const m = Math.floor(d / 60);
  const s = Math.round(d % 60);
  return m + 'm ' + s + 's';
}

const STATUS_META: Record<string, { color: string; text: string }> = {
  success: { color: 'green', text: '成功' },
  failed: { color: 'red', text: '失败' },
  running: { color: 'blue', text: '执行中' },
  waiting: { color: 'orange', text: '等待中' },
  cancelled: { color: 'default', text: '已取消' },
  pending: { color: 'orange', text: '排队中' },
};

export default function ExecutionDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<any>(null);
  const [logs, setLogs] = useState<string>('');
  const [analyzing, setAnalyzing] = useState(false);

  const fetchDetail = useCallback(async () => {
    if (!id) return;
    setLoading(true);
    try {
      const res: any = await request.get('/executions/' + id);
      const d = res.data || res;
      setDetail(d);
    } catch (e: any) {
      message.error(e?.message || '加载执行详情失败');
    } finally {
      setLoading(false);
    }
  }, [id]);

  const fetchLogs = useCallback(async () => {
    if (!id) return;
    try {
      const res: any = await request.get('/executions/' + id + '/logs', {
        responseType: 'text',
        transformResponse: [(v: string) => v],
      });
      setLogs(typeof res === 'string' ? res : res?.data || '无日志');
    } catch {
      setLogs('加载日志失败');
    }
  }, [id]);

  useEffect(() => {
    fetchDetail();
    fetchLogs();
  }, [fetchDetail, fetchLogs]);

  const handleAnalyze = async () => {
    if (!id) return;
    setAnalyzing(true);
    try {
      await request.post('/executions/' + id + '/analyze');
      message.success('AI 分析完成');
      fetchDetail();
    } catch (e: any) {
      message.error(e?.message || 'AI 分析失败');
    } finally {
      setAnalyzing(false);
    }
  };

  if (loading && !detail) {
    return (
      <div style={{ textAlign: 'center', padding: 80 }}>
        <Spin size="large" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div style={{ padding: 24 }}>
        <Alert message="未找到执行记录" type="warning" showIcon
          action={<Button onClick={() => navigate('/execution')}>返回列表</Button>}
        />
      </div>
    );
  }

  const statusInfo = STATUS_META[detail.status] || { color: 'default', text: detail.status };
  const analysis = detail.analysis || {};
  const cases: any[] = analysis.cases || [];
  const total = analysis.total || (detail.success_count || 0) + (detail.failed_count || 0);
  const passed = analysis.passed || detail.success_count || 0;
  const failed = analysis.failed || detail.failed_count || 0;
  const passRate = total > 0 ? ((passed / total) * 100).toFixed(1) : '0';

  // 展平子测试结果
  const expandedCases: any[] = [];
  cases.forEach((c: any, idx: number) => {
    const subTests = c.assertion_result?.results;
    if (Array.isArray(subTests) && subTests.length > 0) {
      subTests.forEach((st: any) => {
        expandedCases.push({
          key: idx + '-' + st.name,
          case_id: st.name || c.case_id,
          title: st.name || c.title,
          status: st.passed ? 'PASS' : 'FAIL',
          duration_ms: st.duration_ms || 0,
          error: st.error || null,
        });
      });
    } else {
      expandedCases.push({
        key: String(idx),
        case_id: c.case_id || ('Case-' + (idx + 1)),
        title: c.title || '',
        status: c.status || 'UNKNOWN',
        duration_ms: c.duration_ms || 0,
        error: c.error || null,
      });
    }
  });

  return (
    <div>
      <Card
        title={
          <Space>
            <Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/execution')}>返回</Button>
            <Title level={4} style={{ margin: 0 }}>执行详情 #{id}</Title>
            <Tag color={statusInfo.color}>{statusInfo.text}</Tag>
          </Space>
        }
        extra={
          <Space>
            <Button icon={<ReloadOutlined />} onClick={fetchDetail}>刷新</Button>
            <Button icon={<RobotOutlined />} loading={analyzing} onClick={handleAnalyze}>AI 分析</Button>
            <Button icon={<FileTextOutlined />} onClick={() => window.open('/api/executions/' + id + '/report?format=html', '_blank')}>查看报告</Button>
            <Button icon={<FileExcelOutlined />} onClick={() => window.open('/api/executions/' + id + '/report?format=excel', '_blank')}>下载Excel</Button>
          </Space>
        }
      >
        {/* 统计卡片 */}
        <Row gutter={16} style={{ marginBottom: 24 }}>
          <Col span={6}>
            <Card size="small"><Statistic title="总计" value={total} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="通过" value={passed} valueStyle={{ color: '#52c41a' }} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="失败" value={failed} valueStyle={{ color: '#f5222d' }} /></Card>
          </Col>
          <Col span={6}>
            <Card size="small"><Statistic title="通过率" value={passRate} suffix="%" valueStyle={{ color: Number(passRate) >= 80 ? '#52c41a' : '#fa8c16' }} /></Card>
          </Col>
        </Row>

        {/* 基本信息 */}
        <Descriptions title="执行信息" bordered column={3} size="small" style={{ marginBottom: 24 }}>
          <Descriptions.Item label="执行ID">{detail.id}</Descriptions.Item>
          <Descriptions.Item label="类型">{detail.execution_type}</Descriptions.Item>
          <Descriptions.Item label="状态"><Tag color={statusInfo.color}>{statusInfo.text}</Tag></Descriptions.Item>
          <Descriptions.Item label="触发来源">{detail.trigger_source || '-'}</Descriptions.Item>
          <Descriptions.Item label="耗时">{formatDuration(detail.duration)}</Descriptions.Item>
          <Descriptions.Item label="通过/失败">{passed} / {failed}</Descriptions.Item>
          <Descriptions.Item label="开始时间">{detail.start_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="结束时间">{detail.end_time || '-'}</Descriptions.Item>
          <Descriptions.Item label="创建时间">{detail.created_at || '-'}</Descriptions.Item>
          {detail.error_message && (
            <Descriptions.Item label="错误信息" span={3}>
              <Text type="danger">{detail.error_message}</Text>
            </Descriptions.Item>
          )}
        </Descriptions>

        {/* 用例结果表格 */}
        <Title level={5}>用例结果</Title>
        <Table
          dataSource={expandedCases}
          rowKey="key"
          size="small"
          pagination={false}
          style={{ marginBottom: 24 }}
          columns={[
            { title: '用例ID', dataIndex: 'case_id', width: 200 },
            { title: '标题', dataIndex: 'title' },
            {
              title: '状态', dataIndex: 'status', width: 100,
              render: (s: string) => {
                const color = s === 'PASS' ? 'green' : s === 'FAIL' ? 'red' : 'default';
                return <Tag color={color}>{s}</Tag>;
              },
            },
            { title: '耗时(ms)', dataIndex: 'duration_ms', width: 120 },
            { title: '错误信息', dataIndex: 'error', render: (e: string) => e ? <Text type="danger" style={{ fontSize: 12 }}>{e}</Text> : '-' },
          ]}
        />

        {/* 执行日志 */}
        <Collapse
          items={[{
            key: 'logs',
            label: '执行日志',
            children: (
              <pre style={{ background: '#f5f5f5', padding: 12, borderRadius: 4, fontSize: 12, maxHeight: 300, overflow: 'auto' }}>
                {logs || '无日志'}
              </pre>
            ),
          }]}
        />
      </Card>
    </div>
  );
}
