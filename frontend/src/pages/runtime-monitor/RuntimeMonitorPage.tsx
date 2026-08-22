/**
 * 企业级 Agent Runtime 监控页面
 *
 * 功能模块:
 *   1. Runtime 概览 - 模式/队列/任务统计/Worker 状态
 *   2. 任务列表 - 查看/取消/重试任务
 *   3. 实时事件流 - SSE 订阅任务事件,实时显示
 *   4. Worker 池 - Worker 状态与统计
 *   5. 调度管理 - 查看/取消调度任务
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import {
  Card, Row, Col, Table, Tag, Button, Tabs, Statistic, Space, Typography,
  Drawer, Timeline, message, Badge, Descriptions, Empty, Input,
  Modal, Form, Select, Switch, Popconfirm, Progress, Divider,
} from 'antd';
import {
  ReloadOutlined, PlayCircleOutlined, StopOutlined,
  ThunderboltOutlined, CheckCircleOutlined, CloseCircleOutlined,
  ClockCircleOutlined, ExclamationCircleOutlined, CloudOutlined,
  ApiOutlined, DashboardOutlined, RobotOutlined, MonitorOutlined,
  FieldTimeOutlined, FireOutlined,
} from '@ant-design/icons';
import type { ColumnsType } from 'antd/es/table';
import {
  getRuntimeStats, getRuntimeHealth, listTasks,
  getTaskResult, cancelTask, retryTask, getWorkerStats,
  listSchedules, cancelSchedule, scheduleTask, submitTask,
  createSSEStream, queryHistory, getRuntimeMetrics,
  type RuntimeStats, type RuntimeHealth, type TaskState,
  type WorkerPoolStats, type ScheduledTask, type SSEEvent,
  type SubmitTaskRequest, type HistoryTask, type RuntimeMetrics,
} from '../../services/runtimeEnterprise';

const { Text, Title } = Typography;

// ============================================================
// 状态映射
// ============================================================

const STATUS_COLORS: Record<string, string> = {
  pending: 'default',
  running: 'processing',
  success: 'success',
  failed: 'error',
  timeout: 'warning',
  cancelled: 'default',
};

const STATUS_ICONS: Record<string, React.ReactNode> = {
  pending: <ClockCircleOutlined />,
  running: <PlayCircleOutlined spin />,
  success: <CheckCircleOutlined />,
  failed: <CloseCircleOutlined />,
  timeout: <ExclamationCircleOutlined />,
  cancelled: <StopOutlined />,
};

const STATUS_LABELS: Record<string, string> = {
  pending: '等待中',
  running: '执行中',
  success: '成功',
  failed: '失败',
  timeout: '超时',
  cancelled: '已取消',
};

const PRIORITY_COLORS: Record<string, string> = {
  low: 'default',
  normal: 'blue',
  high: 'orange',
  urgent: 'red',
};

const PRIORITY_LABELS: Record<string, string> = {
  low: '低',
  normal: '普通',
  high: '高',
  urgent: '紧急',
};

// ============================================================
// 主组件
// ============================================================

export default function RuntimeMonitorPage() {
  const [activeTab, setActiveTab] = useState('overview');
  const [stats, setStats] = useState<RuntimeStats | null>(null);
  const [health, setHealth] = useState<RuntimeHealth | null>(null);
  const [tasks, setTasks] = useState<TaskState[]>([]);
  const [workers, setWorkers] = useState<WorkerPoolStats | null>(null);
  const [schedules, setSchedules] = useState<ScheduledTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTask, setSelectedTask] = useState<TaskState | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [sseConnected, setSseConnected] = useState(false);
  const [subscribeTaskId, setSubscribeTaskId] = useState('');
  const closeSseRef = useRef<(() => void) | null>(null);
  const [submitModalOpen, setSubmitModalOpen] = useState(false);
  const [scheduleModalOpen, setScheduleModalOpen] = useState(false);
  const [submitForm] = Form.useForm();
  const [scheduleForm] = Form.useForm();
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const [historyTasks, setHistoryTasks] = useState<HistoryTask[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyHours, setHistoryHours] = useState(24);
  const [metrics, setMetrics] = useState<RuntimeMetrics | null>(null);

  // 加载所有数据
  const loadAll = useCallback(async () => {
    setLoading(true);
    try {
      const [statsResp, healthResp, tasksResp, workersResp, schedulesResp] = await Promise.all([
        getRuntimeStats().catch(() => null),
        getRuntimeHealth().catch(() => null),
        listTasks({ limit: 100 }).catch(() => []),
        getWorkerStats().catch(() => null),
        listSchedules().catch(() => []),
      ]);
      if (statsResp) setStats(statsResp);
      if (healthResp) setHealth(healthResp);
      setTasks(tasksResp as TaskState[]);
      if (workersResp) setWorkers(workersResp);
      setSchedules(schedulesResp as ScheduledTask[]);
    } catch (e) {
      message.error('加载数据失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAll();
    // 定时刷新 (10秒)
    const interval = setInterval(loadAll, 10000);
    return () => clearInterval(interval);
  }, [loadAll]);

  // 加载历史任务
  const loadHistory = useCallback(async (page = 1) => {
    try {
      const result = await queryHistory({
        hours: historyHours,
        limit: 20,
        offset: (page - 1) * 20,
      });
      setHistoryTasks(result.tasks);
      setHistoryTotal(result.total);
      setHistoryPage(page);
    } catch (e) {
      message.error('加载历史任务失败');
    }
  }, [historyHours]);

  // 加载指标
  const loadMetrics = useCallback(async () => {
    try {
      const data = await getRuntimeMetrics(historyHours);
      setMetrics(data);
    } catch (e) {
      message.error('加载指标失败');
    }
  }, [historyHours]);

  // Tab 切换时加载数据
  useEffect(() => {
    if (activeTab === 'history') {
      loadHistory(1);
    } else if (activeTab === 'metrics') {
      loadMetrics();
    }
  }, [activeTab, loadHistory, loadMetrics]);

  // SSE 订阅
  const handleSubscribe = useCallback(() => {
    if (!subscribeTaskId.trim()) {
      message.warning('请输入 Task ID');
      return;
    }
    // 关闭旧连接
    if (closeSseRef.current) {
      closeSseRef.current();
    }
    setEvents([]);
    setSseConnected(true);
    const close = createSSEStream(
      subscribeTaskId.trim(),
      (event) => {
        setEvents((prev) => [...prev, event]);
      },
      () => {
        setSseConnected(false);
        message.warning('SSE 连接断开');
      },
    );
    closeSseRef.current = close;
    message.success(`已订阅任务: ${subscribeTaskId}`);
  }, [subscribeTaskId]);

  const handleStopSubscribe = useCallback(() => {
    if (closeSseRef.current) {
      closeSseRef.current();
      closeSseRef.current = null;
    }
    setSseConnected(false);
  }, []);

  useEffect(() => {
    return () => {
      if (closeSseRef.current) closeSseRef.current();
    };
  }, []);

  // 任务操作
  const handleCancelTask = async (taskId: string) => {
    try {
      await cancelTask(taskId);
      message.success('任务已取消');
      loadAll();
    } catch {
      message.error('取消失败');
    }
  };

  const handleRetryTask = async (taskId: string) => {
    try {
      await retryTask(taskId);
      message.success('重试已启动');
      loadAll();
    } catch {
      message.error('重试失败');
    }
  };

  const handleViewTask = async (task: TaskState) => {
    setSelectedTask(task);
    setDrawerOpen(true);
    // 如果任务有结果,加载结果
    if (task.status === 'success' || task.status === 'failed') {
      try {
        const result = await getTaskResult(task.task_id);
        setSelectedTask({ ...task, result: result.result });
      } catch {
        // 忽略
      }
    }
  };

  // 提交任务
  const handleSubmitTask = async () => {
    try {
      const values = await submitForm.validateFields();
      await submitTask(values as SubmitTaskRequest);
      message.success('任务已提交');
      setSubmitModalOpen(false);
      submitForm.resetFields();
      loadAll();
    } catch {
      message.error('提交失败');
    }
  };

  // 调度任务
  const handleScheduleTask = async () => {
    try {
      const values = await scheduleForm.validateFields();
      await scheduleTask(values);
      message.success('调度已创建');
      setScheduleModalOpen(false);
      scheduleForm.resetFields();
      loadAll();
    } catch {
      message.error('调度失败');
    }
  };

  // 过滤任务
  const filteredTasks = statusFilter
    ? tasks.filter((t) => t.status === statusFilter)
    : tasks;

  // ============================================================
  // 任务表格列
  // ============================================================
  const taskColumns: ColumnsType<TaskState> = [
    {
      title: 'Task ID',
      dataIndex: 'task_id',
      key: 'task_id',
      width: 180,
      ellipsis: true,
      render: (text) => <Text code copyable={{ text }}>{text}</Text>,
    },
    {
      title: 'Agent',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 160,
      render: (text) => <Tag icon={<RobotOutlined />}>{text}</Tag>,
    },
    {
      title: 'Action',
      dataIndex: 'action',
      key: 'action',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Tag color={STATUS_COLORS[status]} icon={STATUS_ICONS[status]}>
          {STATUS_LABELS[status] || status}
        </Tag>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (priority) => (
        <Tag color={PRIORITY_COLORS[priority]}>{PRIORITY_LABELS[priority] || priority}</Tag>
      ),
    },
    {
      title: '重试',
      key: 'retry',
      width: 70,
      render: (_, record) => (
        <Text>{record.retry_count}/{record.max_retries}</Text>
      ),
    },
    {
      title: 'Worker',
      dataIndex: 'worker_id',
      key: 'worker_id',
      width: 110,
      render: (text) => text ? <Text code>{text}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (text) => text ? new Date(text).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 200,
      render: (_, record) => (
        <Space size="small">
          <Button
            type="link"
            size="small"
            onClick={() => handleViewTask(record)}
          >
            详情
          </Button>
          <Button
            type="link"
            size="small"
            onClick={() => {
              setSubscribeTaskId(record.task_id);
              setActiveTab('events');
            }}
          >
            订阅
          </Button>
          {(record.status === 'pending' || record.status === 'running') && (
            <Popconfirm
              title="确定取消此任务?"
              onConfirm={() => handleCancelTask(record.task_id)}
            >
              <Button type="link" size="small" danger>取消</Button>
            </Popconfirm>
          )}
          {(record.status === 'failed' || record.status === 'timeout') && (
            <Button
              type="link"
              size="small"
              onClick={() => handleRetryTask(record.task_id)}
            >
              重试
            </Button>
          )}
        </Space>
      ),
    },
  ];

  // ============================================================
  // Worker 表格列
  // ============================================================
  const workerColumns: ColumnsType<any> = [
    {
      title: 'Worker ID',
      dataIndex: 'worker_id',
      key: 'worker_id',
      render: (text) => <Text code>{text}</Text>,
    },
    {
      title: '状态',
      dataIndex: 'is_busy',
      key: 'is_busy',
      render: (busy) => busy ? (
        <Badge status="processing" text="忙碌" />
      ) : (
        <Badge status="success" text="空闲" />
      ),
    },
    {
      title: '当前任务',
      dataIndex: 'current_task',
      key: 'current_task',
      render: (text) => text ? <Text code>{text}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '已完成',
      dataIndex: 'tasks_done',
      key: 'tasks_done',
      render: (n) => <Statistic value={n} valueStyle={{ fontSize: 16 }} />,
    },
    {
      title: '失败数',
      dataIndex: 'tasks_failed',
      key: 'tasks_failed',
      render: (n) => n > 0 ? <Text type="danger">{n}</Text> : <Text>0</Text>,
    },
    {
      title: '平均耗时',
      dataIndex: 'avg_duration_ms',
      key: 'avg_duration_ms',
      render: (ms) => <Text>{ms.toFixed(0)}ms</Text>,
    },
  ];

  // ============================================================
  // 调度表格列
  // ============================================================
  const scheduleColumns: ColumnsType<ScheduledTask> = [
    {
      title: '调度 ID',
      dataIndex: 'schedule_id',
      key: 'schedule_id',
      render: (text) => <Text code>{text}</Text>,
    },
    {
      title: 'Agent',
      dataIndex: 'agent_name',
      key: 'agent_name',
      render: (text) => <Tag icon={<RobotOutlined />}>{text}</Tag>,
    },
    {
      title: '类型',
      dataIndex: 'schedule_type',
      key: 'schedule_type',
      render: (type) => {
        const colors: Record<string, string> = {
          immediate: 'blue',
          delayed: 'orange',
          scheduled: 'purple',
          dependent: 'cyan',
        };
        const labels: Record<string, string> = {
          immediate: '立即',
          delayed: '延迟',
          scheduled: '定时',
          dependent: '依赖',
        };
        return <Tag color={colors[type]}>{labels[type] || type}</Tag>;
      },
    },
    {
      title: '执行次数',
      dataIndex: 'run_count',
      key: 'run_count',
      render: (n, record) => (
        <Text>{n}{record.max_runs ? `/${record.max_runs}` : '/∞'}</Text>
      ),
    },
    {
      title: '下次执行',
      dataIndex: 'next_run_at',
      key: 'next_run_at',
      render: (ts) => ts ? new Date(ts * 1000).toLocaleString() : '-',
    },
    {
      title: '状态',
      dataIndex: 'enabled',
      key: 'enabled',
      render: (enabled) => enabled ? (
        <Badge status="success" text="启用" />
      ) : (
        <Badge status="default" text="禁用" />
      ),
    },
    {
      title: '操作',
      key: 'action',
      render: (_, record) => (
        <Popconfirm
          title="确定取消此调度?"
          onConfirm={async () => {
            await cancelSchedule(record.schedule_id);
            message.success('已取消');
            loadAll();
          }}
        >
          <Button type="link" size="small" danger>取消</Button>
        </Popconfirm>
      ),
    },
  ];

  // ============================================================
  // 历史任务表格列
  // ============================================================
  const historyColumns: ColumnsType<HistoryTask> = [
    {
      title: 'Task ID',
      dataIndex: 'task_id',
      key: 'task_id',
      width: 180,
      ellipsis: true,
      render: (text) => <Text code copyable={{ text }}>{text}</Text>,
    },
    {
      title: 'Agent',
      dataIndex: 'agent_name',
      key: 'agent_name',
      width: 140,
      render: (text) => <Tag icon={<RobotOutlined />}>{text}</Tag>,
    },
    {
      title: 'Action',
      dataIndex: 'action',
      key: 'action',
      width: 100,
    },
    {
      title: '状态',
      dataIndex: 'status',
      key: 'status',
      width: 100,
      render: (status) => (
        <Tag color={STATUS_COLORS[status]} icon={STATUS_ICONS[status]}>
          {STATUS_LABELS[status] || status}
        </Tag>
      ),
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      key: 'priority',
      width: 80,
      render: (priority) => (
        <Tag color={PRIORITY_COLORS[priority]}>{PRIORITY_LABELS[priority] || priority}</Tag>
      ),
    },
    {
      title: 'Worker',
      dataIndex: 'worker_id',
      key: 'worker_id',
      width: 110,
      render: (text) => text ? <Text code>{text}</Text> : <Text type="secondary">-</Text>,
    },
    {
      title: '耗时',
      dataIndex: 'duration_ms',
      key: 'duration_ms',
      width: 100,
      sorter: (a, b) => (a.duration_ms || 0) - (b.duration_ms || 0),
      render: (ms) => {
        if (ms == null) return <Text type="secondary">-</Text>;
        if (ms < 1000) return <Text>{ms.toFixed(0)}ms</Text>;
        return <Text>{(ms / 1000).toFixed(2)}s</Text>;
      },
    },
    {
      title: '重试',
      key: 'retry',
      width: 70,
      render: (_, record) => (
        <Text>{record.retry_count}/{record.max_retries}</Text>
      ),
    },
    {
      title: '创建时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 170,
      sorter: (a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return ta - tb;
      },
      render: (text) => text ? new Date(text).toLocaleString() : '-',
    },
    {
      title: '完成时间',
      dataIndex: 'completed_at',
      key: 'completed_at',
      width: 170,
      render: (text) => text ? new Date(text).toLocaleString() : '-',
    },
    {
      title: '操作',
      key: 'action',
      width: 100,
      render: (_, record) => (
        <Button
          type="link"
          size="small"
          onClick={() => {
            setSubscribeTaskId(record.task_id);
            message.info(`已选中任务 ${record.task_id}`);
          }}
        >
          选中
        </Button>
      ),
    },
  ];

  // ============================================================
  // 渲染
  // ============================================================
  return (
    <div style={{ padding: 24 }}>
      <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between' }}>
        <Title level={3} style={{ margin: 0 }}>
          <MonitorOutlined /> 企业级 Agent Runtime
        </Title>
        <Space>
          <Button icon={<ReloadOutlined />} onClick={loadAll} loading={loading}>
            刷新
          </Button>
          <Button
            type="primary"
            icon={<ThunderboltOutlined />}
            onClick={() => setSubmitModalOpen(true)}
          >
            提交任务
          </Button>
          <Button
            icon={<FieldTimeOutlined />}
            onClick={() => setScheduleModalOpen(true)}
          >
            调度任务
          </Button>
        </Space>
      </div>

      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'overview',
            label: <span><DashboardOutlined /> 概览</span>,
            children: (
              <RuntimeOverview stats={stats} health={health} workers={workers} />
            ),
          },
          {
            key: 'tasks',
            label: <span><ApiOutlined /> 任务列表 ({tasks.length})</span>,
            children: (
              <Card>
                <div style={{ marginBottom: 16 }}>
                  <Space>
                    <Select
                      placeholder="按状态过滤"
                      allowClear
                      style={{ width: 150 }}
                      value={statusFilter}
                      onChange={setStatusFilter}
                      options={Object.entries(STATUS_LABELS).map(([k, v]) => ({
                        value: k, label: v,
                      }))}
                    />
                    <Button icon={<ReloadOutlined />} onClick={loadAll}>
                      刷新
                    </Button>
                  </Space>
                </div>
                <Table
                  columns={taskColumns}
                  dataSource={filteredTasks}
                  rowKey="task_id"
                  size="small"
                  pagination={{ pageSize: 20, showSizeChanger: true }}
                  loading={loading}
                  scroll={{ x: 1200 }}
                />
              </Card>
            ),
          },
          {
            key: 'workers',
            label: <span><RobotOutlined /> Worker 池</span>,
            children: (
              <Card>
                {workers ? (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={6}>
                        <Card size="small">
                          <Statistic title="Worker 数量" value={workers.size} prefix={<RobotOutlined />} />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small">
                          <Statistic
                            title="忙碌"
                            value={workers.busy_workers}
                            valueStyle={{ color: '#1677ff' }}
                            prefix={<FireOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small">
                          <Statistic
                            title="空闲"
                            value={workers.idle_workers}
                            valueStyle={{ color: '#52c41a' }}
                            prefix={<CheckCircleOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={6}>
                        <Card size="small">
                          <Statistic
                            title="运行中任务"
                            value={workers.running_tasks}
                            prefix={<PlayCircleOutlined />}
                          />
                        </Card>
                      </Col>
                    </Row>
                    <Table
                      columns={workerColumns}
                      dataSource={workers.workers}
                      rowKey="worker_id"
                      size="small"
                      pagination={false}
                    />
                  </>
                ) : (
                  <Empty description="无 Worker 数据" />
                )}
              </Card>
            ),
          },
          {
            key: 'events',
            label: <span><CloudOutlined /> 实时事件流</span>,
            children: (
              <Card>
                <div style={{ marginBottom: 16 }}>
                  <Space>
                    <Input
                      placeholder="输入 Task ID 订阅事件"
                      style={{ width: 300 }}
                      value={subscribeTaskId}
                      onChange={(e) => setSubscribeTaskId(e.target.value)}
                      onPressEnter={handleSubscribe}
                    />
                    {sseConnected ? (
                      <Button
                        danger
                        icon={<StopOutlined />}
                        onClick={handleStopSubscribe}
                      >
                        停止订阅
                      </Button>
                    ) : (
                      <Button
                        type="primary"
                        icon={<PlayCircleOutlined />}
                        onClick={handleSubscribe}
                      >
                        订阅
                      </Button>
                    )}
                    <Badge
                      status={sseConnected ? 'processing' : 'default'}
                      text={sseConnected ? '已连接' : '未连接'}
                    />
                  </Space>
                </div>
                <Divider />
                {events.length === 0 ? (
                  <Empty description="暂无事件,输入 Task ID 后点击订阅" />
                ) : (
                  <div style={{ maxHeight: 500, overflowY: 'auto' }}>
                    <Timeline
                      items={events.map((event, idx) => ({
                        key: idx,
                        color: event.event === 'error' ? 'red'
                          : event.event === 'done' ? 'green'
                          : event.event === 'ping' ? 'gray'
                          : 'blue',
                        children: (
                          <div>
                            <Tag color={
                              event.event === 'error' ? 'red' :
                              event.event === 'done' ? 'green' :
                              event.event === 'ping' ? 'default' : 'blue'
                            }>
                              {event.event}
                            </Tag>
                            <Text type="secondary" style={{ fontSize: 12 }}>
                              {event.timestamp
                                ? new Date(event.timestamp * 1000).toLocaleTimeString()
                                : ''}
                            </Text>
                            <pre style={{
                              fontSize: 12, marginTop: 4, maxHeight: 100,
                              overflow: 'auto', background: '#f5f5f5', padding: 8,
                              borderRadius: 4,
                            }}>
                              {JSON.stringify(event, null, 2)}
                            </pre>
                          </div>
                        ),
                      }))}
                    />
                  </div>
                )}
              </Card>
            ),
          },
          {
            key: 'schedules',
            label: <span><FieldTimeOutlined /> 调度管理 ({schedules.length})</span>,
            children: (
              <Card>
                <Table
                  columns={scheduleColumns}
                  dataSource={schedules}
                  rowKey="schedule_id"
                  size="small"
                  pagination={{ pageSize: 20 }}
                  loading={loading}
                />
              </Card>
            ),
          },
          {
            key: 'history',
            label: <span><FireOutlined /> 历史任务 ({historyTotal})</span>,
            children: (
              <Card>
                <div style={{ marginBottom: 16, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Space>
                    <Text>最近</Text>
                    <Select
                      value={historyHours}
                      onChange={(v) => {
                        setHistoryHours(v);
                        setTimeout(() => loadHistory(1), 0);
                      }}
                      style={{ width: 100 }}
                      options={[
                        { value: 1, label: '1 小时' },
                        { value: 6, label: '6 小时' },
                        { value: 24, label: '24 小时' },
                        { value: 72, label: '3 天' },
                        { value: 168, label: '7 天' },
                      ]}
                    />
                  </Space>
                  <Button icon={<ReloadOutlined />} onClick={() => loadHistory(historyPage)}>
                    刷新
                  </Button>
                </div>
                <Table
                  columns={historyColumns}
                  dataSource={historyTasks}
                  rowKey="task_id"
                  size="small"
                  scroll={{ x: 1200 }}
                  pagination={{
                    current: historyPage,
                    total: historyTotal,
                    pageSize: 20,
                    showSizeChanger: false,
                    showTotal: (total) => `共 ${total} 条`,
                    onChange: (page) => loadHistory(page),
                  }}
                />
              </Card>
            ),
          },
          {
            key: 'metrics',
            label: <span><DashboardOutlined /> 指标统计</span>,
            children: (
              <div>
                {metrics ? (
                  <>
                    <Row gutter={16} style={{ marginBottom: 16 }}>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="总任务数"
                            value={metrics.total}
                            prefix={<ApiOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="成功率"
                            value={metrics.success_rate}
                            precision={1}
                            suffix="%"
                            valueStyle={{
                              color: metrics.success_rate >= 80 ? '#3f8600' : metrics.success_rate >= 50 ? '#faad14' : '#cf1322',
                            }}
                            prefix={<CheckCircleOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="平均耗时"
                            value={metrics.avg_duration_ms ? (metrics.avg_duration_ms / 1000).toFixed(2) : 0}
                            suffix="s"
                            prefix={<ClockCircleOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="P50 耗时"
                            value={metrics.p50_duration_ms ? (metrics.p50_duration_ms / 1000).toFixed(2) : 0}
                            suffix="s"
                            prefix={<ClockCircleOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="P95 耗时"
                            value={metrics.p95_duration_ms ? (metrics.p95_duration_ms / 1000).toFixed(2) : 0}
                            suffix="s"
                            valueStyle={{ color: metrics.p95_duration_ms > 10000 ? '#cf1322' : '#3f8600' }}
                            prefix={<ExclamationCircleOutlined />}
                          />
                        </Card>
                      </Col>
                      <Col span={4}>
                        <Card size="small">
                          <Statistic
                            title="吞吐量"
                            value={metrics.throughput ? metrics.throughput.toFixed(2) : 0}
                            suffix="/min"
                            prefix={<ThunderboltOutlined />}
                          />
                        </Card>
                      </Col>
                    </Row>

                    <Row gutter={16}>
                      <Col span={12}>
                        <Card title="按状态分布" size="small" style={{ marginBottom: 16 }}>
                          {metrics.by_status && Object.keys(metrics.by_status).length > 0 ? (
                            <Row gutter={[8, 8]}>
                              {Object.entries(metrics.by_status).map(([status, count]) => (
                                <Col span={8} key={status}>
                                  <Statistic
                                    title={
                                      <Tag color={STATUS_COLORS[status]} icon={STATUS_ICONS[status]}>
                                        {STATUS_LABELS[status] || status}
                                      </Tag>
                                    }
                                    value={count}
                                    valueStyle={{ fontSize: 20 }}
                                  />
                                </Col>
                              ))}
                            </Row>
                          ) : (
                            <Empty description="暂无数据" />
                          )}
                        </Card>
                      </Col>
                      <Col span={12}>
                        <Card title="按 Agent 分布" size="small" style={{ marginBottom: 16 }}>
                          {metrics.by_agent && Object.keys(metrics.by_agent).length > 0 ? (
                            <Table
                              size="small"
                              pagination={false}
                              dataSource={Object.entries(metrics.by_agent).map(([name, info]) => ({
                                key: name,
                                agent_name: name,
                                ...info,
                              }))}
                              columns={[
                                {
                                  title: 'Agent',
                                  dataIndex: 'agent_name',
                                  key: 'agent_name',
                                  render: (text) => <Tag icon={<RobotOutlined />}>{text}</Tag>,
                                },
                                {
                                  title: '总数',
                                  dataIndex: 'total',
                                  key: 'total',
                                  width: 70,
                                },
                                {
                                  title: '成功',
                                  dataIndex: 'success',
                                  key: 'success',
                                  width: 70,
                                  render: (n) => <Text type="success">{n || 0}</Text>,
                                },
                                {
                                  title: '失败',
                                  dataIndex: 'failed',
                                  key: 'failed',
                                  width: 70,
                                  render: (n) => (n > 0 ? <Text type="danger">{n}</Text> : <Text>0</Text>),
                                },
                                {
                                  title: '平均耗时',
                                  dataIndex: 'avg_duration_ms',
                                  key: 'avg_duration_ms',
                                  width: 100,
                                  render: (ms) => ms ? `${(ms / 1000).toFixed(2)}s` : '-',
                                },
                              ]}
                            />
                          ) : (
                            <Empty description="暂无数据" />
                          )}
                        </Card>
                      </Col>
                    </Row>

                    <Card title="小时趋势" size="small">
                      {metrics.hourly && metrics.hourly.length > 0 ? (
                        <Table
                          size="small"
                          pagination={false}
                          dataSource={metrics.hourly.map((h, i) => ({ ...h, key: i }))}
                          columns={[
                            {
                              title: '时段',
                              dataIndex: 'hour',
                              key: 'hour',
                              render: (hour) => <Text code>{hour}</Text>,
                            },
                            {
                              title: '任务数',
                              dataIndex: 'total',
                              key: 'total',
                              width: 100,
                              render: (n) => <Statistic value={n} valueStyle={{ fontSize: 14 }} />,
                            },
                            {
                              title: '成功',
                              dataIndex: 'success',
                              key: 'success',
                              width: 80,
                              render: (n) => <Text type="success">{n || 0}</Text>,
                            },
                            {
                              title: '失败',
                              dataIndex: 'failed',
                              key: 'failed',
                              width: 80,
                              render: (n) => (n > 0 ? <Text type="danger">{n}</Text> : <Text>0</Text>),
                            },
                            {
                              title: '占比',
                              key: 'ratio',
                              width: 200,
                              render: (_, record) => {
                                const ratio = metrics.total > 0 ? (record.total / metrics.total) * 100 : 0;
                                return <Progress percent={ratio} size="small" />;
                              },
                            },
                          ]}
                        />
                      ) : (
                        <Empty description="暂无趋势数据" />
                      )}
                    </Card>

                    <div style={{ marginTop: 16, textAlign: 'right' }}>
                      <Text type="secondary" style={{ fontSize: 12 }}>
                        统计周期: 最近 {historyHours} 小时
                      </Text>
                    </div>
                  </>
                ) : (
                  <Card>
                    <Empty description="暂无指标数据,请先执行任务" />
                  </Card>
                )}
              </div>
            ),
          },
        ]}
      />

      {/* 任务详情 Drawer */}
      <Drawer
        title={selectedTask ? `任务详情: ${selectedTask.task_id}` : ''}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={640}
      >
        {selectedTask && (
          <Descriptions column={1} bordered size="small">
            <Descriptions.Item label="Task ID">
              <Text code copyable>{selectedTask.task_id}</Text>
            </Descriptions.Item>
            <Descriptions.Item label="Agent">
              <Tag icon={<RobotOutlined />}>{selectedTask.agent_name}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="Action">
              {selectedTask.action}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag color={STATUS_COLORS[selectedTask.status]} icon={STATUS_ICONS[selectedTask.status]}>
                {STATUS_LABELS[selectedTask.status]}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="优先级">
              <Tag color={PRIORITY_COLORS[selectedTask.priority]}>
                {PRIORITY_LABELS[selectedTask.priority]}
              </Tag>
            </Descriptions.Item>
            <Descriptions.Item label="重试">
              {selectedTask.retry_count} / {selectedTask.max_retries}
            </Descriptions.Item>
            <Descriptions.Item label="Worker">
              {selectedTask.worker_id ? <Text code>{selectedTask.worker_id}</Text> : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="创建时间">
              {selectedTask.created_at ? new Date(selectedTask.created_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="开始时间">
              {selectedTask.started_at ? new Date(selectedTask.started_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="完成时间">
              {selectedTask.completed_at ? new Date(selectedTask.completed_at).toLocaleString() : '-'}
            </Descriptions.Item>
            <Descriptions.Item label="超时(秒)">
              {selectedTask.timeout_seconds}
            </Descriptions.Item>
            {selectedTask.error && (
              <Descriptions.Item label="错误">
                <Text type="danger" style={{ whiteSpace: 'pre-wrap' }}>
                  {selectedTask.error}
                </Text>
              </Descriptions.Item>
            )}
            {selectedTask.result && (
              <Descriptions.Item label="结果">
                <pre style={{
                  fontSize: 12, maxHeight: 300, overflow: 'auto',
                  background: '#f5f5f5', padding: 8, borderRadius: 4,
                }}>
                  {typeof selectedTask.result === 'string'
                    ? selectedTask.result
                    : JSON.stringify(selectedTask.result, null, 2)}
                </pre>
              </Descriptions.Item>
            )}
          </Descriptions>
        )}
      </Drawer>

      {/* 提交任务 Modal */}
      <Modal
        title="提交任务"
        open={submitModalOpen}
        onOk={handleSubmitTask}
        onCancel={() => setSubmitModalOpen(false)}
        width={560}
      >
        <Form form={submitForm} layout="vertical">
          <Form.Item
            name="agent_name"
            label="Agent 名称"
            rules={[{ required: true, message: '请输入 Agent 名称' }]}
          >
            <Input placeholder="例如: api_debug_agent" />
          </Form.Item>
          <Form.Item name="action" label="Action" initialValue="execute">
            <Input placeholder="execute" />
          </Form.Item>
          <Form.Item name="payload" label="Payload (JSON)">
            <Input.TextArea
              rows={4}
              placeholder='{"key": "value"}'
            />
          </Form.Item>
          <Row gutter={16}>
            <Col span={8}>
              <Form.Item name="priority" label="优先级" initialValue="normal">
                <Select options={[
                  { value: 'low', label: '低' },
                  { value: 'normal', label: '普通' },
                  { value: 'high', label: '高' },
                  { value: 'urgent', label: '紧急' },
                ]} />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="timeout_seconds" label="超时(秒)" initialValue={300}>
                <Input type="number" />
              </Form.Item>
            </Col>
            <Col span={8}>
              <Form.Item name="max_retries" label="重试次数" initialValue={3}>
                <Input type="number" />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item name="wait" label="同步等待" valuePropName="checked">
            <Switch />
          </Form.Item>
        </Form>
      </Modal>

      {/* 调度任务 Modal */}
      <Modal
        title="调度任务"
        open={scheduleModalOpen}
        onOk={handleScheduleTask}
        onCancel={() => setScheduleModalOpen(false)}
        width={560}
      >
        <Form form={scheduleForm} layout="vertical">
          <Form.Item
            name="agent_name"
            label="Agent 名称"
            rules={[{ required: true, message: '请输入 Agent 名称' }]}
          >
            <Input placeholder="例如: api_debug_agent" />
          </Form.Item>
          <Form.Item name="action" label="Action" initialValue="execute">
            <Input />
          </Form.Item>
          <Form.Item name="payload" label="Payload (JSON)">
            <Input.TextArea rows={3} placeholder='{"key": "value"}' />
          </Form.Item>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item name="delay_seconds" label="延迟秒数 (0=立即)">
                <Input type="number" defaultValue={0} />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item name="cron_expression" label="Cron 表达式 (可选)">
                <Input placeholder="*/5 * * * *" />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>
    </div>
  );
}

// ============================================================
// Runtime 概览组件
// ============================================================

function RuntimeOverview({
  stats, health, workers,
}: {
  stats: RuntimeStats | null;
  health: RuntimeHealth | null;
  workers: WorkerPoolStats | null;
}) {
  if (!stats) {
    return <Empty description="加载中..." />;
  }

  const dispatcher = stats.dispatcher;
  const statusCounts = dispatcher.status_counts || {};
  const totalTasks = dispatcher.total_tasks || 0;
  const successRate = totalTasks > 0
    ? ((statusCounts.success || 0) / totalTasks * 100)
    : 0;

  return (
    <div>
      {/* 健康状态 */}
      <Card style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={6}>
            <Statistic
              title="运行状态"
              value={health?.status === 'healthy' ? '健康' : '异常'}
              valueStyle={{
                color: health?.status === 'healthy' ? '#52c41a' : '#ff4d4f',
              }}
              prefix={health?.status === 'healthy'
                ? <CheckCircleOutlined />
                : <CloseCircleOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="运行模式"
              value={dispatcher.mode === 'standalone' ? '单机' : '分布式'}
              prefix={<CloudOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="队列大小"
              value={dispatcher.queue_size}
              prefix={<ClockCircleOutlined />}
            />
          </Col>
          <Col span={6}>
            <Statistic
              title="启动状态"
              value={dispatcher.started ? '运行中' : '已停止'}
              valueStyle={{
                color: dispatcher.started ? '#52c41a' : '#bfbfbf',
              }}
            />
          </Col>
        </Row>
      </Card>

      {/* 任务统计 */}
      <Card title="任务统计" style={{ marginBottom: 16 }}>
        <Row gutter={16}>
          <Col span={4}>
            <Statistic title="总任务" value={totalTasks} />
          </Col>
          <Col span={4}>
            <Statistic
              title="成功"
              value={statusCounts.success || 0}
              valueStyle={{ color: '#52c41a' }}
              prefix={<CheckCircleOutlined />}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="失败"
              value={statusCounts.failed || 0}
              valueStyle={{ color: '#ff4d4f' }}
              prefix={<CloseCircleOutlined />}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="执行中"
              value={statusCounts.running || 0}
              valueStyle={{ color: '#1677ff' }}
              prefix={<PlayCircleOutlined />}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="等待中"
              value={statusCounts.pending || 0}
              prefix={<ClockCircleOutlined />}
            />
          </Col>
          <Col span={4}>
            <Statistic
              title="成功率"
              value={successRate.toFixed(1)}
              suffix="%"
              valueStyle={{ color: successRate > 80 ? '#52c41a' : '#faad14' }}
            />
          </Col>
        </Row>
      </Card>

      {/* Worker 池 */}
      {workers && (
        <Card title="Worker 池" style={{ marginBottom: 16 }}>
          <Row gutter={16}>
            <Col span={6}>
              <Statistic title="Worker 数量" value={workers.size} prefix={<RobotOutlined />} />
            </Col>
            <Col span={6}>
              <Statistic
                title="忙碌"
                value={workers.busy_workers}
                valueStyle={{ color: '#1677ff' }}
              />
            </Col>
            <Col span={6}>
              <Statistic
                title="空闲"
                value={workers.idle_workers}
                valueStyle={{ color: '#52c41a' }}
              />
            </Col>
            <Col span={6}>
              <Statistic title="运行中任务" value={workers.running_tasks} />
            </Col>
          </Row>
          <div style={{ marginTop: 16 }}>
            <Progress
              percent={workers.size > 0 ? (workers.busy_workers / workers.size * 100) : 0}
              status={workers.busy_workers === workers.size ? 'exception' : 'active'}
              format={() => `${workers.busy_workers}/${workers.size} 忙碌`}
            />
          </div>
        </Card>
      )}

      {/* 流与调度 */}
      <Row gutter={16}>
        <Col span={12}>
          <Card title="事件流统计">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="已发布事件"
                  value={stats.stream_publisher.events_published}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="SSE 客户端"
                  value={stats.stream_publisher.sse_clients_total}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="WS 客户端"
                  value={stats.stream_publisher.ws_clients_total}
                />
              </Col>
            </Row>
          </Card>
        </Col>
        <Col span={12}>
          <Card title="调度统计">
            <Row gutter={16}>
              <Col span={8}>
                <Statistic
                  title="总调度"
                  value={stats.scheduler.total_schedules}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="启用中"
                  value={stats.scheduler.enabled_schedules}
                  valueStyle={{ color: '#52c41a' }}
                />
              </Col>
              <Col span={8}>
                <Statistic
                  title="活跃任务"
                  value={stats.collector.active_tasks}
                />
              </Col>
            </Row>
          </Card>
        </Col>
      </Row>
    </div>
  );
}
