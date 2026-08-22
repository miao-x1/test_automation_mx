/**
 * 性能测试 - 任务列表页
 *
 * 路由: /performance
 *
 * 功能:
 *   1. 顶部筛选条(测试类型 / 状态)
 *   2. 任务列表表格(任务名称 / 测试类型 / 目标URL / 并发数 / 状态 / 创建时间 / 操作)
 *   3. "新建任务" 按钮打开创建弹窗
 *   4. 操作: 方案 / 脚本 / 分析 / 详情 / 删除
 */
import { useState, useEffect, useCallback } from 'react';
import {
  Card,
  Table,
  Button,
  Modal,
  Form,
  Input,
  Select,
  InputNumber,
  Tag,
  Space,
  message,
  Typography,
  Popconfirm,
  Tooltip,
} from 'antd';
import {
  PlusOutlined,
  ReloadOutlined,
  EyeOutlined,
  DeleteOutlined,
  ThunderboltOutlined,
  CodeOutlined,
  BarChartOutlined,
  PlayCircleOutlined,
  StopOutlined,
} from '@ant-design/icons';
import { useNavigate } from 'react-router-dom';
import {
  listTasks,
  createTask,
  deleteTask,
  runPlan,
  runScript,
  runAnalysis,
  executeTask,
  stopExecute,
  type PerformanceTask,
} from '@/services/performance';

const { Title } = Typography;

// 测试类型中文名 / 颜色
const TEST_TYPE_META: Record<string, { color: string; text: string }> = {
  api: { color: 'blue', text: 'API 测试' },
  web: { color: 'cyan', text: 'Web 测试' },
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

// 兼容后端返回结构: {items, total} | {data, total} | {code, data:{items,total}} | 数组
function normalizeList(res: any): { list: PerformanceTask[]; total: number } {
  if (Array.isArray(res)) {
    return { list: res, total: res.length };
  }
  // 解包 {code, message, data: ...} 信封格式
  const payload = res?.data ?? res;
  if (Array.isArray(payload)) {
    return { list: payload, total: payload.length };
  }
  const list = payload?.items || payload?.list || [];
  const total = payload?.total ?? (Array.isArray(list) ? list.length : 0);
  return { list: list || [], total: total || 0 };
}

export default function PerformanceListPage() {
  const navigate = useNavigate();
  const [form] = Form.useForm();

  // 列表状态
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<PerformanceTask[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);

  // 筛选状态
  const [testTypeFilter, setTestTypeFilter] = useState<string | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | undefined>(undefined);

  // 创建弹窗
  const [createOpen, setCreateOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  // 行操作 loading: { [taskKey]: boolean }
  const [actionLoading, setActionLoading] = useState<Record<string, boolean>>({});

  // 拉取列表
  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listTasks({
        page,
        page_size: pageSize,
        test_type: testTypeFilter,
        status: statusFilter,
      });
      const { list, total: t } = normalizeList(res);
      setData(list);
      setTotal(t);
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '加载性能测试任务列表失败');
      setData([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, testTypeFilter, statusFilter]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // 操作: 新建任务
  const handleCreate = async () => {
    try {
      const values = await form.validateFields();
      setCreating(true);
      await createTask({
        name: values.name,
        target_url: values.target_url,
        method: values.method,
        test_type: values.test_type,
        business_volume: values.business_volume,
        headers: {},
        body: {},
      });
      message.success('任务创建成功');
      setCreateOpen(false);
      form.resetFields();
      setPage(1);
      fetchData();
    } catch (e: unknown) {
      if ((e as { errorFields?: unknown })?.errorFields) return;
      const err = e as { message?: string };
      message.error(err?.message || '创建任务失败');
    } finally {
      setCreating(false);
    }
  };

  // 操作: 运行方案
  const handleRunPlan = async (record: PerformanceTask) => {
    setActionLoading((s) => ({ ...s, [`plan-${record.id}`]: true }));
    try {
      await runPlan(record.id);
      message.success(`任务「${record.name}」测试方案已生成`);
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '生成方案失败');
    } finally {
      setActionLoading((s) => ({ ...s, [`plan-${record.id}`]: false }));
    }
  };

  // 操作: 生成/运行脚本
  const handleRunScript = async (record: PerformanceTask) => {
    setActionLoading((s) => ({ ...s, [`script-${record.id}`]: true }));
    try {
      const scriptType = record.script_type || 'auto';
      await runScript(record.id, scriptType);
      message.success(`任务「${record.name}」测试脚本已生成`);
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '生成脚本失败');
    } finally {
      setActionLoading((s) => ({ ...s, [`script-${record.id}`]: false }));
    }
  };

  // 操作: 运行分析
  const handleRunAnalysis = async (record: PerformanceTask) => {
    setActionLoading((s) => ({ ...s, [`analyze-${record.id}`]: true }));
    try {
      await runAnalysis(record.id);
      message.success(`任务「${record.name}」性能分析完成`);
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '运行分析失败');
    } finally {
      setActionLoading((s) => ({ ...s, [`analyze-${record.id}`]: false }));
    }
  };

  // 操作: 启动执行
  const handleExecute = async (record: PerformanceTask) => {
    if (!record.script_content) {
      message.warning('请先生成测试脚本');
      return;
    }
    setActionLoading((s) => ({ ...s, [`execute-${record.id}`]: true }));
    try {
      await executeTask(record.id);
      message.success(`任务「${record.name}」性能测试已启动`);
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '启动执行失败');
    } finally {
      setActionLoading((s) => ({ ...s, [`execute-${record.id}`]: false }));
    }
  };

  // 操作: 停止执行
  const handleStop = async (record: PerformanceTask) => {
    setActionLoading((s) => ({ ...s, [`stop-${record.id}`]: true }));
    try {
      await stopExecute(record.id);
      message.success(`任务「${record.name}」已停止`);
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '停止失败');
    } finally {
      setActionLoading((s) => ({ ...s, [`stop-${record.id}`]: false }));
    }
  };

  // 操作: 删除
  const handleDelete = async (id: number) => {
    try {
      await deleteTask(id);
      message.success('删除成功');
      fetchData();
    } catch (e: unknown) {
      const err = e as { message?: string };
      message.error(err?.message || '删除失败');
    }
  };

  // 表格列
  const columns = [
    {
      title: '任务名称',
      dataIndex: 'name',
      width: 180,
      ellipsis: true,
      render: (text: string, record: PerformanceTask) => (
        <a onClick={() => navigate(`/performance/${record.id}`)}>{text}</a>
      ),
    },
    {
      title: '测试类型',
      dataIndex: 'test_type',
      width: 110,
      render: (t: string) => {
        const meta = TEST_TYPE_META[t] || { color: 'default', text: t };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
    },
    {
      title: '目标URL',
      dataIndex: 'target_url',
      ellipsis: true,
      render: (url: string) => (
        <Tooltip title={url}>
          <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{url || '-'}</span>
        </Tooltip>
      ),
    },
    {
      title: '并发数',
      dataIndex: 'concurrency',
      width: 90,
      align: 'center' as const,
      render: (n: number) => (n ? <Tag color="blue">{n}</Tag> : <span style={{ color: '#bfbfbf' }}>-</span>),
    },
    {
      title: '状态',
      dataIndex: 'status',
      width: 110,
      render: (s: string) => {
        const meta = STATUS_META[s] || { color: 'default', text: s };
        return <Tag color={meta.color}>{meta.text}</Tag>;
      },
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
      width: 440,
      fixed: 'right' as const,
      render: (_: unknown, record: PerformanceTask) => (
        <Space size="small" wrap>
          <Button
            type="link"
            size="small"
            icon={<ThunderboltOutlined />}
            loading={!!actionLoading[`plan-${record.id}`]}
            onClick={() => handleRunPlan(record)}
          >
            方案
          </Button>
          <Button
            type="link"
            size="small"
            icon={<CodeOutlined />}
            loading={!!actionLoading[`script-${record.id}`]}
            onClick={() => handleRunScript(record)}
          >
            脚本
          </Button>
          {record.status === 'running' ? (
            <Button
              type="link"
              size="small"
              danger
              icon={<StopOutlined />}
              loading={!!actionLoading[`stop-${record.id}`]}
              onClick={() => handleStop(record)}
            >
              停止
            </Button>
          ) : (
            <Button
              type="link"
              size="small"
              icon={<PlayCircleOutlined />}
              loading={!!actionLoading[`execute-${record.id}`]}
              disabled={!record.script_content}
              onClick={() => handleExecute(record)}
            >
              执行
            </Button>
          )}
          <Button
            type="link"
            size="small"
            icon={<BarChartOutlined />}
            loading={!!actionLoading[`analyze-${record.id}`]}
            onClick={() => handleRunAnalysis(record)}
          >
            分析
          </Button>
          <Button
            type="link"
            size="small"
            icon={<EyeOutlined />}
            onClick={() => navigate(`/performance/${record.id}`)}
          >
            详情
          </Button>
          <Popconfirm
            title="确认删除该任务?"
            description="删除后无法恢复, 关联结果与指标将一并清除"
            onConfirm={() => handleDelete(record.id)}
            okText="确认"
            cancelText="取消"
            okButtonProps={{ danger: true }}
          >
            <Button type="link" size="small" danger icon={<DeleteOutlined />}>
              删除
            </Button>
          </Popconfirm>
        </Space>
      ),
    },
  ];

  return (
    <Card
      title={
        <Space>
          <ThunderboltOutlined style={{ color: '#1677ff' }} />
          <Title level={4} style={{ margin: 0 }}>性能测试</Title>
          <Tag color="processing">{total}</Tag>
        </Space>
      }
      extra={
        <Space>
          <Select
            placeholder="测试类型"
            value={testTypeFilter}
            onChange={(v) => { setTestTypeFilter(v); setPage(1); }}
            allowClear
            style={{ width: 130 }}
            options={[
              { value: 'api', label: 'API 测试' },
              { value: 'web', label: 'Web 测试' },
            ]}
          />
          <Select
            placeholder="状态"
            value={statusFilter}
            onChange={(v) => { setStatusFilter(v); setPage(1); }}
            allowClear
            style={{ width: 130 }}
            options={Object.entries(STATUS_META).map(([value, meta]) => ({ value, label: meta.text }))}
          />
          <Button icon={<ReloadOutlined />} onClick={fetchData}>刷新</Button>
          <Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>
            新建任务
          </Button>
        </Space>
      }
    >
      <Table
        dataSource={data}
        rowKey="id"
        loading={loading}
        size="middle"
        scroll={{ x: 1200 }}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          showQuickJumper: true,
          showTotal: (t) => `共 ${t} 条`,
          onChange: (p, ps) => { setPage(p); setPageSize(ps); },
        }}
        columns={columns}
      />

      {/* 新建任务弹窗 */}
      <Modal
        title="新建性能测试任务"
        open={createOpen}
        onOk={handleCreate}
        onCancel={() => { setCreateOpen(false); form.resetFields(); }}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
        width={560}
        destroyOnClose
      >
        <Form form={form} layout="vertical" initialValues={{ test_type: 'api', method: 'GET' }}>
          <Form.Item
            name="name"
            label="任务名称"
            rules={[{ required: true, message: '请输入任务名称' }]}
          >
            <Input placeholder="请输入任务名称" maxLength={100} />
          </Form.Item>
          <Form.Item
            name="test_type"
            label="测试类型"
            rules={[{ required: true, message: '请选择测试类型' }]}
          >
            <Select
              options={[
                { value: 'api', label: 'API 测试' },
                { value: 'web', label: 'Web 测试' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="target_url"
            label="目标URL"
            rules={[
              { required: true, message: '请输入目标URL' },
              { type: 'url', message: '请输入合法的URL, 例如 https://example.com' },
            ]}
          >
            <Input placeholder="https://example.com/api/test" />
          </Form.Item>
          <Form.Item
            name="method"
            label="HTTP方法"
            rules={[{ required: true, message: '请选择HTTP方法' }]}
          >
            <Select
              options={[
                { value: 'GET', label: 'GET' },
                { value: 'POST', label: 'POST' },
                { value: 'PUT', label: 'PUT' },
                { value: 'DELETE', label: 'DELETE' },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="business_volume"
            label="日业务量"
            rules={[{ required: true, message: '请输入日业务量' }]}
            tooltip="预估每日业务请求总量, 用于推导并发数与TPS目标"
          >
            <InputNumber<number>
              min={1}
              max={100000000}
              style={{ width: '100%' }}
              placeholder="例如 1000000"
              formatter={(v) => (v != null ? `${v}`.replace(/\B(?=(\d{3})+(?!\d))/g, ',') : '')}
              parser={(v) => Number((v || '').replace(/[^\d]/g, ''))}
            />
          </Form.Item>
        </Form>
      </Modal>
    </Card>
  );
}
