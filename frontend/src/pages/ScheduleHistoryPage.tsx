/**
 * 定时任务执行历史记录
 *
 * 展示所有定时任务的执行历史，支持筛选、搜索、分页、重试
 * 详情通过抽屉展示
 */
import { useState, useCallback, useEffect } from 'react';
import {
  Card, Table, Button, Space, Tag, Select, Input, message,
  Drawer, Descriptions, Typography, Alert, Spin,
} from 'antd';
import {
  HistoryOutlined, ReloadOutlined, RedoOutlined,
  CheckCircleOutlined, CloseCircleOutlined, ClockCircleOutlined,
  SyncOutlined, UserOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  listScheduleHistory, getScheduleHistoryDetail, retryScheduleHistory,
} from '../services/schedule';
import type { ScheduleRunLogItem } from '../services/schedule';
import { PageHeader } from '../components/UI';

const { Text, Paragraph } = Typography;
const { Search } = Input;

// ==================== 状态/触发方式映射 ====================
const STATUS_MAP: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  running: { color: 'processing', label: '执行中', icon: <SyncOutlined spin /> },
  success: { color: 'success', label: '成功', icon: <CheckCircleOutlined /> },
  failed: { color: 'error', label: '失败', icon: <CloseCircleOutlined /> },
  timeout: { color: 'warning', label: '超时', icon: <ClockCircleOutlined /> },
  cancelled: { color: 'default', label: '已取消', icon: <CloseCircleOutlined /> },
};

const TRIGGER_MAP: Record<string, { color: string; label: string }> = {
  schedule: { color: 'blue', label: '定时触发' },
  manual: { color: 'green', label: '手动触发' },
  retry: { color: 'orange', label: '重试' },
};

// ==================== 详情抽屉 ====================
function DetailDrawer({ recordId, open, onClose }: { recordId: number | null; open: boolean; onClose: () => void }) {
  const [detail, setDetail] = useState<ScheduleRunLogItem | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && recordId) {
      setLoading(true);
      getScheduleHistoryDetail(recordId)
        .then(data => setDetail(data))
        .catch(() => message.error('获取详情失败'))
        .finally(() => setLoading(false));
    } else {
      setDetail(null);
    }
  }, [open, recordId]);

  const statusCfg = STATUS_MAP[detail?.status || ''] || { color: 'default', label: detail?.status, icon: null };
  const triggerCfg = TRIGGER_MAP[detail?.trigger_type || ''] || { color: 'default', label: detail?.trigger_type };

  return (
    <Drawer title="执行历史详情" open={open} onClose={onClose} width={640} loading={loading}>
      {detail ? (
        <Descriptions column={2} bordered size="small">
          <Descriptions.Item label="任务名称" span={2}>{detail.schedule_name}</Descriptions.Item>
          <Descriptions.Item label="执行状态">
            <Tag color={statusCfg.color} icon={statusCfg.icon}>{statusCfg.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="触发方式">
            <Tag color={triggerCfg.color}>{triggerCfg.label}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="开始时间">
            {detail.started_at ? new Date(detail.started_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="结束时间">
            {detail.finished_at ? new Date(detail.finished_at).toLocaleString('zh-CN') : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="耗时">
            {detail.duration != null ? `${detail.duration}秒` : '-'}
          </Descriptions.Item>
          <Descriptions.Item label="重试次数">{detail.retry_count || 0}</Descriptions.Item>
          <Descriptions.Item label="操作人" span={2}>
            {detail.operator ? <Space><UserOutlined />{detail.operator}</Space> : '系统'}
          </Descriptions.Item>
          <Descriptions.Item label="结果摘要" span={2}>
            {detail.result_summary || '-'}
          </Descriptions.Item>
          {detail.error_message && (
            <Descriptions.Item label="失败原因" span={2}>
              <Alert type="error" message={detail.error_message} showIcon style={{ marginBottom: 0 }} />
            </Descriptions.Item>
          )}
          {detail.logs && (
            <Descriptions.Item label="执行日志" span={2}>
              <Paragraph
                ellipsis={{ rows: 10, expandable: true, symbol: '展开全部' }}
                style={{ marginBottom: 0, fontFamily: 'monospace', fontSize: 12, backgroundColor: '#f5f5f5', padding: 8, borderRadius: 4, whiteSpace: 'pre-wrap' }}
              >
                {detail.logs}
              </Paragraph>
            </Descriptions.Item>
          )}
          {detail.execution_detail && (
            <Descriptions.Item label="关联执行记录" span={2}>
              <Space>
                <Tag>执行ID: {detail.execution_detail.id}</Tag>
                <Tag color={detail.execution_detail.status === 'success' ? 'green' : 'red'}>
                  {detail.execution_detail.status}
                </Tag>
                {detail.execution_detail.duration != null && <Tag>耗时: {detail.execution_detail.duration}s</Tag>}
              </Space>
            </Descriptions.Item>
          )}
        </Descriptions>
      ) : (
        <Spin />
      )}
    </Drawer>
  );
}

// ==================== 主页面 ====================
export default function ScheduleHistoryPage() {
  const [records, setRecords] = useState<ScheduleRunLogItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [triggerFilter, setTriggerFilter] = useState<string | undefined>();
  const [keyword, setKeyword] = useState('');
  const [detailId, setDetailId] = useState<number | null>(null);

  const fetchRecords = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listScheduleHistory({
        status: statusFilter,
        trigger_type: triggerFilter,
        keyword: keyword || undefined,
        page,
        page_size: 20,
      });
      setRecords(data?.items || []);
      setTotal(data?.total || 0);
    } catch {
      message.error('获取历史记录失败');
    }
    setLoading(false);
  }, [statusFilter, triggerFilter, keyword, page]);

  useEffect(() => { fetchRecords(); }, [fetchRecords]);

  const handleRetry = async (id: number) => {
    try {
      await retryScheduleHistory(id);
      message.success('已触发重试');
      fetchRecords();
    } catch {
      message.error('重试失败');
    }
  };

  const columns: ColumnsType<ScheduleRunLogItem> = [
    { title: 'ID', dataIndex: 'id', width: 55 },
    {
      title: '任务名称', dataIndex: 'schedule_name', width: 180, ellipsis: true,
      render: (v: string, r: ScheduleRunLogItem) => (
        <Button type="link" size="small" style={{ padding: 0 }} onClick={() => setDetailId(r.id)}>
          {v || `定时任务#${r.schedule_task_id}`}
        </Button>
      ),
    },
    {
      title: '执行状态', dataIndex: 'status', width: 90,
      render: (s: string) => {
        const cfg = STATUS_MAP[s] || { color: 'default', label: s, icon: null };
        return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
      },
    },
    {
      title: '触发方式', dataIndex: 'trigger_type', width: 90,
      render: (t: string) => {
        const cfg = TRIGGER_MAP[t] || { color: 'default', label: t };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: '执行时间', dataIndex: 'started_at', width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '耗时', dataIndex: 'duration', width: 70,
      render: (v: number | null) => v != null ? `${v}s` : '-',
    },
    {
      title: '操作人', dataIndex: 'operator', width: 90, ellipsis: true,
      render: (v: string) => v || <Text type="secondary">系统</Text>,
    },
    {
      title: '失败原因', dataIndex: 'error_message', ellipsis: true,
      render: (v: string) => v ? <Text type="danger">{v}</Text> : '-',
    },
    {
      title: '操作', width: 120, fixed: 'right',
      render: (_: unknown, r: ScheduleRunLogItem) => (
        <Space size="small">
          <Button type="link" size="small" onClick={() => setDetailId(r.id)}>详情</Button>
          {(r.status === 'failed' || r.status === 'timeout') && (
            <Button type="link" size="small" icon={<RedoOutlined />} onClick={() => handleRetry(r.id)}>重试</Button>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="历史记录"
        icon={<HistoryOutlined />}
        subtitle="定时任务执行历史，支持筛选、搜索与重试"
      />

      <Card extra={
        <Space>
          <Select placeholder="执行状态" allowClear style={{ width: 110 }} value={statusFilter} onChange={v => { setStatusFilter(v); setPage(1); }}>
            <Select.Option value="success">成功</Select.Option>
            <Select.Option value="failed">失败</Select.Option>
            <Select.Option value="running">执行中</Select.Option>
            <Select.Option value="timeout">超时</Select.Option>
          </Select>
          <Select placeholder="触发方式" allowClear style={{ width: 110 }} value={triggerFilter} onChange={v => { setTriggerFilter(v); setPage(1); }}>
            <Select.Option value="schedule">定时触发</Select.Option>
            <Select.Option value="manual">手动触发</Select.Option>
            <Select.Option value="retry">重试</Select.Option>
          </Select>
          <Search
            placeholder="搜索任务名称"
            allowClear
            style={{ width: 180 }}
            onSearch={v => { setKeyword(v); setPage(1); }}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchRecords}>刷新</Button>
        </Space>
      }>
        <Table
          columns={columns}
          dataSource={records}
          rowKey="id"
          loading={loading}
          size="small"
          pagination={{ current: page, total, pageSize: 20, onChange: setPage, showTotal: t => `共 ${t} 条` }}
          scroll={{ x: 1000 }}
        />
      </Card>

      <DetailDrawer recordId={detailId} open={!!detailId} onClose={() => setDetailId(null)} />
    </div>
  );
}
