/**
 * 执行中心（Execution Center）
 *
 * 职责：展示所有执行记录汇总，包括需求驱动和上传脚本执行
 * 入口：执行中心 → TaskDetail
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Table, Button, Tag, Space, Select, message,
} from 'antd';
import {
  ThunderboltOutlined, EyeOutlined, ReloadOutlined, BugOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined, SyncOutlined,
} from '@ant-design/icons';
import request from '../services/request';
import { PageHeader } from '../components/UI';

interface ExecutionRecordItem {
  id: number;
  task_id: number;
  task_name: string;
  status: string;
  duration: number | null;
  success_count: number;
  failed_count: number;
  error_message: string | null;
  log_content: string | null;
  analysis: { root_cause?: string; suggestion?: string } | null;
  created_at: string;
}

const statusMap: Record<string, { color: string; text: string; icon: React.ReactNode }> = {
  pending: { color: 'default', text: '待执行', icon: <ClockCircleOutlined /> },
  running: { color: 'processing', text: '执行中', icon: <SyncOutlined spin /> },
  success: { color: 'success', text: '成功', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', text: '失败', icon: <CloseCircleOutlined /> },
};

export default function ExecutionCenter() {
  const navigate = useNavigate();
  const [records, setRecords] = useState<ExecutionRecordItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const params: any = { page, page_size: 20 };
      if (statusFilter) params.status = statusFilter;
      const res: any = await request.get('/executions/list', { params });
      const data = res?.data || res;
      setRecords(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('获取执行记录失败');
    }
    setLoading(false);
  }, [page, statusFilter]);

  useEffect(() => { fetchRecords(); }, [fetchRecords]);

  const successCount = records.filter(r => r.status === 'success').length;
  const failedCount = records.filter(r => r.status === 'failed').length;
  const pendingCount = records.filter(r => r.status === 'pending' || r.status === 'running').length;

  const columns = [
    {
      title: 'ID', dataIndex: 'id', key: 'id', width: 60,
    },
    {
      title: '任务名称', dataIndex: 'task_name', key: 'task_name', width: 200, ellipsis: true,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 100,
      render: (status: string) => {
        const cfg = statusMap[status] || statusMap.pending;
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.text}</Tag>;
      },
    },
    {
      title: '耗时', dataIndex: 'duration', key: 'duration', width: 80,
      render: (v: number | null) => v != null ? `${v}s` : '-',
    },
    {
      title: '通过/失败', key: 'counts', width: 100,
      render: (_: unknown, r: ExecutionRecordItem) => (
        <span>
          <span style={{ color: '#52c41a' }}>{r.success_count}</span>
          {' / '}
          <span style={{ color: '#ff4d4f' }}>{r.failed_count}</span>
        </span>
      ),
    },
    {
      title: '错误信息', dataIndex: 'error_message', key: 'error_message', ellipsis: true,
      render: (v: string) => v || '-',
    },
    {
      title: '缺陷分析', key: 'analysis', width: 120,
      render: (_: unknown, r: ExecutionRecordItem) => {
        if (r.status !== 'failed') return <Tag>无</Tag>;
        if (r.analysis) return <Tag color="orange" icon={<BugOutlined />}>已分析</Tag>;
        return <Tag color="default">待分析</Tag>;
      },
    },
    {
      title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: ExecutionRecordItem) => (
        <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/task/${record.task_id}`)}>
          查看详情
        </Button>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="执行中心"
        icon={<ThunderboltOutlined />}
        subtitle="查看所有执行记录，包括需求驱动和上传脚本执行"
      />

      <Space style={{ marginBottom: 16 }} size="large">
        <Card size="small" style={{ minWidth: 120 }}>
          <Space>
            <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 20 }} />
            <div>
              <div style={{ fontSize: 12, color: '#999' }}>成功</div>
              <div style={{ fontSize: 20, fontWeight: 600, color: '#52c41a' }}>{successCount}</div>
            </div>
          </Space>
        </Card>
        <Card size="small" style={{ minWidth: 120 }}>
          <Space>
            <CloseCircleOutlined style={{ color: '#ff4d4f', fontSize: 20 }} />
            <div>
              <div style={{ fontSize: 12, color: '#999' }}>失败</div>
              <div style={{ fontSize: 20, fontWeight: 600, color: '#ff4d4f' }}>{failedCount}</div>
            </div>
          </Space>
        </Card>
        <Card size="small" style={{ minWidth: 120 }}>
          <Space>
            <ClockCircleOutlined style={{ color: '#1890ff', fontSize: 20 }} />
            <div>
              <div style={{ fontSize: 12, color: '#999' }}>待执行</div>
              <div style={{ fontSize: 20, fontWeight: 600, color: '#1890ff' }}>{pendingCount}</div>
            </div>
          </Space>
        </Card>
        <Select
          value={statusFilter}
          onChange={v => { setStatusFilter(v); setPage(1); }}
          style={{ width: 140 }}
          allowClear
          placeholder="状态筛选"
          options={[
            { value: undefined, label: '全部状态' },
            { value: 'success', label: '成功' },
            { value: 'failed', label: '失败' },
            { value: 'pending', label: '待执行' },
            { value: 'running', label: '执行中' },
          ]}
        />
      </Space>

      <Card extra={<Button icon={<ReloadOutlined />} onClick={fetchRecords}>刷新</Button>}>
        <Table
          columns={columns}
          dataSource={records}
          rowKey="id"
          loading={loading}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        />
      </Card>
    </div>
  );
}
