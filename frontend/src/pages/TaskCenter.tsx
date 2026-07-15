/**
 * 任务管理（Manage / Task Center）
 *
 * 职责：Task 列表展示、查询/删除/下载脚本
 * 禁止：创建任务、执行任务
 *
 * 创建任务 → /requirement
 * 执行任务 → /task/:id（TaskDetail）
 */
import { useState, useCallback, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Card, Table, Button, Tag, Space, Popconfirm, message,
  Tabs, Statistic, Row, Col, Select, Spin,
} from 'antd';
import {
  PlusOutlined, ReloadOutlined, DeleteOutlined, DownloadOutlined,
  EyeOutlined, GlobalOutlined, PictureOutlined,
  UnorderedListOutlined, BarChartOutlined, CheckCircleOutlined,
  CloseCircleOutlined, ClockCircleOutlined, FileTextOutlined,
  CodeOutlined, DatabaseOutlined, ApartmentOutlined,
} from '@ant-design/icons';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip as RTooltip, Legend, ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import {
  getTaskList, deleteTask, downloadScript, Task,
} from '../services/task';
import request from '../services/request';
import { PageHeader } from '../components/UI';
import { TYPE_LABELS, TYPE_COLORS, TYPE_ICONS } from '../services/taskTypeDetector';

const statusMap: Record<string, { color: string; text: string }> = {
  pending: { color: 'default', text: '待处理' },
  processing: { color: 'processing', text: '处理中' },
  success: { color: 'success', text: '成功' },
  failed: { color: 'error', text: '失败' },
};

const modeMap: Record<string, { color: string; text: string }> = {
  image: { color: 'purple', text: '图片' },
  url: { color: 'green', text: 'URL' },
  requirement: { color: 'blue', text: '需求' },
};

interface DashboardStats {
  tasks: { total: number; completed: number; failed: number; pending: number; success_rate: number };
  executions: { total: number; success: number; failed: number; avg_duration: number };
  scripts: { total: number };
  knowledge_base: { total: number; elements: number; cases: number; scripts: number };
  graph: { total: number; relationships: number };
  feedback: { total: number; avg_score: number };
}

interface TrendItem {
  date: string;
  tasks: number;
  completed: number;
  failed: number;
  avg_duration: number;
}

function TaskListTab() {
  const navigate = useNavigate();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedRowKeys, setSelectedRowKeys] = useState<React.Key[]>([]);
  const [typeFilter, setTypeFilter] = useState<string>('all');

  const fetchTasks = async () => {
    setLoading(true);
    try {
      const res: any = await getTaskList();
      const taskData = res?.data || res;
      setTasks(taskData?.items || []);
      setTotal(taskData?.total || 0);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchTasks(); }, []);

  const filteredTasks = typeFilter === 'all'
    ? tasks
    : tasks.filter((t: any) => {
        if (typeFilter === 'hybrid') return t.task_type === 'hybrid';
        return t.task_type === typeFilter || (t.task_type === 'hybrid' && (t as any).test_scope?.[typeFilter]);
      });

  const handleDelete = async (id: number) => {
    try {
      await deleteTask(id);
      message.success('删除成功');
      setSelectedRowKeys(prev => prev.filter(k => k !== id));
      fetchTasks();
    } catch {
      message.error('删除失败');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedRowKeys.length === 0) { message.warning('请先选择要删除的任务'); return; }
    try {
      const res: any = await request.post('/tasks/batch_delete', { ids: selectedRowKeys });
      message.success(res?.message || '批量删除完成');
      setSelectedRowKeys([]);
      fetchTasks();
    } catch {
      message.error('批量删除失败');
    }
  };

  const columns = [
    { title: 'ID', dataIndex: 'id', key: 'id', width: 60, fixed: 'left' as const },
    { title: '任务名称', dataIndex: 'task_name', key: 'task_name', width: 180, ellipsis: true },
    {
      title: '输入模式', dataIndex: 'input_mode', key: 'input_mode', width: 90,
      render: (mode: string) => (
        <Tag color={modeMap[mode]?.color} icon={mode === 'image' ? <PictureOutlined /> : mode === 'url' ? <GlobalOutlined /> : undefined}>
          {modeMap[mode]?.text || mode}
        </Tag>
      ),
    },
    {
      title: '测试类型', dataIndex: 'task_type', key: 'task_type', width: 110,
      render: (t: string) => <Tag color={TYPE_COLORS[t] || 'default'}>{TYPE_ICONS[t] || ''} {TYPE_LABELS[t] || '未分类'}</Tag>,
    },
    {
      title: '状态', dataIndex: 'status', key: 'status', width: 90,
      render: (status: string) => <Tag color={statusMap[status]?.color}>{statusMap[status]?.text}</Tag>,
    },
    { title: '页面URL', dataIndex: 'page_url', key: 'page_url', width: 200, ellipsis: true, render: (url: string) => url || '-' },
    { title: '创建时间', dataIndex: 'created_at', key: 'created_at', width: 170 },
    {
      title: '操作', key: 'action', width: 200, fixed: 'right' as const,
      render: (_: unknown, record: Task) => (
        <Space size="small">
          <Button type="link" size="small" icon={<EyeOutlined />} onClick={() => navigate(`/task/${record.id}`)}>详情</Button>
          <Button type="link" size="small" icon={<DownloadOutlined />} disabled={!record.script} onClick={() => downloadScript(record.id)}>下载</Button>
          <Popconfirm title="确定删除此任务？" onConfirm={() => handleDelete(record.id)} okText="确定" cancelText="取消">
            <Button type="link" size="small" danger icon={<DeleteOutlined />} disabled={record.status === 'processing'}>删除</Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      extra={
        <Space>
          {selectedRowKeys.length > 0 && (
            <Popconfirm title={`确定删除选中的 ${selectedRowKeys.length} 个任务？`} onConfirm={handleBatchDelete} okText="确定" cancelText="取消">
              <Button danger icon={<DeleteOutlined />}>批量删除 ({selectedRowKeys.length})</Button>
            </Popconfirm>
          )}
          <Button icon={<ReloadOutlined />} onClick={fetchTasks}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => navigate('/requirement')}>创建任务</Button>
        </Space>
      }
    >
      <Space style={{ marginBottom: 12 }} wrap>
        <Tag.CheckableTag checked={typeFilter === 'all'} onChange={() => setTypeFilter('all')} style={{ padding: '4px 12px', borderRadius: 4 }}>
          全部
        </Tag.CheckableTag>
        {Object.entries(TYPE_LABELS).map(([key, label]) => (
          <Tag.CheckableTag key={key} checked={typeFilter === key} onChange={() => setTypeFilter(key)} style={{ padding: '4px 12px', borderRadius: 4 }}>
            {TYPE_ICONS[key]} {label}
          </Tag.CheckableTag>
        ))}
      </Space>
      <Table
        columns={columns}
        dataSource={filteredTasks}
        rowKey="id"
        loading={loading}
        pagination={{ total, pageSize: 20 }}
        scroll={{ x: 1000 }}
        rowSelection={{ selectedRowKeys, onChange: setSelectedRowKeys }}
      />
    </Card>
  );
}

function StatsTab() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [trend, setTrend] = useState<TrendItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [trendDays, setTrendDays] = useState(7);

  const fetchStats = useCallback(async () => {
    setLoading(true);
    try {
      const res: any = await request.get('/dashboard/stats');
      if (res.code === 200) setStats(res.data);
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  const fetchTrend = useCallback(async (days: number) => {
    try {
      const res: any = await request.get(`/dashboard/trend?days=${days}`);
      if (res.code === 200) setTrend(res.data);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { fetchStats(); fetchTrend(trendDays); }, [fetchStats, fetchTrend, trendDays]);

  return (
    <Spin spinning={loading}>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={4}><Card size="small"><Statistic title="任务总数" value={stats?.tasks.total ?? '-'} prefix={<FileTextOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="成功率" value={stats?.tasks.success_rate ?? 0} suffix="%" valueStyle={{ color: (stats?.tasks.success_rate ?? 0) >= 80 ? '#3f8600' : '#cf1322' }} prefix={<CheckCircleOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="脚本数" value={stats?.scripts.total ?? '-'} prefix={<CodeOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="知识库" value={stats?.knowledge_base.total ?? '-'} prefix={<DatabaseOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="图谱数量" value={stats?.graph.total ?? '-'} prefix={<ApartmentOutlined />} /></Card></Col>
        <Col span={4}><Card size="small"><Statistic title="平均耗时" value={stats?.executions.avg_duration ?? 0} suffix="秒" prefix={<ClockCircleOutlined />} /></Card></Col>
      </Row>
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={8}>
          <Card title="任务统计" size="small">
            <Row gutter={8}>
              <Col span={8}><Statistic title="完成" value={stats?.tasks.completed ?? 0} valueStyle={{ color: '#3f8600', fontSize: 20 }} prefix={<CheckCircleOutlined />} /></Col>
              <Col span={8}><Statistic title="失败" value={stats?.tasks.failed ?? 0} valueStyle={{ color: '#cf1322', fontSize: 20 }} prefix={<CloseCircleOutlined />} /></Col>
              <Col span={8}><Statistic title="进行中" value={stats?.tasks.pending ?? 0} valueStyle={{ color: '#1890ff', fontSize: 20 }} prefix={<ClockCircleOutlined />} /></Col>
            </Row>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="执行统计" size="small">
            <Row gutter={8}>
              <Col span={8}><Statistic title="总执行" value={stats?.executions.total ?? 0} valueStyle={{ fontSize: 20 }} /></Col>
              <Col span={8}><Statistic title="成功" value={stats?.executions.success ?? 0} valueStyle={{ color: '#3f8600', fontSize: 20 }} /></Col>
              <Col span={8}><Statistic title="失败" value={stats?.executions.failed ?? 0} valueStyle={{ color: '#cf1322', fontSize: 20 }} /></Col>
            </Row>
          </Card>
        </Col>
        <Col span={8}>
          <Card title="反馈统计" size="small">
            <Row gutter={8}>
              <Col span={12}><Statistic title="反馈数" value={stats?.feedback.total ?? 0} valueStyle={{ fontSize: 20 }} /></Col>
              <Col span={12}><Statistic title="平均评分" value={stats?.feedback.avg_score ?? 0} suffix="/5" valueStyle={{ fontSize: 20, color: '#722ed1' }} /></Col>
            </Row>
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={14}>
          <Card title="任务趋势" size="small" extra={<Select value={trendDays} onChange={(v) => { setTrendDays(v); fetchTrend(v); }} size="small" style={{ width: 100 }} options={[{ value: 7, label: '近7天' }, { value: 14, label: '近14天' }, { value: 30, label: '近30天' }]} />}>
            <ResponsiveContainer width="100%" height={280}>
              <LineChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} />
                <RTooltip /><Legend />
                <Line type="monotone" dataKey="tasks" stroke="#1890ff" name="任务数" strokeWidth={2} />
                <Line type="monotone" dataKey="completed" stroke="#52c41a" name="完成数" strokeWidth={2} />
                <Line type="monotone" dataKey="failed" stroke="#ff4d4f" name="失败数" strokeWidth={2} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </Col>
        <Col span={10}>
          <Card title="执行耗时趋势" size="small">
            <ResponsiveContainer width="100%" height={280}>
              <BarChart data={trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(v: string) => v.slice(5)} />
                <YAxis tick={{ fontSize: 11 }} />
                <RTooltip /><Legend />
                <Bar dataKey="avg_duration" fill="#722ed1" name="平均耗时(s)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </Col>
      </Row>
    </Spin>
  );
}

export default function TaskCenter() {
  return (
    <div>
      <PageHeader
        title="任务中心"
        icon={<UnorderedListOutlined />}
        subtitle="管理所有测试任务，点击详情进入任务详情页执行"
      />
      <Tabs
        defaultActiveKey="tasks"
        items={[
          { key: 'tasks', label: <span><UnorderedListOutlined /> 任务列表</span>, children: <TaskListTab /> },
          { key: 'stats', label: <span><BarChartOutlined /> 统计概览</span>, children: <StatsTab /> },
        ]}
      />
    </div>
  );
}
