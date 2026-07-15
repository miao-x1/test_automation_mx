/**
 * 执行中心（Execution First）
 *
 * 统一执行入口，整合所有执行类型：
 *   最近执行 / 接口执行 / Web执行 / 定时任务 / 报告
 *
 * 数据源：POST /execution/run/asset（统一入口）
 * 禁止：/api-test/execution/run / /assets/run
 */
import { useEffect, useState, useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Card, Tabs, Tag, Table, Button, Space, message, Modal, Input, Badge, Tooltip } from 'antd';
import {
  PlayCircleOutlined, ApiOutlined, GlobalOutlined,
  ClockCircleOutlined, FileTextOutlined, ReloadOutlined,
  CheckCircleOutlined, CloseCircleOutlined, SyncOutlined,
  StopOutlined, RedoOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';

/** 执行记录接口 */
interface ExecutionItem {
  id: number;
  execution_type?: string;
  asset_id?: number;
  suite_id?: number;
  session_id?: number;
  status: string;
  trigger_source?: string;
  duration?: number;
  success_count?: number;
  failed_count?: number;
  error_message?: string;
  report_path?: string;
  created_at?: string;
  task_name?: string;
}

const typeConfig: Record<string, { color: string; label: string; icon: React.ReactNode }> = {
  api: { color: 'blue', label: '接口', icon: <ApiOutlined /> },
  web: { color: 'green', label: 'Web', icon: <GlobalOutlined /> },
  android: { color: 'orange', label: 'Android', icon: <GlobalOutlined /> },
  suite: { color: 'purple', label: '套件', icon: <PlayCircleOutlined /> },
  batch: { color: 'cyan', label: '批量', icon: <PlayCircleOutlined /> },
};

const statusConfig: Record<string, { color: string; label: string; icon: React.ReactNode; badge: 'default' | 'processing' | 'success' | 'warning' | 'error' }> = {
  waiting: { color: 'default', label: '等待中', icon: <ClockCircleOutlined />, badge: 'default' },
  pending: { color: 'default', label: '待执行', icon: <ClockCircleOutlined />, badge: 'default' },
  running: { color: 'processing', label: '执行中', icon: <SyncOutlined spin />, badge: 'processing' },
  success: { color: 'success', label: '成功', icon: <CheckCircleOutlined />, badge: 'success' },
  failed: { color: 'error', label: '失败', icon: <CloseCircleOutlined />, badge: 'error' },
  cancelled: { color: 'warning', label: '已取消', icon: <StopOutlined />, badge: 'warning' },
};

/** 通用执行列表 */
function ExecutionList({ typeFilter }: { typeFilter?: string }) {
  const [items, setItems] = useState<ExecutionItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: '20',
      });
      if (typeFilter) params.set('execution_type', typeFilter);
      const res = await fetch(`/api/executions/list?${params}`, { credentials: 'include' });
      const data = await res.json();
      const d = data.data || data;
      setItems(d.items || []);
      setTotal(d.total || 0);
    } catch {
      message.error('加载执行列表失败');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [page, typeFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleCancel = async (id: number) => {
    try {
      const res = await fetch(`/api/execution/${id}/cancel`, {
        method: 'POST', credentials: 'include',
      });
      const data = await res.json();
      if (data.code === 200) {
        message.success('已取消');
        fetchData();
      } else {
        message.error(data.message || '取消失败');
      }
    } catch { message.error('取消失败'); }
  };

  const handleRetry = async (id: number) => {
    try {
      const res = await fetch(`/api/executions/${id}/retry`, {
        method: 'POST', credentials: 'include',
      });
      const data = await res.json();
      const d = data.data || data;
      if (d.execution_id) {
        message.success(`重试已提交 (ID: ${d.execution_id})`);
        fetchData();
      } else {
        message.error(data.message || '重试失败');
      }
    } catch { message.error('重试失败'); }
  };

  const handleDelete = async (id: number) => {
    Modal.confirm({
      title: '确认删除',
      icon: <ExclamationCircleOutlined />,
      content: `确定删除执行记录 #${id}？`,
      onOk: async () => {
        try {
          await fetch(`/api/executions/${id}`, { method: 'DELETE', credentials: 'include' });
          message.success('已删除');
          fetchData();
        } catch { message.error('删除失败'); }
      },
    });
  };

  const columns: ColumnsType<ExecutionItem> = [
    { title: 'ID', dataIndex: 'id', width: 60 },
    { title: '类型', dataIndex: 'execution_type', width: 80, render: (v: string) => {
      const cfg = typeConfig[v] || typeConfig.api;
      return <Tag color={cfg.color} icon={cfg.icon}>{cfg.label}</Tag>;
    }},
    { title: '状态', dataIndex: 'status', width: 100, render: (v: string) => {
      const cfg = statusConfig[v] || statusConfig.failed;
      return <Badge status={cfg.badge} text={<span style={{ color: cfg.color }}>{cfg.label}</span>} />;
    }},
    { title: '通过/失败', width: 100, render: (_: any, r: ExecutionItem) => (
      <Space size={4}>
        <Tag color="success">{r.success_count || 0}</Tag>
        <Tag color="error">{r.failed_count || 0}</Tag>
      </Space>
    )},
    { title: '耗时', dataIndex: 'duration', width: 80, render: (v: number) => v ? `${v.toFixed(1)}s` : '-' },
    { title: '触发', dataIndex: 'trigger_source', width: 70, render: (v: string) => <Tag>{v || 'manual'}</Tag> },
    { title: '创建时间', dataIndex: 'created_at', width: 160, render: (v: string) => v ? v.substring(0, 19) : '-' },
    { title: '操作', width: 160, render: (_: any, r: ExecutionItem) => (
      <Space size={4}>
        {(r.status === 'waiting' || r.status === 'pending' || r.status === 'running') && (
          <Tooltip title="取消">
            <Button size="small" type="link" icon={<StopOutlined />} onClick={() => handleCancel(r.id)} />
          </Tooltip>
        )}
        {(r.status === 'failed' || r.status === 'success') && (
          <Tooltip title="重试">
            <Button size="small" type="link" icon={<RedoOutlined />} onClick={() => handleRetry(r.id)} />
          </Tooltip>
        )}
        {r.report_path && (
          <Tooltip title="报告">
            <Button size="small" type="link" icon={<FileTextOutlined />} onClick={() => window.open(`/api/execution/${r.id}/report?format=html`, '_blank')} />
          </Tooltip>
        )}
        <Tooltip title="删除">
          <Button size="small" type="link" danger icon={<CloseCircleOutlined />} onClick={() => handleDelete(r.id)} />
        </Tooltip>
      </Space>
    )},
  ];

  return (
    <div>
      <Space style={{ marginBottom: 12 }}>
        <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
      </Space>
      <Table
        dataSource={items} columns={columns} rowKey="id" loading={loading}
        pagination={{ current: page, pageSize: 20, total, onChange: setPage, showTotal: t => `共 ${t} 条` }}
        size="small"
      />
    </div>
  );
}

/** 快速执行面板 */
function QuickExecute() {
  const [assetId, setAssetId] = useState<string>('');
  const [executing, setExecuting] = useState(false);

  const handleExecute = async () => {
    const id = parseInt(assetId);
    if (!id) { message.warning('请输入用例ID'); return; }
    setExecuting(true);
    try {
      const res = await fetch('/api/executions/run/asset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ asset_id: id, env: 'test', base_url: 'http://localhost:8080', async_exec: true }),
      });
      const data = await res.json();
      const d = data.data || data;
      if (d.execution_id) {
        message.success(`执行已提交 (ID: ${d.execution_id})`);
        setAssetId('');
      } else {
        message.error(d.detail || '执行失败');
      }
    } catch { message.error('执行请求失败'); }
    finally { setExecuting(false); }
  };

  return (
    <Card title="快速执行" size="small" style={{ marginBottom: 16 }}>
      <Space>
        <Input
          placeholder="输入用例ID" value={assetId}
          onChange={e => setAssetId(e.target.value)} style={{ width: 160 }}
          onPressEnter={handleExecute}
        />
        <Button type="primary" icon={<PlayCircleOutlined />} onClick={handleExecute} loading={executing}>
          执行
        </Button>
      </Space>
    </Card>
  );
}

/** 定时任务 - 跳转提示 */
function ScheduleTab() {
  const navigate = useNavigate();
  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <p>管理定时执行任务，查看执行历史。</p>
        <Space>
          <Button icon={<ClockCircleOutlined />} onClick={() => navigate('/web/schedule')}>定时任务管理</Button>
          <Button icon={<ClockCircleOutlined />} onClick={() => navigate('/web/schedule/history')}>执行历史</Button>
        </Space>
      </Space>
    </Card>
  );
}

/** 报告中心 */
function ReportsTab() {
  const navigate = useNavigate();
  return (
    <Card>
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <p>查看各模块测试报告。</p>
        <Space>
          <Button icon={<FileTextOutlined />} onClick={() => navigate('/api-test/report')}>接口测试报告</Button>
          <Button icon={<FileTextOutlined />} onClick={() => navigate('/web/reports')}>Web测试报告</Button>
        </Space>
      </Space>
    </Card>
  );
}

export default function ExecutionCenterPage() {
  const location = useLocation();
  const navigate = useNavigate();

  const getActiveKey = () => {
    if (location.pathname.includes('/api')) return 'api';
    if (location.pathname.includes('/web')) return 'web';
    if (location.pathname.includes('/schedule')) return 'schedule';
    if (location.pathname.includes('/reports')) return 'reports';
    return 'recent';
  };

  const tabItems = [
    {
      key: 'recent',
      label: <span><PlayCircleOutlined /> 最近执行</span>,
      children: (
        <div>
          <QuickExecute />
          <ExecutionList />
        </div>
      ),
    },
    {
      key: 'api',
      label: <span><ApiOutlined /> 接口执行</span>,
      children: <ExecutionList typeFilter="api" />,
    },
    {
      key: 'web',
      label: <span><GlobalOutlined /> Web执行</span>,
      children: <ExecutionList typeFilter="web" />,
    },
    {
      key: 'schedule',
      label: <span><ClockCircleOutlined /> 定时任务</span>,
      children: <ScheduleTab />,
    },
    {
      key: 'reports',
      label: <span><FileTextOutlined /> 报告</span>,
      children: <ReportsTab />,
    },
  ];

  return (
    <div>
      <Card size="small" bodyStyle={{ padding: '0 12px 12px' }}>
        <Tabs
          activeKey={getActiveKey()}
          onChange={(key) => {
            const routeMap: Record<string, string> = {
              recent: '/execution/recent',
              api: '/execution/api',
              web: '/execution/web',
              schedule: '/execution/schedule',
              reports: '/execution/reports',
            };
            navigate(routeMap[key] || '/execution/recent');
          }}
          items={tabItems}
        />
      </Card>
    </div>
  );
}
